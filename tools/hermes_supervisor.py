#!/usr/bin/env python3
"""Hermes Supervisor policy validation CLI."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import date as calendar_date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PolicyError(ValueError):
    """A policy is invalid and must be rejected."""


class DetectionError(ValueError):
    """Change detection cannot safely read the configured databases."""


class CaptureError(ValueError):
    """A source intent cannot be safely projected or captured."""


class BatchError(ValueError):
    """A Supervisor batch cannot be safely planned or enqueued."""


class StateError(ValueError):
    """Supervisor state cannot be safely read or changed."""


class StateBusyError(StateError):
    """Another process owns the supervisor state lock."""


class StateDurabilityError(StateError):
    """A committed state is visible but its directory sync did not complete."""


class GateError(ValueError):
    """A Stage0 gate input is invalid and must fail closed."""


class ProfileBootstrapError(ValueError):
    """Profile bootstrap discovery or planning failed closed."""


class GCError(ValueError):
    """Minimal stale state-temp collection failed closed."""


class BriefingError(ValueError):
    """A deterministic briefing input or delivery failed closed."""


@dataclass(frozen=True)
class BriefingDecision:
    id: str
    key: str
    question: str
    options: tuple[str, ...]
    recommendation: str
    dangerous: bool
    importance: int


@dataclass(frozen=True)
class BriefingReply:
    answers: dict[str, str]
    unresolved_dangerous: tuple[str, ...]


def parse_briefing_reply(text: str, decisions: tuple[BriefingDecision, ...]) -> BriefingReply:
    """Parse explicit decision answers; recommendations never imply dangerous consent."""
    if type(text) is not str:
        raise BriefingError("invalid briefing reply")
    try:
        if not text or len(text.encode("utf-8", "strict")) > 4096:
            raise BriefingError("invalid briefing reply")
    except UnicodeError as error:
        raise BriefingError("invalid briefing reply") from error
    if type(decisions) is not tuple:
        raise BriefingError("invalid briefing decisions")
    indexed: dict[str, BriefingDecision] = {}
    for decision in decisions:
        if (
            type(decision) is not BriefingDecision
            or re.fullmatch(r"D[1-9][0-9]*", decision.id) is None
            or decision.id in indexed
            or type(decision.options) is not tuple
            or not decision.options
            or any(type(option) is not str or not option for option in decision.options)
            or decision.recommendation not in decision.options
            or type(decision.dangerous) is not bool
        ):
            raise BriefingError("invalid briefing decisions")
        indexed[decision.id] = decision
    answers: dict[str, str] = {}
    fill_remaining = False
    for raw_part in re.split(r"\s*/\s*", text.strip()):
        part = raw_part.strip()
        if part == "残りは推奨":
            if fill_remaining:
                raise BriefingError("duplicate remaining recommendation")
            fill_remaining = True
            continue
        match = re.fullmatch(r"(D[1-9][0-9]*)\s+(.+)", part)
        if match is None:
            raise BriefingError("malformed briefing reply")
        identifier, answer = match.groups()
        if identifier not in indexed:
            raise BriefingError("unknown decision id")
        if identifier in answers:
            raise BriefingError("duplicate decision id")
        if answer not in indexed[identifier].options:
            raise BriefingError("invalid decision answer")
        answers[identifier] = answer
    if fill_remaining:
        for identifier, decision in indexed.items():
            if identifier not in answers and not decision.dangerous:
                answers[identifier] = decision.recommendation
    unresolved = tuple(
        identifier for identifier, decision in indexed.items()
        if decision.dangerous and identifier not in answers
    )
    return BriefingReply(answers, unresolved)


_STATE_JSON_MAX_BYTES = 64 * 1024
_PAYLOAD_JSON_MAX_BYTES = 64 * 1024
_STRICT_JSON_MAX_DEPTH = 32


def _strict_json_loads(
    raw: str,
    *,
    max_bytes: int,
    error_type: type[ValueError],
    message: str,
) -> Any:
    """Decode bounded RFC JSON without duplicate names or non-finite constants."""
    try:
        if type(raw) is not str:
            raise ValueError("not text")
        if len(raw.encode("utf-8", "strict")) > max_bytes:
            raise ValueError("too large")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate name")
                result[key] = value
            return result

        def reject_constant(_value: str) -> Any:
            raise ValueError("nonstandard constant")

        value = json.loads(
            raw, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
        stack = [(value, 1)]
        while stack:
            current, depth = stack.pop()
            if depth > _STRICT_JSON_MAX_DEPTH:
                raise ValueError("nesting too deep")
            if type(current) is dict:
                stack.extend((item, depth + 1) for item in current.values())
            elif type(current) is list:
                stack.extend((item, depth + 1) for item in current)
            elif type(current) is str:
                current.encode("utf-8", "strict")
            elif type(current) is float and not math.isfinite(current):
                raise ValueError("non-finite number")
        return value
    except error_type:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError, TypeError, ValueError) as error:
        raise error_type(message) from error


def _load_state_json(payload: bytes) -> Any:
    try:
        if type(payload) is not bytes or len(payload) > _STATE_JSON_MAX_BYTES:
            raise StateError("invalid supervisor state")
        raw = payload.decode("utf-8", "strict")
    except StateError:
        raise
    except UnicodeError as error:
        raise StateError("invalid supervisor state") from error
    return _strict_json_loads(
        raw,
        max_bytes=_STATE_JSON_MAX_BYTES,
        error_type=StateError,
        message="invalid supervisor state",
    )


_BOOTSTRAP_ROLES = ("supervisor", "researcher", "builder", "verifier")
_PROMPT_SIZE_LIMIT = 16_384
_PROMPT_VERSION = "hermes-supervisor-role/v1"
_PROMPT_VERSION_HEADER = f"Prompt-Version: {_PROMPT_VERSION}"
_APPROVED_PROMPT_DIGESTS = {
    "supervisor": "c88ba3744f2271f9d5771dfeccd2ac1fb00632ce169dd4298ac7dfd06d65416b",
    "researcher": "c8e1b4200b542c6546a504b5c02a889876e0e3b75a505cb41d3a0b19c1a93a05",
    "builder": "9b322b92db0a6ef416ff473c752096ff8f38f337c9ba9c6eb82d71d5712b7369",
    "verifier": "9e7e5cd59cbb2a6422335d913e7be429e4f023732d4ddbbd4dc2a3e964cf5f32",
}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_PROMPT_DIR = (
    _REPOSITORY_ROOT / "home" / "modules" / "ai" / "hermes-supervisor" / "prompts"
)


@dataclass(frozen=True)
class PromptSource:
    role: str
    path: Path
    text: str
    version: str
    digest: str


def _validate_prompt_payload(role: str, payload: bytes) -> tuple[str, str]:
    if len(payload) <= 0 or len(payload) > _PROMPT_SIZE_LIMIT:
        raise ProfileBootstrapError(f"prompt source size invalid: {role}")
    try:
        text = payload.decode("utf-8", "strict")
        text.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ProfileBootstrapError(f"prompt source is not strict UTF-8: {role}") from error
    if not text.startswith(_PROMPT_VERSION_HEADER + "\n"):
        raise ProfileBootstrapError(f"prompt version invalid: {role}")
    if text.splitlines()[0] != _PROMPT_VERSION_HEADER:
        raise ProfileBootstrapError(f"prompt version invalid: {role}")
    folded = text.casefold()
    required = (
        "# role", "# read/write boundary", "# forbidden", "# completion contract",
        "05-private/", "read", "write", "list", "search", "no exceptions",
        "tools enforce",
    )
    role_required = {
        "supervisor": (
            "form", "triage", "plan", "dispatch", "review", "kanban", "audit",
            "does not implement", "patch project", "apply", "commit", "push", "deploy",
            "self-approve", "decision", "action", "reason code", "card", "source ids",
            "acceptance", "risks", "rollback", "human gates", "evidence",
        ),
        "researcher": (
            "strictly read-only", "project", "kanban", "external writes", "patch",
            "apply", "commit", "push", "evidence", "citations", "uncertainty",
            "unresolved assumptions", "recommendation", "facts",
        ),
        "builder": (
            "disposable", "scratch", "worktree", "sandbox", "verify the assigned path",
            "live workspace", "live configuration", "live service", "apply", "deploy",
            "commit", "push", "secrets", "artifact", "diff path", "tests",
            "actual results", "residual risks", "rollback",
            "never claim completion without evidence",
        ),
        "verifier": (
            "independently", "evidence only", "bounded read-only", "test caches",
            "source mutation", "does not self-fix", "patch", "alter the artifact",
            "pass/fail/blocked", "acceptance criterion", "failures", "residual risk",
            "required next action",
        ),
    }
    if (
        any(fragment not in folded for fragment in required)
        or any(fragment not in folded for fragment in role_required[role])
        or "do not request or store hidden reasoning" not in folded
    ):
        raise ProfileBootstrapError(f"prompt contract invalid: {role}")
    if "chain-of-thought" in folded:
        raise ProfileBootstrapError(f"prompt requests forbidden reasoning: {role}")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != _APPROVED_PROMPT_DIGESTS[role]:
        raise ProfileBootstrapError(f"prompt digest is not approved: {role}")
    return text, digest


def _read_prompt_fd(directory_fd: int, role: str) -> bytes:
    name = f"{role}.md"
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        file_fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as error:
        raise ProfileBootstrapError(f"prompt source must be a regular file: {role}") from error
    try:
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ProfileBootstrapError(
                f"prompt source must be a single-link regular file: {role}"
            )
        if metadata.st_size <= 0 or metadata.st_size > _PROMPT_SIZE_LIMIT:
            raise ProfileBootstrapError(f"prompt source size invalid: {role}")
        payload = bytearray()
        while len(payload) <= _PROMPT_SIZE_LIMIT:
            chunk = os.read(file_fd, min(8192, _PROMPT_SIZE_LIMIT + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != metadata.st_size or len(payload) > _PROMPT_SIZE_LIMIT:
            raise ProfileBootstrapError(f"prompt source size changed: {role}")
        return bytes(payload)
    finally:
        os.close(file_fd)


def _lexical_absolute_path(path: Path) -> Path:
    def forbidden(part: str) -> bool:
        return part == ".." or part.casefold() == "05-private"

    if type(path) is not type(Path()) or any(forbidden(part) for part in path.parts):
        raise ProfileBootstrapError("invalid prompt directory")
    absolute = path if path.is_absolute() else Path(os.getcwd()) / path
    if any(forbidden(part) for part in absolute.parts):
        raise ProfileBootstrapError("invalid prompt directory")
    return Path(os.path.normpath(absolute))


def validate_prompt_sources(prompt_dir: Path) -> tuple[PromptSource, ...]:
    """Read approved prompts through component-anchored, no-follow descriptors."""
    absolute_prompt_dir = _lexical_absolute_path(prompt_dir)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise ProfileBootstrapError("prompt source read requires O_NOFOLLOW")
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | nofollow | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd: int | None = None
    try:
        try:
            directory_fd = os.open("/", directory_flags)
            for component in absolute_prompt_dir.parts[1:]:
                next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
                try:
                    if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                        raise ProfileBootstrapError(
                            "prompt directory must be a regular directory"
                        )
                except BaseException:
                    os.close(next_fd)
                    raise
                os.close(directory_fd)
                directory_fd = next_fd
        except OSError as error:
            raise ProfileBootstrapError("prompt directory must be a regular directory") from error
        metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ProfileBootstrapError("prompt directory must be a regular directory")
        expected = {f"{role}.md" for role in _BOOTSTRAP_ROLES}
        allowed = expected | {"briefing.md"}
        actual = set(os.listdir(directory_fd))
        missing = expected - actual
        extra = actual - allowed
        if missing:
            raise ProfileBootstrapError(f"prompt source missing: {sorted(missing)[0]}")
        if extra:
            raise ProfileBootstrapError(f"unexpected prompt source: {sorted(extra)[0]}")
        result: list[PromptSource] = []
        for role in _BOOTSTRAP_ROLES:
            payload = _read_prompt_fd(directory_fd, role)
            text, digest = _validate_prompt_payload(role, payload)
            result.append(PromptSource(
                role, absolute_prompt_dir / f"{role}.md", text, _PROMPT_VERSION, digest
            ))
        return tuple(result)
    except ProfileBootstrapError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        raise ProfileBootstrapError(f"prompt source read failed ({type(error).__name__})") from error
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


_PROFILE_LIST_SIZE_LIMIT = 65_536
_PROFILE_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SGR = re.compile(r"\x1b\[[0-9;]*m")
_PROFILE_DESCRIPTIONS = {
    "supervisor": "Coordinates triage, planning, dispatch, and evidence review through Kanban and audit records.",
    "researcher": "Performs read-only research and reports sourced facts, uncertainty, and recommendations.",
    "builder": "Implements assigned changes only in a disposable scratch, worktree, or sandbox.",
    "verifier": "Independently verifies acceptance criteria and returns an evidence-based verdict.",
}
_PROMPT_SOURCE_PREFIX = "home/modules/ai/hermes-supervisor/prompts"


@dataclass(frozen=True)
class ProfileList:
    profiles: tuple[str, ...]
    active_profile: str | None


@dataclass(frozen=True)
class ProfileBootstrapOperation:
    profile: str
    status: str
    argv: tuple[str, ...] | None
    prompt_source: str
    description: str


def parse_profile_list(text: str) -> ProfileList:
    """Parse the public ``hermes profile list`` table, failing closed."""
    if type(text) is not str:
        raise ProfileBootstrapError("profile list output must be text")
    try:
        encoded = text.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ProfileBootstrapError("profile list output is not strict UTF-8") from error
    if len(encoded) > _PROFILE_LIST_SIZE_LIMIT:
        raise ProfileBootstrapError("profile list output exceeds limit")
    cleaned = _SGR.sub("", text)
    if any(
        (character.isspace() and character not in (" ", "\n"))
        or (character != "\n" and unicodedata.category(character).startswith("C"))
        for character in cleaned
    ):
        raise ProfileBootstrapError("profile list output has control data")
    lines = cleaned.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 3 or lines[0].split() != [
        "Profile", "Model", "Gateway", "Alias", "Distribution",
    ]:
        raise ProfileBootstrapError("profile list header is invalid")
    separator = lines[1].split()
    if len(separator) != 5 or any(re.fullmatch(r"[-─]+", part) is None for part in separator):
        raise ProfileBootstrapError("profile list separator is invalid")
    profiles: list[str] = []
    active: str | None = None
    for line in lines[2:]:
        fields = line.split()
        if not fields:
            raise ProfileBootstrapError("profile list contains blank row")
        marked = False
        if fields[0] == "◆":
            marked = True
            fields = fields[1:]
        elif fields[0].startswith("◆"):
            marked = True
            fields[0] = fields[0][1:]
        if len(fields) != 5:
            raise ProfileBootstrapError("profile list row is truncated")
        profile = fields[0]
        if len(profile) > 64 or _PROFILE_TOKEN.fullmatch(profile) is None:
            raise ProfileBootstrapError("profile list has invalid profile token")
        if profile in profiles:
            raise ProfileBootstrapError("profile list has duplicate profile")
        profiles.append(profile)
        if marked:
            if active is not None:
                raise ProfileBootstrapError("profile list has multiple active profiles")
            active = profile
    if "default" not in profiles:
        raise ProfileBootstrapError("source profile default is absent")
    return ProfileList(tuple(profiles), active)


def _validate_executable(executable: str) -> str:
    if type(executable) is not str or not executable or "\x00" in executable:
        raise ProfileBootstrapError("invalid Hermes executable")
    try:
        executable.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ProfileBootstrapError("invalid Hermes executable") from error
    return executable


def _validate_profile_list_model(profiles: ProfileList) -> set[str]:
    if type(profiles) is not ProfileList or type(profiles.profiles) is not tuple:
        raise ProfileBootstrapError("invalid profile list model")
    checked: list[str] = []
    for profile in profiles.profiles:
        if (
            type(profile) is not str
            or len(profile) > 64
            or _PROFILE_TOKEN.fullmatch(profile) is None
            or profile in checked
        ):
            raise ProfileBootstrapError("invalid profile list model")
        checked.append(profile)
    if "default" not in checked:
        raise ProfileBootstrapError("source profile default is absent")
    if profiles.active_profile is not None and (
        type(profiles.active_profile) is not str
        or profiles.active_profile not in checked
    ):
        raise ProfileBootstrapError("invalid active profile")
    return set(checked)


def _validate_planner_prompt_sources(
    prompt_sources: tuple[PromptSource, ...],
) -> None:
    if type(prompt_sources) is not tuple or len(prompt_sources) != len(_BOOTSTRAP_ROLES):
        raise ProfileBootstrapError("invalid prompt source set")
    for role, source in zip(_BOOTSTRAP_ROLES, prompt_sources, strict=True):
        canonical_path = _CANONICAL_PROMPT_DIR / f"{role}.md"
        if (
            type(source) is not PromptSource
            or type(source.role) is not str
            or source.role != role
            or type(source.path) is not type(canonical_path)
            or source.path != canonical_path
            or not source.path.is_absolute()
            or type(source.text) is not str
            or type(source.version) is not str
            or source.version != _PROMPT_VERSION
            or type(source.digest) is not str
            or source.digest != _APPROVED_PROMPT_DIGESTS[role]
        ):
            raise ProfileBootstrapError("invalid prompt source set")
        try:
            payload = source.text.encode("utf-8", "strict")
        except UnicodeError as error:
            raise ProfileBootstrapError("invalid prompt source set") from error
        _, computed_digest = _validate_prompt_payload(role, payload)
        if computed_digest != source.digest:
            raise ProfileBootstrapError("invalid prompt source digest")


def _validate_bootstrap_operation(
    operation: ProfileBootstrapOperation,
    *,
    role: str,
    status: str,
    executable: str,
) -> None:
    description = _PROFILE_DESCRIPTIONS[role]
    expected_argv = None if status == "skip_existing" else (
        executable, "profile", "create", role, "--clone-from", "default",
        "--description", description,
    )
    if (
        type(operation) is not ProfileBootstrapOperation
        or operation.profile != role
        or operation.status != status
        or operation.argv != expected_argv
        or operation.prompt_source != f"{_PROMPT_SOURCE_PREFIX}/{role}.md"
        or operation.description != description
    ):
        raise ProfileBootstrapError("invalid bootstrap operation")


def plan_profile_bootstrap(
    profiles: ProfileList,
    prompt_sources: tuple[PromptSource, ...],
    *,
    executable: str,
) -> tuple[ProfileBootstrapOperation, ...]:
    """Produce an idempotent create/skip plan from exact validated models."""
    checked_executable = _validate_executable(executable)
    existing = _validate_profile_list_model(profiles)
    _validate_planner_prompt_sources(prompt_sources)
    operations: list[ProfileBootstrapOperation] = []
    for role in _BOOTSTRAP_ROLES:
        description = _PROFILE_DESCRIPTIONS[role]
        status = "skip_existing" if role in existing else "create"
        argv = None if status == "skip_existing" else (
            checked_executable, "profile", "create", role, "--clone-from", "default",
            "--description", description,
        )
        operation = ProfileBootstrapOperation(
            role, status, argv, f"{_PROMPT_SOURCE_PREFIX}/{role}.md", description
        )
        _validate_bootstrap_operation(
            operation, role=role, status=status, executable=checked_executable
        )
        operations.append(operation)
    return tuple(operations)


class _BoundedOutputError(ValueError):
    """A production child exceeded one per-stream output limit."""


def _kill_and_reap(
    process: subprocess.Popen[bytes], parent_process_group: int,
) -> None:
    try:
        if process.returncode is None:
            if process.pid == parent_process_group:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
    finally:
        process.wait()


def _bounded_subprocess_run(
    argv: list[str], *, environment: dict[str, str], timeout: float, output_limit: int,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated child while enforcing live per-stream byte limits."""
    parent_process_group = os.getpgrp()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=dict(environment),
        start_new_session=True,
        bufsize=0,
    )
    selector = None
    finished = False
    try:
        selector = selectors.DefaultSelector()
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + timeout
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("subprocess pipes unavailable")
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            events = selector.select(remaining_time)
            if not events:
                raise subprocess.TimeoutExpired(argv, timeout)
            for key, _ in events:
                name = key.data
                output = streams[name]
                chunk = os.read(key.fd, output_limit + 1 - len(output))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output.extend(chunk)
                if len(output) > output_limit:
                    raise _BoundedOutputError("subprocess output exceeds limit")
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        stdout = bytes(streams["stdout"]).decode("utf-8", "strict")
        stderr = bytes(streams["stderr"]).decode("utf-8", "strict")
        returncode = process.wait(timeout=remaining_time)
        finished = True
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)
    finally:
        has_operational_error = sys.exception() is not None
        cleanup_errors: list[BaseException] = []

        def cleanup(operation: Callable[[], Any]) -> None:
            try:
                operation()
            except BaseException as error:
                cleanup_errors.append(error)

        if selector is not None:
            cleanup(selector.close)
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                cleanup(pipe.close)
        if not finished:
            cleanup(lambda: _kill_and_reap(process, parent_process_group))
        if cleanup_errors and not has_operational_error:
            raise cleanup_errors[0]


class HermesProfileClient:
    """Read-only client for the public Hermes profile listing command."""

    def __init__(
        self,
        executable: str,
        *,
        runner: Callable[..., Any] | None = None,
        timeout: float = 30.0,
        output_limit: int = _PROFILE_LIST_SIZE_LIMIT,
        base_env: Mapping[str, str] | None = None,
    ):
        self.executable = _validate_executable(executable)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ProfileBootstrapError("invalid profile list timeout")
        if type(output_limit) is not int or output_limit <= 0:
            raise ProfileBootstrapError("invalid profile list output limit")
        try:
            environment = dict(os.environ if base_env is None else base_env)
        except (TypeError, ValueError) as error:
            raise ProfileBootstrapError("invalid subprocess environment") from error
        if any(type(key) is not str or type(value) is not str for key, value in environment.items()):
            raise ProfileBootstrapError("invalid subprocess environment")
        self.runner = runner
        self.timeout = timeout
        self.output_limit = output_limit
        self.base_env = environment

    def _production_run(self, argv: list[str], environment: dict[str, str]) -> Any:
        try:
            return _bounded_subprocess_run(
                argv, environment=environment, timeout=self.timeout,
                output_limit=self.output_limit,
            )
        except _BoundedOutputError as error:
            raise ProfileBootstrapError("profile list output exceeds limit") from error
        except UnicodeError as error:
            raise ProfileBootstrapError("profile list output is not strict UTF-8") from error

    def list_profiles(self) -> ProfileList:
        argv = [self.executable, "profile", "list"]
        environment = dict(self.base_env)
        try:
            if self.runner is None:
                completed = self._production_run(argv, environment)
            else:
                completed = self.runner(
                    argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    encoding="utf-8", errors="strict", timeout=self.timeout, check=False,
                    shell=False, env=environment,
                )
        except ProfileBootstrapError:
            raise
        except subprocess.TimeoutExpired as error:
            raise ProfileBootstrapError("Hermes profile list timed out") from error
        except Exception as error:
            raise ProfileBootstrapError(
                f"Hermes profile list failed ({type(error).__name__})"
            ) from error
        if type(getattr(completed, "returncode", None)) is not int:
            raise ProfileBootstrapError("Hermes profile list returned invalid result")
        stdout = getattr(completed, "stdout", None)
        stderr = getattr(completed, "stderr", None)
        if type(stdout) is not str or type(stderr) is not str:
            raise ProfileBootstrapError("Hermes profile list returned invalid output")
        try:
            stdout_size = len(stdout.encode("utf-8", "strict"))
            stderr_size = len(stderr.encode("utf-8", "strict"))
        except UnicodeError as error:
            raise ProfileBootstrapError("profile list output is not strict UTF-8") from error
        if stdout_size > self.output_limit or stderr_size > self.output_limit:
            raise ProfileBootstrapError("profile list output exceeds limit")
        if completed.returncode != 0:
            raise ProfileBootstrapError(
                f"Hermes profile list exited with status {completed.returncode}"
            )
        return parse_profile_list(stdout)


def _ensure_private_directory(path: Path) -> None:
    """Create missing directory levels privately without altering existing ones."""
    try:
        os.mkdir(path, 0o700)
    except FileNotFoundError:
        _ensure_private_directory(path.parent)
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            if not stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode):
                raise NotADirectoryError(path)
            return
    except FileExistsError:
        if not stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode):
            raise NotADirectoryError(path)
        return

    # Only a successful mkdir grants permission to alter this directory.
    os.chmod(path, 0o700, follow_symlinks=False)
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class DailyBudget:
    date: str | None
    supervisor_runs: int
    dispatches: int
    paid_worker_usd: int


@dataclass(frozen=True)
class SupervisorState:
    schema_version: int
    mode: str
    control_state: str
    last_message_id: int
    last_event_id: int
    last_supervisor_enqueued_at: int | None
    daily_budget: DailyBudget
    pending_message_ids: tuple[int, ...]
    pending_event_ids: tuple[int, ...]
    last_accepted_primary_goal_id: str | None
    extractor_version: str
    emergency_stop_requested_at: int | None
    last_supervisor_message_id: int = 0
    last_supervisor_event_id: int = 0


@dataclass(frozen=True)
class GateRequest:
    kind: str
    goal_id: str | None = None
    active_worker_count: int = 0
    paid_worker_usd: int = 0
    safety_critical: bool = False
    data_loss_risk: bool = False


@dataclass(frozen=True)
class GateDecision:
    action: str
    reason_code: str
    effective_budget: DailyBudget
    next_primary_goal_id: str | None


def initial_supervisor_state(*, frozen: bool = False) -> SupervisorState:
    return SupervisorState(
        schema_version=2,
        mode="shadow",
        control_state="frozen" if frozen else "running",
        last_message_id=0,
        last_event_id=0,
        last_supervisor_enqueued_at=None,
        daily_budget=DailyBudget(None, 0, 0, 0),
        pending_message_ids=(),
        pending_event_ids=(),
        last_accepted_primary_goal_id=None,
        extractor_version="v1",
        emergency_stop_requested_at=None,
        last_supervisor_message_id=0,
        last_supervisor_event_id=0,
    )


_STATE_V1_KEYS = {
    "schema_version", "mode", "control_state", "last_message_id", "last_event_id",
    "last_supervisor_enqueued_at", "daily_budget", "pending_message_ids",
    "pending_event_ids", "last_accepted_primary_goal_id", "extractor_version",
    "emergency_stop_requested_at",
}
_STATE_KEYS = _STATE_V1_KEYS | {
    "last_supervisor_message_id", "last_supervisor_event_id",
}
_BUDGET_KEYS = {"date", "supervisor_runs", "dispatches", "paid_worker_usd"}


def _state_object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise StateError(f"{label}: expected object")
    unknown = set(value) - keys
    missing = keys - set(value)
    if unknown:
        raise StateError(f"{label}: unknown key {sorted(unknown)[0]!r}")
    if missing:
        raise StateError(f"{label}: missing key {sorted(missing)[0]!r}")
    return value


def _state_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise StateError(f"{label}: expected integer >= 0")
    return value


def _state_optional_int(value: Any, label: str) -> int | None:
    return None if value is None else _state_int(value, label)


def _state_ids(value: Any, label: str) -> tuple[int, ...]:
    if type(value) is not list:
        raise StateError(f"{label}: expected array")
    result = tuple(_state_int(item, label) for item in value)
    if len(result) != len(set(result)):
        raise StateError(f"{label}: duplicate id")
    return result


def _validate_pending_cursor(
    cursor: Any, pending: Any, *, cursor_label: str, pending_label: str
) -> tuple[int, tuple[int, ...]]:
    checked_cursor = _state_int(cursor, cursor_label)
    if type(pending) is not tuple:
        raise StateError(f"{pending_label}: expected tuple")
    checked_pending = tuple(_state_int(item, pending_label) for item in pending)
    if len(checked_pending) != len(set(checked_pending)):
        raise StateError(f"{pending_label}: duplicate id")
    if any(identifier > checked_cursor for identifier in checked_pending):
        raise StateError(f"{pending_label}: id beyond cursor")
    return checked_cursor, checked_pending


def _state_optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise StateError(f"{label}: expected non-empty string or null")
    return value


def _state_from_data(value: Any) -> SupervisorState:
    if type(value) is not dict:
        raise StateError("state: expected object")
    version = _state_int(value.get("schema_version"), "schema_version")
    legacy = version == 1
    if version not in (1, 2):
        raise StateError("schema_version: incompatible")
    root = _state_object(value, "state", _STATE_V1_KEYS if legacy else _STATE_KEYS)
    if root["mode"] not in ("shadow", "limited", "eco") or type(root["mode"]) is not str:
        raise StateError("mode: invalid")
    if (root["control_state"] not in
            ("running", "paused", "frozen", "emergency_stopped")
            or type(root["control_state"]) is not str):
        raise StateError("control_state: invalid")
    budget_data = _state_object(root["daily_budget"], "daily_budget", _BUDGET_KEYS)
    budget_date = budget_data["date"]
    if budget_date is not None:
        if type(budget_date) is not str:
            raise StateError("daily_budget.date: invalid")
        try:
            if calendar_date.fromisoformat(budget_date).isoformat() != budget_date:
                raise ValueError
        except ValueError as error:
            raise StateError("daily_budget.date: invalid") from error
    extractor = root["extractor_version"]
    if type(extractor) is not str or extractor != "v1":
        raise StateError("extractor_version: incompatible")
    state = SupervisorState(
        schema_version=2,
        mode=root["mode"],
        control_state=root["control_state"],
        last_message_id=_state_int(root["last_message_id"], "last_message_id"),
        last_event_id=_state_int(root["last_event_id"], "last_event_id"),
        last_supervisor_enqueued_at=_state_optional_int(
            root["last_supervisor_enqueued_at"], "last_supervisor_enqueued_at"
        ),
        daily_budget=DailyBudget(
            date=budget_date,
            supervisor_runs=_state_int(budget_data["supervisor_runs"], "supervisor_runs"),
            dispatches=_state_int(budget_data["dispatches"], "dispatches"),
            paid_worker_usd=_state_int(budget_data["paid_worker_usd"], "paid_worker_usd"),
        ),
        pending_message_ids=_state_ids(root["pending_message_ids"], "pending_message_ids"),
        pending_event_ids=_state_ids(root["pending_event_ids"], "pending_event_ids"),
        last_accepted_primary_goal_id=_state_optional_string(
            root["last_accepted_primary_goal_id"], "last_accepted_primary_goal_id"
        ),
        extractor_version=extractor,
        emergency_stop_requested_at=_state_optional_int(
            root["emergency_stop_requested_at"], "emergency_stop_requested_at"
        ),
        last_supervisor_message_id=(
            0 if legacy else _state_int(
                root["last_supervisor_message_id"], "last_supervisor_message_id"
            )
        ),
        last_supervisor_event_id=(
            0 if legacy else _state_int(
                root["last_supervisor_event_id"], "last_supervisor_event_id"
            )
        ),
    )
    _validate_pending_cursor(
        state.last_message_id,
        state.pending_message_ids,
        cursor_label="last_message_id",
        pending_label="pending_message_ids",
    )
    _validate_pending_cursor(
        state.last_event_id,
        state.pending_event_ids,
        cursor_label="last_event_id",
        pending_label="pending_event_ids",
    )
    return state


class StateLock:
    """Nonblocking process lock; StateStore mutations acquire this internally."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> StateLock:
        _ensure_private_directory(self.path.parent)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if type(nofollow) is not int:
            raise StateError("lock open failed: O_NOFOLLOW unavailable")
        flags = os.O_RDWR | os.O_CREAT | nofollow
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise StateError(f"lock open failed: {error}") from error
        try:
            try:
                metadata = os.fstat(fd)
            except OSError as error:
                raise StateError(f"lock fstat failed: {error}") from error
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise StateError("lock path must be a single-link regular file")
            try:
                os.fchmod(fd, 0o600)
            except OSError as error:
                raise StateError(f"lock fchmod failed: {error}") from error
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StateBusyError("supervisor state is busy") from error
            except OSError as error:
                raise StateError(f"lock flock failed: {error}") from error
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self._fd is not None
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class StateStore:
    def __init__(self, path: Path, *, clock: Any | None = None):
        self.path = path
        self.clock = clock
        self.lock_path = path.with_name(path.name + ".lock")

    def initialize(self) -> SupervisorState:
        try:
            return self._initialize()
        except StateError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise StateError(f"state initialization failed: {error}") from error

    def _initialize(self) -> SupervisorState:
        with StateLock(self.lock_path):
            if self.path.exists():
                try:
                    return self.read()
                except StateError:
                    return self._recover_unlocked()
            state = initial_supervisor_state()
            self._write_unlocked(state)
            return state

    def _recover_unlocked(self) -> SupervisorState:
        now = self.clock() if self.clock is not None else int(time.time())
        timestamp = _state_int(now, "recovery timestamp")
        base = Path(f"{self.path}.corrupt.{timestamp}")
        quarantine = base
        suffix = 0
        try:
            while True:
                try:
                    os.link(self.path, quarantine, follow_symlinks=False)
                    break
                except FileExistsError:
                    suffix += 1
                    quarantine = Path(f"{base}.{suffix}")
            state = initial_supervisor_state(frozen=True)
            self._write_unlocked(state)
            return state
        except StateError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise StateError(f"state recovery failed: {error}") from error

    def read(self) -> SupervisorState:
        try:
            with self.path.open("rb") as stream:
                payload = stream.read(_STATE_JSON_MAX_BYTES + 1)
            return _state_from_data(_load_state_json(payload))
        except StateError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise StateError(f"invalid supervisor state: {error}") from error

    def write(self, state: SupervisorState) -> None:
        # Validate even explicitly constructed dataclasses before persistence.
        try:
            canonical = json.dumps(asdict(state), ensure_ascii=True, separators=(",", ":"))
            _state_from_data(_strict_json_loads(
                canonical, max_bytes=_STATE_JSON_MAX_BYTES, error_type=StateError,
                message="invalid supervisor state",
            ))
            with StateLock(self.lock_path):
                self._write_unlocked(state)
        except StateError:
            raise
        except (OSError, TypeError, ValueError, RecursionError) as error:
            raise StateError(f"state write failed: {error}") from error

    def set_mode(self, mode: str) -> tuple[SupervisorState, bool]:
        if type(mode) is not str or mode not in ("shadow", "limited", "eco"):
            raise StateError("mode: invalid")
        try:
            with StateLock(self.lock_path):
                if self.path.exists():
                    try:
                        state = self.read()
                    except StateError:
                        state = self._recover_unlocked()
                else:
                    state = initial_supervisor_state()
                changed = state.mode != mode
                state = replace(state, mode=mode)
                if changed or not self.path.exists():
                    self._write_unlocked(state)
                return state, changed
        except StateError:
            raise
        except (OSError, TypeError, ValueError, RecursionError) as error:
            raise StateError(f"state mode change failed: {error}") from error

    def record_frozen_observation(self, changes: ChangeSet) -> SupervisorState:
        try:
            with StateLock(self.lock_path):
                if self.path.exists():
                    try:
                        state = self.read()
                    except StateError:
                        state = self._recover_unlocked()
                else:
                    state = initial_supervisor_state()
                changed = record_frozen_observation(state, changes)
                self._write_unlocked(changed)
                return changed
        except StateError:
            raise
        except (OSError, TypeError, ValueError, RecursionError) as error:
            raise StateError(f"state observation failed: {error}") from error

    def control(self, action: str) -> SupervisorState:
        if action not in ("pause", "freeze", "resume", "emergency-stop"):
            raise StateError(f"invalid control action: {action}")
        try:
            return self._control(action)
        except StateError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise StateError(f"state control failed: {error}") from error

    def _control(self, action: str) -> SupervisorState:
        with StateLock(self.lock_path):
            if self.path.exists():
                try:
                    state = self.read()
                except StateError:
                    state = self._recover_unlocked()
            else:
                state = initial_supervisor_state()
            now = None
            if action == "emergency-stop":
                now = self.clock() if self.clock is not None else int(time.time())
            changed = transition_control(state, action, now=now)
            self._write_unlocked(changed)
            return changed

    def emergency_stop(self, callback: Callable[[], None]) -> SupervisorState:
        # Persistence completes before any callback that might later terminate work.
        stopped = self.control("emergency-stop")
        callback()
        return stopped

    def _write_unlocked(self, state: SupervisorState) -> None:
        """Atomically persist state; caller must hold this store's StateLock."""
        if type(state) is not SupervisorState or state.schema_version != 2:
            raise StateError("state model must use schema_version 2")
        canonical = json.dumps(asdict(state), ensure_ascii=True, separators=(",", ":"))
        _state_from_data(_strict_json_loads(
            canonical, max_bytes=_STATE_JSON_MAX_BYTES, error_type=StateError,
            message="invalid supervisor state",
        ))
        _ensure_private_directory(self.path.parent)
        payload = (json.dumps(asdict(state), ensure_ascii=True, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
        temporary = self.path.with_name(
            f".{self.path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
        )
        fd: int | None = None
        replaced = False
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                fd = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            replaced = True
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except StateError:
            raise
        except OSError as error:
            if replaced:
                raise StateDurabilityError(
                    f"state commit durability is uncertain: {error}"
                ) from error
            raise
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


_GC_TEMP_NAME = re.compile(r"\.state\.json\.tmp\.[0-9]+\.[0-9a-f]{16}")


@dataclass(frozen=True)
class GCResult:
    candidates: tuple[str, ...]
    deleted: tuple[str, ...]


def parse_older_than(value: str) -> int:
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]*d", value) is None:
        raise GCError("--older-than must be a positive Nd value")
    try:
        days = int(value[:-1])
    except (TypeError, ValueError, OverflowError) as error:
        raise GCError("--older-than must be a positive Nd value") from error
    if days > 365_000:
        raise GCError("--older-than is too large")
    return days


def _open_gc_root(root: Path) -> int | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise GCError("GC requires O_NOFOLLOW")
    try:
        return os.open(root, flags | nofollow)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise GCError("state root must be a non-symlink directory") from error


def _gc_candidates(directory_fd: int, cutoff: float) -> tuple[str, ...]:
    candidates: list[str] = []
    try:
        names = os.listdir(directory_fd)
        for name in names:
            if type(name) is not str or _GC_TEMP_NAME.fullmatch(name) is None:
                continue
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(metadata.st_mode) and metadata.st_mtime <= cutoff:
                candidates.append(name)
    except (OSError, TypeError, ValueError) as error:
        raise GCError("state temp scan failed") from error
    return tuple(sorted(candidates))


def collect_stale_state_temps(
    root: Path,
    days: int,
    *,
    now: int | float,
    dry_run: bool,
) -> GCResult:
    """Delete only stale StateStore atomic-write leftovers directly under root."""
    path_type = type(Path())
    if type(root) is not path_type or not root.is_absolute():
        raise GCError("state root must be an absolute path")
    if type(days) is not int or days <= 0 or days > 365_000:
        raise GCError("retention days must be a positive integer")
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise GCError("GC time must be finite and nonnegative")
    if type(dry_run) is not bool:
        raise GCError("dry-run flag must be boolean")
    cutoff = float(now) - days * 86400
    directory_fd = _open_gc_root(root)
    if directory_fd is None:
        return GCResult((), ())
    try:
        original = os.fstat(directory_fd)
        if not stat.S_ISDIR(original.st_mode):
            raise GCError("state root must be a directory")
        if dry_run:
            return GCResult(_gc_candidates(directory_fd, cutoff), ())
        with StateLock(root / "state.json.lock"):
            try:
                current = os.stat(root, follow_symlinks=False)
            except OSError as error:
                raise GCError("state root changed during GC") from error
            if (
                not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)
            ):
                raise GCError("state root changed during GC")
            candidates = _gc_candidates(directory_fd, cutoff)
            deleted: list[str] = []
            for name in candidates:
                try:
                    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mtime > cutoff:
                        continue
                    os.unlink(name, dir_fd=directory_fd)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise GCError("state temp deletion failed") from error
                deleted.append(name)
            return GCResult(candidates, tuple(deleted))
    except (GCError, StateError):
        raise
    except (OSError, TypeError, ValueError) as error:
        raise GCError("state temp GC failed") from error
    finally:
        os.close(directory_fd)


@dataclass(frozen=True)
class MessageChange:
    id: int
    session_id: str
    content: str
    timestamp: float
    compacted: bool


@dataclass(frozen=True)
class CaptureProjection:
    source_profile: str
    source_session_id: str
    source_message_id: int
    source_timestamp: float
    extractor_version: str
    idempotency_key: str
    title: str
    body: str
    relation_kind: str | None
    relation_target: None = None


@dataclass(frozen=True)
class SupervisorBatchProjection:
    title: str
    body: str
    idempotency_key: str
    message_ids: tuple[int, ...]
    event_ids: tuple[int, ...]
    emergency: bool
    safety_critical: bool
    data_loss_risk: bool
    mode: str
    start_message_id: int
    start_event_id: int
    proposed_message_id: int
    proposed_event_id: int


@dataclass(frozen=True)
class CreatedCardRef:
    id: str
    title: str
    status: str
    existing: bool = False


@dataclass(frozen=True)
class SupervisorBatchAck:
    card: CreatedCardRef
    acknowledged_message_id: int
    acknowledged_event_id: int
    message_ids: tuple[int, ...]
    event_ids: tuple[int, ...]

    @property
    def id(self) -> str:
        return self.card.id

    @property
    def title(self) -> str:
        return self.card.title

    @property
    def status(self) -> str:
        return self.card.status

    @property
    def existing(self) -> bool:
        return self.card.existing


def _capture_safe_text(value: str) -> str:
    return value.encode("utf-8", "backslashreplace").decode("utf-8")


def _capture_metadata_text(value: str) -> str:
    quoted = json.dumps(value, ensure_ascii=False)[1:-1]
    return _capture_safe_text(quoted)


def plan_capture(
    message: MessageChange, *, profile: str, extractor_version: str
) -> CaptureProjection:
    if profile != "default":
        raise CaptureError("source profile must be 'default'")
    if type(message.id) is not int or message.id < 0:
        raise CaptureError("invalid source message id")
    if type(message.session_id) is not str or not message.session_id:
        raise CaptureError("invalid source session id")
    if type(message.content) is not str:
        raise CaptureError("invalid source content")
    if type(message.compacted) is not bool:
        raise CaptureError("invalid source compacted flag")
    if type(message.timestamp) not in (int, float) or not math.isfinite(message.timestamp):
        raise CaptureError("invalid source timestamp")
    if type(extractor_version) is not str or not extractor_version:
        raise CaptureError("invalid extractor version")
    canonical = json.dumps(
        [profile, message.session_id, message.id, extractor_version],
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")
    digest = hashlib.sha256(canonical).hexdigest()
    key = "supervisor-capture:v1:" + digest
    session = _capture_metadata_text(message.session_id)
    content = _capture_safe_text(message.content)
    title_session = json.dumps(message.session_id, ensure_ascii=True)[1:-1]
    session_fragment = (
        title_session if len(title_session) <= 80
        else title_session[:64] + "~" + digest[:12]
    )
    title = f"Capture default/{session_fragment}/{message.id}"[:160]
    lowered = content.casefold()
    relation: str | None = None
    if any(marker in lowered for marker in (
        "修正:", "修正：", "訂正:", "訂正：", "correction:", "correct:",
    )):
        relation = "correction_candidate"
    elif any(marker in lowered for marker in (
        "撤回:", "撤回：", "取り消し:", "retract:", "withdraw:",
    )):
        relation = "retraction_candidate"
    metadata = (
        f"Source profile: default\nSource session: {session}\n"
        f"Source message: {message.id}\nSource timestamp: {message.timestamp!r}\n"
        f"Extractor version: {_capture_metadata_text(extractor_version)}\n"
    )
    if relation is not None:
        metadata += f"Relation candidate: {relation}; target unresolved\n"
    if len(content) > 512:
        body = metadata + "Content (verbatim, truncated):\n" + content[:512]
    else:
        body = metadata + "Content (verbatim):\n" + content
    if len(body) > 2048:
        raise CaptureError("capture metadata exceeds body limit")
    return CaptureProjection(
        profile, message.session_id, message.id, float(message.timestamp), extractor_version,
        key, title, body, relation,
    )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError("invalid kanban JSON: duplicate key")
        result[key] = value
    return result


def _json_depth(value: Any, limit: int = 32) -> None:
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            raise CaptureError("invalid kanban JSON: nesting too deep")
        if type(current) is dict:
            for key in current:
                if type(key) is not str:
                    raise CaptureError("invalid kanban JSON object key")
                try:
                    key.encode("utf-8", errors="strict")
                except UnicodeEncodeError as error:
                    raise CaptureError("invalid kanban JSON Unicode") from error
            stack.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in current)
        elif type(current) is str:
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as error:
                raise CaptureError("invalid kanban JSON Unicode") from error


_KANBAN_TASK_STATUSES = {
    "triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done",
    "archived",
}
_BATCH_BODY_KEYS = {
    "batch_key", "contract", "emergency", "event_ids", "events", "gate_policy",
    "instruction", "message_ids", "mode", "schema", "source_cursors",
}
_BATCH_EVENT_KEYS = {
    "actor_profile", "classification", "id", "kind", "run_id", "task_id",
}
_BATCH_INSTRUCTION = (
    "Supervisor forms and reviews an analysis plan only; does not implement; "
    "obey the gate; never apply to real or live state; do not provide hidden reasoning."
)


def _batch_unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BatchError("invalid Supervisor batch JSON")
        result[key] = value
    return result


def _batch_text(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not value:
        raise BatchError("invalid Supervisor batch text")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise BatchError("invalid Supervisor batch text") from error


def _batch_ids(value: Any, label: str) -> tuple[int, ...]:
    if type(value) is not list:
        raise BatchError(f"{label}: invalid")
    result = tuple(value)
    if any(type(item) is not int or item <= 0 for item in result):
        raise BatchError(f"{label}: invalid")
    if result != tuple(sorted(set(result))):
        raise BatchError(f"{label}: invalid")
    return result


def _batch_title(message_start: int, message_end: int, event_start: int, event_end: int) -> str:
    return f"Supervisor batch m{message_start + 1}-{message_end} e{event_start + 1}-{event_end}"


def _load_batch_body(body: Any) -> dict[str, Any]:
    if type(body) is not str:
        raise BatchError("invalid Supervisor batch body")
    try:
        encoded = body.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise BatchError("invalid Supervisor batch body") from error
    if len(encoded) > 65_536:
        raise BatchError("invalid Supervisor batch body")
    try:
        value = json.loads(
            body,
            object_pairs_hook=_batch_unique_json_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                BatchError("invalid Supervisor batch JSON")
            ),
        )
        _json_depth(value)
    except BatchError:
        raise
    except CaptureError as error:
        raise BatchError("invalid Supervisor batch JSON") from error
    except (json.JSONDecodeError, UnicodeError, RecursionError, TypeError, ValueError) as error:
        raise BatchError("invalid Supervisor batch JSON") from error
    if type(value) is not dict:
        raise BatchError("invalid Supervisor batch body")
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if canonical != body:
        raise BatchError("noncanonical Supervisor batch body")
    return value


def _validate_batch_projection(projection: Any) -> dict[str, Any]:
    if type(projection) is not SupervisorBatchProjection:
        raise BatchError("invalid Supervisor batch projection")
    for value in (projection.title, projection.idempotency_key, projection.mode):
        _batch_text(value)
    for flag in (projection.emergency, projection.safety_critical, projection.data_loss_risk):
        if type(flag) is not bool:
            raise BatchError("invalid Supervisor batch projection")
    starts_ends = (
        projection.start_message_id, projection.start_event_id,
        projection.proposed_message_id, projection.proposed_event_id,
    )
    if any(type(value) is not int or value < 0 for value in starts_ends):
        raise BatchError("invalid Supervisor batch cursors")
    if (projection.proposed_message_id < projection.start_message_id
            or projection.proposed_event_id < projection.start_event_id):
        raise BatchError("invalid Supervisor batch cursors")
    if type(projection.message_ids) is not tuple or type(projection.event_ids) is not tuple:
        raise BatchError("invalid Supervisor batch ids")
    message_ids = _batch_ids(list(projection.message_ids), "message ids")
    event_ids = _batch_ids(list(projection.event_ids), "event ids")
    if not message_ids and not event_ids:
        raise BatchError("Supervisor batch has no relevant ids")
    if any(item <= projection.start_message_id or item > projection.proposed_message_id
           for item in message_ids):
        raise BatchError("message ids outside Supervisor batch")
    if any(item <= projection.start_event_id or item > projection.proposed_event_id
           for item in event_ids):
        raise BatchError("event ids outside Supervisor batch")
    body = _load_batch_body(projection.body)
    if set(body) != _BATCH_BODY_KEYS:
        raise BatchError("invalid Supervisor batch schema")
    if (body["schema"] != "supervisor-batch/v1"
            or body["batch_key"] != projection.idempotency_key
            or body["mode"] != projection.mode
            or type(body["emergency"]) is not bool
            or body["emergency"] != projection.emergency
            or body["instruction"] != _BATCH_INSTRUCTION):
        raise BatchError("invalid Supervisor batch contract")
    if projection.mode == "shadow":
        contract = {"allowed_temperatures": [], "allowed_workspaces": [],
                    "child_dispatch": False, "real_apply": False}
    elif projection.mode in ("limited", "eco"):
        contract = {"allowed_temperatures": ["research", "build"],
                    "allowed_workspaces": ["scratch", "project_bound_worktree"],
                    "child_dispatch": True, "real_apply": False}
    else:
        raise BatchError("invalid Supervisor batch mode")
    if body["contract"] != contract:
        raise BatchError("invalid Supervisor batch contract")
    gate_policy = body["gate_policy"]
    if (type(gate_policy) is not dict
            or set(gate_policy) != {"daily_supervisor_limit", "data_loss_precedence",
                                    "observe_executes", "forbidden_workspaces"}
            or type(gate_policy["daily_supervisor_limit"]) is not int
            or gate_policy["daily_supervisor_limit"] <= 0
            or gate_policy["data_loss_precedence"] is not True
            or gate_policy["observe_executes"] is not False
            or gate_policy["forbidden_workspaces"] != ["main", "dir", "live"]):
        raise BatchError("invalid Supervisor batch gate policy")
    cursors = body["source_cursors"]
    if type(cursors) is not dict or set(cursors) != {"message", "event"}:
        raise BatchError("invalid Supervisor batch cursors")
    for stream, start, end in (
        ("message", projection.start_message_id, projection.proposed_message_id),
        ("event", projection.start_event_id, projection.proposed_event_id),
    ):
        cursor = cursors[stream]
        if (type(cursor) is not dict or set(cursor) != {"start", "end"}
                or type(cursor["start"]) is not int or type(cursor["end"]) is not int
                or cursor != {"start": start, "end": end}):
            raise BatchError("invalid Supervisor batch cursors")
    if _batch_ids(body["message_ids"], "message ids") != message_ids:
        raise BatchError("invalid Supervisor batch message ids")
    if _batch_ids(body["event_ids"], "event ids") != event_ids:
        raise BatchError("invalid Supervisor batch event ids")
    events = body["events"]
    if type(events) is not list or len(events) != len(event_ids):
        raise BatchError("invalid Supervisor batch events")
    event_summary_ids: list[int] = []
    for event in events:
        if type(event) is not dict or set(event) != _BATCH_EVENT_KEYS:
            raise BatchError("invalid Supervisor batch event")
        identifier = event["id"]
        if type(identifier) is not int or identifier <= 0:
            raise BatchError("invalid Supervisor batch event")
        for field in ("task_id", "kind", "classification"):
            _batch_text(event[field])
        _batch_text(event["actor_profile"], nullable=True)
        if event["run_id"] is not None and (
            type(event["run_id"]) is not int or event["run_id"] < 0
        ):
            raise BatchError("invalid Supervisor batch event")
        event_summary_ids.append(identifier)
    if tuple(event_summary_ids) != event_ids:
        raise BatchError("invalid Supervisor batch events")
    expected_title = _batch_title(
        projection.start_message_id, projection.proposed_message_id,
        projection.start_event_id, projection.proposed_event_id,
    )
    if projection.title != expected_title or len(projection.title) > 160:
        raise BatchError("invalid Supervisor batch title")
    return body


def _validate_batch_ack(ack: Any, projection: SupervisorBatchProjection) -> SupervisorBatchAck:
    body = _validate_batch_projection(projection)
    if type(ack) is not SupervisorBatchAck or type(ack.card) is not CreatedCardRef:
        raise BatchError("batch client returned invalid acknowledgement")
    card = ack.card
    for value in (card.id, card.title, card.status):
        _batch_text(value)
    if type(card.existing) is not bool or card.status not in _KANBAN_TASK_STATUSES - {"archived"}:
        raise BatchError("invalid Supervisor batch card")
    message_end = ack.acknowledged_message_id
    event_end = ack.acknowledged_event_id
    if (type(message_end) is not int or type(event_end) is not int
            or message_end < projection.start_message_id
            or event_end < projection.start_event_id
            or message_end > projection.proposed_message_id
            or event_end > projection.proposed_event_id
            or (not card.existing and (
                message_end != projection.proposed_message_id
                or event_end != projection.proposed_event_id
            ))):
        raise BatchError("invalid Supervisor batch acknowledgement cursors")
    expected_message_ids = tuple(item for item in projection.message_ids if item <= message_end)
    expected_event_ids = tuple(item for item in projection.event_ids if item <= event_end)
    if (type(ack.message_ids) is not tuple or type(ack.event_ids) is not tuple
            or ack.message_ids != expected_message_ids or ack.event_ids != expected_event_ids
            or (not ack.message_ids and not ack.event_ids)):
        raise BatchError("invalid Supervisor batch acknowledgement ids")
    if card.title != _batch_title(
        projection.start_message_id, message_end, projection.start_event_id, event_end
    ):
        raise BatchError("invalid Supervisor batch acknowledgement title")
    # Force validation of event summaries before any acknowledgement is trusted.
    if [event for event in body["events"] if event["id"] <= event_end] != [
        event for event in body["events"] if event["id"] in ack.event_ids
    ]:
        raise BatchError("invalid Supervisor batch acknowledgement events")
    return ack


def _batch_ack_from_response(
    value: dict[str, Any], projection: SupervisorBatchProjection
) -> SupervisorBatchAck:
    current = _validate_batch_projection(projection)
    if value["assignee"] != "supervisor":
        raise BatchError("Supervisor batch assignee mismatch")
    card = CreatedCardRef(
        value["id"], value["title"], value["status"], value.get("existing", False)
    )
    if not card.existing:
        if value["title"] != projection.title or value["body"] != projection.body:
            raise BatchError("new Supervisor batch response mismatch")
        return _validate_batch_ack(
            SupervisorBatchAck(
                card, projection.proposed_message_id, projection.proposed_event_id,
                projection.message_ids, projection.event_ids,
            ),
            projection,
        )

    returned = _load_batch_body(value["body"])
    if set(returned) != _BATCH_BODY_KEYS:
        raise BatchError("invalid existing Supervisor batch schema")
    cursors = returned.get("source_cursors")
    if type(cursors) is not dict or set(cursors) != {"message", "event"}:
        raise BatchError("invalid existing Supervisor batch cursors")
    checked: dict[str, int] = {}
    for stream, start, current_end in (
        ("message", projection.start_message_id, projection.proposed_message_id),
        ("event", projection.start_event_id, projection.proposed_event_id),
    ):
        cursor = cursors[stream]
        if type(cursor) is not dict or set(cursor) != {"start", "end"}:
            raise BatchError("invalid existing Supervisor batch cursors")
        returned_start, returned_end = cursor["start"], cursor["end"]
        if (type(returned_start) is not int or type(returned_end) is not int
                or returned_start != start or returned_end < start or returned_end > current_end):
            raise BatchError("invalid existing Supervisor batch cursors")
        checked[stream] = returned_end
    message_end, event_end = checked["message"], checked["event"]
    expected = json.loads(projection.body)
    expected["source_cursors"]["message"]["end"] = message_end
    expected["source_cursors"]["event"]["end"] = event_end
    expected["message_ids"] = [
        item for item in current["message_ids"] if item <= message_end
    ]
    expected["event_ids"] = [item for item in current["event_ids"] if item <= event_end]
    expected["events"] = [item for item in current["events"] if item["id"] <= event_end]
    if not expected["message_ids"] and not expected["event_ids"]:
        raise BatchError("existing Supervisor batch acknowledges no relevant ids")
    expected_body = json.dumps(
        expected, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if value["body"] != expected_body:
        raise BatchError("existing Supervisor batch is not an exact prefix")
    expected_title = _batch_title(
        projection.start_message_id, message_end, projection.start_event_id, event_end
    )
    if value["title"] != expected_title:
        raise BatchError("existing Supervisor batch title mismatch")
    return _validate_batch_ack(
        SupervisorBatchAck(
            card, message_end, event_end,
            tuple(expected["message_ids"]), tuple(expected["event_ids"]),
        ),
        projection,
    )


class HermesKanbanClient:
    def __init__(
        self,
        executable: str,
        board: str,
        *,
        runner: Callable[..., Any] | None = None,
        timeout: float = 30.0,
        output_limit: int = 65536,
        base_env: Mapping[str, str] | None = None,
    ):
        if type(executable) is not str or not executable or "\x00" in executable:
            raise CaptureError("invalid Hermes executable")
        try:
            executable.encode("utf-8")
        except UnicodeEncodeError as error:
            raise CaptureError("invalid Hermes executable") from error
        if (
            type(board) is not str
            or len(board) > 64
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", board) is None
        ):
            raise CaptureError("invalid Kanban board")
        try:
            board.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise CaptureError("invalid Kanban board") from error
        try:
            environment = dict(os.environ if base_env is None else base_env)
        except (TypeError, ValueError) as error:
            raise CaptureError("invalid subprocess environment") from error
        if any(type(key) is not str or type(value) is not str
               for key, value in environment.items()):
            raise CaptureError("invalid subprocess environment")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise CaptureError("invalid subprocess timeout")
        if type(output_limit) is not int or output_limit <= 0:
            raise CaptureError("invalid subprocess output limit")
        self.executable = executable
        self.board = board
        self.runner = runner
        self.timeout = timeout
        self.output_limit = output_limit
        self.base_env = environment

    def _production_run(self, argv: list[str], environment: dict[str, str]) -> Any:
        try:
            return _bounded_subprocess_run(
                argv, environment=environment, timeout=self.timeout,
                output_limit=self.output_limit,
            )
        except _BoundedOutputError as error:
            raise CaptureError("Hermes create output exceeds limit") from error
        except UnicodeError as error:
            raise CaptureError("invalid Hermes create output") from error

    def create(self, projection: CaptureProjection) -> CreatedCardRef:
        if type(projection) is not CaptureProjection:
            raise CaptureError("invalid capture projection")
        argv = [
            self.executable, "kanban", "create", projection.title,
            "--body", projection.body, "--triage", "--idempotency-key",
            projection.idempotency_key, "--created-by", "supervisor-capture", "--json",
        ]
        result = self._create_argv(argv, expected_batch=None)
        if type(result) is not CreatedCardRef:
            raise CaptureError("Hermes create returned invalid card")
        return result

    def create_supervisor_batch(
        self, projection: SupervisorBatchProjection
    ) -> SupervisorBatchAck:
        _validate_batch_projection(projection)
        argv = [
            self.executable, "kanban", "create", projection.title,
            "--body", projection.body, "--assignee", "supervisor",
            "--workspace", "scratch", "--idempotency-key", projection.idempotency_key,
            "--max-runtime", "30m", "--created-by", "supervisor-watcher",
            "--skill", "kanban-orchestrator", "--skill", "personal-project-management",
            "--max-retries", "2", "--json",
        ]
        try:
            result = self._create_argv(argv, expected_batch=projection)
        except BatchError:
            raise
        except CaptureError as error:
            raise BatchError("Supervisor batch create failed") from error
        if type(result) is not SupervisorBatchAck:
            raise BatchError("Supervisor batch create returned invalid acknowledgement")
        return result

    def _create_argv(
        self, argv: list[str], *, expected_batch: SupervisorBatchProjection | None
    ) -> CreatedCardRef | SupervisorBatchAck:
        try:
            for argument in argv:
                if "\x00" in argument:
                    raise CaptureError("invalid capture argument")
                argument.encode("utf-8")
            environment = dict(self.base_env, HERMES_KANBAN_BOARD=self.board)
            if self.runner is None:
                completed = self._production_run(argv, environment)
            else:
                completed = self.runner(
                    argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    encoding="utf-8", errors="strict", timeout=self.timeout, check=False,
                    shell=False, env=environment,
                )
        except CaptureError:
            raise
        except Exception as error:
            raise CaptureError(f"Hermes create failed ({type(error).__name__})") from error
        if type(getattr(completed, "returncode", None)) is not int:
            raise CaptureError("Hermes create returned invalid result")
        stdout = getattr(completed, "stdout", None)
        stderr = getattr(completed, "stderr", None)
        try:
            if type(stdout) is not str or type(stderr) is not str:
                raise CaptureError("invalid Hermes create output")
            if (
                len(stdout.encode("utf-8", "strict")) > self.output_limit
                or len(stderr.encode("utf-8", "strict")) > self.output_limit
            ):
                raise CaptureError("Hermes create output exceeds limit")
        except UnicodeEncodeError as error:
            raise CaptureError("invalid Hermes create output") from error
        if completed.returncode != 0:
            raise CaptureError(f"Hermes create exited with status {completed.returncode}")
        try:
            value = json.loads(
                stdout,
                object_pairs_hook=_unique_json_object,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    CaptureError(f"invalid kanban JSON constant {token}")
                ),
            )
            _json_depth(value)
        except CaptureError:
            raise
        except (json.JSONDecodeError, UnicodeError, RecursionError, TypeError, ValueError) as error:
            raise CaptureError("invalid kanban JSON output") from error
        if type(value) is not dict:
            raise CaptureError("invalid kanban JSON object")
        for field in ("id", "title", "status"):
            if type(value.get(field)) is not str or not value[field]:
                raise CaptureError(f"invalid kanban task {field}")
        if "body" not in value or "assignee" not in value:
            raise CaptureError("invalid kanban task fields")
        if value["body"] is not None and type(value["body"]) is not str:
            raise CaptureError("invalid kanban task body")
        if value["assignee"] is not None and type(value["assignee"]) is not str:
            raise CaptureError("invalid kanban task assignee")
        if value["status"] not in _KANBAN_TASK_STATUSES:
            raise CaptureError("invalid kanban task status")
        if value["status"] == "archived":
            raise CaptureError("archived kanban task rejected")
        existing = value.get("existing", False)
        if type(existing) is not bool:
            raise CaptureError("invalid kanban task existing flag")
        card = CreatedCardRef(value["id"], value["title"], value["status"], existing)
        if expected_batch is not None:
            return _batch_ack_from_response(value, expected_batch)
        return card


@dataclass(frozen=True)
class EventChange:
    id: int
    task_id: str
    run_id: int | None
    kind: str
    classification: str
    actor_profile: str | None
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class ChangeSet:
    messages: tuple[MessageChange, ...]
    events: tuple[EventChange, ...]
    proposed_message_id: int
    proposed_event_id: int


def transition_control(
    state: SupervisorState, action: str, *, now: int | None = None
) -> SupervisorState:
    if state.control_state not in ("running", "paused", "frozen", "emergency_stopped"):
        raise StateError("invalid current control state")
    targets = {"pause": "paused", "freeze": "frozen", "resume": "running"}
    if action == "emergency-stop":
        if now is None:
            raise StateError("emergency-stop requires a timestamp")
        return replace(
            state,
            control_state="emergency_stopped",
            emergency_stop_requested_at=_state_int(now, "emergency stop timestamp"),
        )
    if action not in targets:
        raise StateError(f"invalid control action: {action}")
    # Resume intentionally preserves the emergency timestamp as audit history.
    return replace(state, control_state=targets[action])


def dispatch_allowed(state: SupervisorState) -> bool:
    return state.control_state == "running"


def card_formation_allowed(state: SupervisorState) -> bool:
    return state.control_state in ("running", "paused")


def _record_observed_ids(
    existing: tuple[int, ...],
    observed: Any,
    *,
    current_cursor: int,
    proposed_cursor: int,
    label: str,
) -> tuple[int, ...]:
    result = list(existing)
    seen = set(existing)
    for value in observed:
        identifier = _state_int(value, f"observed {label} id")
        if identifier > proposed_cursor:
            raise StateError(f"observed {label} id beyond proposed cursor")
        if identifier <= current_cursor:
            if identifier not in seen:
                raise StateError(f"observed {label} id is stale and unknown")
            continue
        if identifier not in seen:
            result.append(identifier)
            seen.add(identifier)
    return tuple(result)


def record_frozen_observation(state: SupervisorState, changes: ChangeSet) -> SupervisorState:
    if state.control_state != "frozen":
        raise StateError("frozen observation requires frozen control state")
    current_message_id, pending_message_ids = _validate_pending_cursor(
        state.last_message_id,
        state.pending_message_ids,
        cursor_label="last_message_id",
        pending_label="pending_message_ids",
    )
    current_event_id, pending_event_ids = _validate_pending_cursor(
        state.last_event_id,
        state.pending_event_ids,
        cursor_label="last_event_id",
        pending_label="pending_event_ids",
    )
    message_mark = _state_int(changes.proposed_message_id, "proposed_message_id")
    event_mark = _state_int(changes.proposed_event_id, "proposed_event_id")
    if message_mark < current_message_id or event_mark < current_event_id:
        raise StateError("observation cursor cannot move backwards")
    return replace(
        state,
        last_message_id=message_mark,
        last_event_id=event_mark,
        pending_message_ids=_record_observed_ids(
            pending_message_ids,
            (message.id for message in changes.messages),
            current_cursor=current_message_id,
            proposed_cursor=message_mark,
            label="message",
        ),
        pending_event_ids=_record_observed_ids(
            pending_event_ids,
            (event.id for event in changes.events),
            current_cursor=current_event_id,
            proposed_cursor=event_mark,
            label="event",
        ),
    )



def _open_readonly(path: Path) -> sqlite3.Connection:
    # Path.as_uri() percent-encodes reserved characters before mode=ro is added.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


_REQUIRED_STATE_SCHEMA = {
    "messages": {"id", "session_id", "role", "content", "timestamp", "active", "compacted"},
    "sessions": {"id", "archived"},
}
_REQUIRED_KANBAN_SCHEMA = {
    "task_events": {"id", "task_id", "run_id", "kind", "payload", "created_at"},
    "task_runs": {"id", "task_id", "profile"},
}
_RELEVANT_EVENT_KINDS = (
    "completed",
    "blocked",
    "gave_up",
    "dependency_wait",
    "block_loop_detected",
    "completion_blocked_hallucination",
)
_EVENT_CLASSIFICATIONS = {
    "completed": "completed",
    "blocked": "blocked",
    "gave_up": "blocked",
    "dependency_wait": "waiting",
    "block_loop_detected": "blocked",
    "completion_blocked_hallucination": "rejected",
}

# Batch polling fails closed rather than truncating: advancing past an overflow could
# permanently skip a safety-critical event later in the same backlog.
_BATCH_MAX_MESSAGES = 4096
_BATCH_MAX_EVENTS = 1024
_BATCH_MESSAGE_QUERY_LIMIT = _BATCH_MAX_MESSAGES + 1
_BATCH_EVENT_QUERY_LIMIT = _BATCH_MAX_EVENTS + 1
_BATCH_TASK_ID_MAX_BYTES = 4096
_BATCH_ACTOR_MAX_BYTES = 256
_BATCH_TOTAL_EVENT_BYTES = 256 * 1024
_BATCH_REDACTED_SESSION_ID = "batch-redacted"

# Capture cycles are intentionally conservative: no more than 64 cards, 256
# event markers, or 512 KiB of message strings are exposed per cycle.  The
# pending cap fits 2048 worst-case signed SQLite IDs below strict 64 KiB state.
_CAPTURE_MAX_MESSAGES = 64
_CAPTURE_MAX_EVENTS = 256
_CAPTURE_SESSION_MAX_BYTES = 4096
_CAPTURE_CONTENT_MAX_BYTES = 64 * 1024
_CAPTURE_TOTAL_MESSAGE_BYTES = 512 * 1024
_CAPTURE_PENDING_ID_CAP = 2048
_CAPTURE_REDACTED_SESSION_ID = "capture-redacted"


def _validate_schema(
    connection: sqlite3.Connection,
    label: str,
    required: dict[str, set[str]],
) -> None:
    for table, columns in required.items():
        actual = {
            str(row["name"])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        missing = columns - actual
        if missing:
            detail = sorted(missing)[0]
            raise DetectionError(f"{label}: incompatible {table} schema (missing {detail})")


def _validate_cursor(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DetectionError(f"{name} must be an integer >= 0")


def _validate_id(value: Any, label: str, name: str) -> int:
    if type(value) is not int or value < 0:
        raise DetectionError(f"{label}: invalid {name}")
    return value


def _validate_optional_id(value: Any, label: str, name: str) -> int | None:
    if value is None:
        return None
    return _validate_id(value, label, name)


def _validate_string(
    value: Any,
    label: str,
    name: str,
    *,
    empty_allowed: bool = False,
) -> str:
    if type(value) is not str or (not empty_allowed and not value):
        raise DetectionError(f"{label}: invalid {name}")
    return value


def _validate_optional_string(value: Any, label: str, name: str) -> str | None:
    if value is None:
        return None
    return _validate_string(value, label, name)


def _validate_timestamp(value: Any) -> float:
    if type(value) not in (int, float):
        raise DetectionError("state.db: invalid message timestamp")
    result = float(value)
    if not math.isfinite(result):
        raise DetectionError("state.db: invalid message timestamp")
    return result


def _validate_compacted(value: Any) -> bool:
    if type(value) is not int or value not in (0, 1):
        raise DetectionError("state.db: invalid message compacted flag")
    return bool(value)


def _validate_event_kind(value: Any, event_id: int) -> str:
    if type(value) is not str or value not in _EVENT_CLASSIFICATIONS:
        raise DetectionError(f"kanban.db: invalid kind for event {event_id}")
    return value


def _decode_payload(raw: Any, event_id: int) -> dict[str, Any] | None:
    if raw is None:
        return None
    message = f"kanban.db: invalid payload for event {event_id}"
    if type(raw) is not str:
        raise DetectionError(message)
    payload = _strict_json_loads(
        raw,
        max_bytes=_PAYLOAD_JSON_MAX_BYTES,
        error_type=DetectionError,
        message=message,
    )
    if type(payload) is not dict:
        raise DetectionError(message)
    return payload


def _event_actor(row: sqlite3.Row, event_id: int) -> str | None:
    run_profile = _validate_optional_string(
        row["run_profile"], "kanban.db", f"run profile for event {event_id}"
    )
    if run_profile is not None:
        return run_profile
    assignment_raw = row["assignment_payload"]
    assignment_event_id = _validate_optional_id(
        row["assignment_event_id"], "kanban.db", f"assignment event id for event {event_id}"
    )
    if assignment_raw is None:
        return None
    if assignment_event_id is None:
        raise DetectionError(f"kanban.db: invalid assignment event id for event {event_id}")
    assignment = _decode_payload(assignment_raw, assignment_event_id)
    assert assignment is not None
    return _validate_optional_string(
        assignment.get("assignee"), "kanban.db", f"assignee for event {event_id}"
    )


def _message_change(row: sqlite3.Row) -> MessageChange:
    message_id = _validate_id(row["id"], "state.db", "message id")
    if type(row["active"]) is not int or row["active"] != 1:
        raise DetectionError(f"state.db: invalid active flag for message {message_id}")
    if type(row["archived"]) is not int or row["archived"] != 0:
        raise DetectionError(f"state.db: invalid archived flag for message {message_id}")
    return MessageChange(
        id=message_id,
        session_id=_validate_string(row["session_id"], "state.db", "session id"),
        content=_validate_string(
            row["content"], "state.db", "message content", empty_allowed=True
        ),
        timestamp=_validate_timestamp(row["timestamp"]),
        compacted=_validate_compacted(row["compacted"]),
    )


def read_pending_messages(path: Path, pending_ids: tuple[int, ...]) -> tuple[MessageChange, ...]:
    """Fetch exact frozen-backlog user messages under one read-only snapshot."""
    checked = tuple(_validate_id(value, "state.db", "pending message id") for value in pending_ids)
    if len(checked) != len(set(checked)):
        raise DetectionError("state.db: duplicate pending message id")
    if not checked:
        return ()
    try:
        with contextlib.closing(_open_readonly(path)) as connection:
            connection.execute("BEGIN")
            try:
                _validate_schema(connection, "state.db", _REQUIRED_STATE_SCHEMA)
                result: list[MessageChange] = []
                for identifier in sorted(checked):
                    row = connection.execute(
                        """
                        SELECT m.id, m.session_id, m.role, m.content, m.timestamp, m.compacted
                          FROM messages AS m JOIN sessions AS s ON s.id = m.session_id
                         WHERE m.id = ?
                        """,
                        (identifier,),
                    ).fetchone()
                    if row is None:
                        raise DetectionError(
                            f"state.db: pending message {identifier} is unavailable"
                        )
                    if type(row["role"]) is not str or row["role"] != "user":
                        raise DetectionError(
                            f"state.db: pending message {identifier} is not a user message"
                        )
                    result.append(MessageChange(
                        id=_validate_id(row["id"], "state.db", "message id"),
                        session_id=_validate_string(row["session_id"], "state.db", "session id"),
                        content=_validate_string(
                            row["content"], "state.db", "message content", empty_allowed=True
                        ),
                        timestamp=_validate_timestamp(row["timestamp"]),
                        compacted=_validate_compacted(row["compacted"]),
                    ))
                return tuple(result)
            finally:
                if connection.in_transaction:
                    connection.rollback()
    except DetectionError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError) as error:
        raise DetectionError(f"pending backlog read failed: {error}") from error


def _event_change(row: sqlite3.Row) -> EventChange:
    event_id = _validate_id(row["id"], "kanban.db", "event id")
    kind = _validate_event_kind(row["kind"], event_id)
    return EventChange(
        id=event_id,
        task_id=_validate_string(row["task_id"], "kanban.db", f"task id for event {event_id}"),
        run_id=_validate_optional_id(
            row["run_id"], "kanban.db", f"run id for event {event_id}"
        ),
        kind=kind,
        classification=_EVENT_CLASSIFICATIONS[kind],
        actor_profile=_event_actor(row, event_id),
        payload=_decode_payload(row["payload"], event_id),
    )


def _read_messages(path: Path, cursor: int) -> tuple[tuple[MessageChange, ...], int]:
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "state.db", _REQUIRED_STATE_SCHEMA)
            maximum = _validate_id(
                connection.execute(
                    "SELECT COALESCE(MAX(id), ?) FROM messages WHERE id > ?",
                    (cursor, cursor),
                ).fetchone()[0],
                "state.db",
                "message high-water id",
            )
            bad_role = connection.execute(
                """
                SELECT id FROM messages
                 WHERE id > ? AND id <= ? AND typeof(role) != 'text'
                 ORDER BY id ASC LIMIT 1
                """,
                (cursor, maximum),
            ).fetchone()
            if bad_role is not None:
                message_id = _validate_id(bad_role[0], "state.db", "message id")
                raise DetectionError(f"state.db: invalid role for message {message_id}")
            rows = connection.execute(
                """
                SELECT m.id, m.session_id, m.content, m.timestamp, m.compacted,
                       m.active, s.archived
                  FROM messages AS m
                  JOIN sessions AS s ON s.id = m.session_id
                 WHERE m.id > ? AND m.id <= ?
                   AND m.role = 'user' AND m.active = 1
                   AND s.archived = 0
                 ORDER BY m.id ASC
                """,
                (cursor, maximum),
            ).fetchall()
            return (tuple(_message_change(row) for row in rows), maximum)
        finally:
            if connection.in_transaction:
                connection.rollback()


def _read_events(path: Path, cursor: int) -> tuple[tuple[EventChange, ...], int]:
    placeholders = ", ".join("?" for _ in _RELEVANT_EVENT_KINDS)
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "kanban.db", _REQUIRED_KANBAN_SCHEMA)
            maximum = _validate_id(
                connection.execute(
                    "SELECT COALESCE(MAX(id), ?) FROM task_events WHERE id > ?",
                    (cursor, cursor),
                ).fetchone()[0],
                "kanban.db",
                "event high-water id",
            )
            bad_kind = connection.execute(
                """
                SELECT id FROM task_events
                 WHERE id > ? AND id <= ? AND typeof(kind) != 'text'
                 ORDER BY id ASC LIMIT 1
                """,
                (cursor, maximum),
            ).fetchone()
            if bad_kind is not None:
                event_id = _validate_id(bad_kind[0], "kanban.db", "event id")
                raise DetectionError(f"kanban.db: invalid kind for event {event_id}")
            rows = connection.execute(
                f"""
                SELECT e.id, e.task_id, e.run_id, e.kind, e.payload,
                       (SELECT r.profile FROM task_runs AS r
                         WHERE r.id = e.run_id AND r.task_id = e.task_id) AS run_profile,
                       (SELECT a.id FROM task_events AS a
                         WHERE a.task_id = e.task_id AND a.id <= e.id
                           AND a.kind IN ('created', 'assigned')
                         ORDER BY a.id DESC LIMIT 1) AS assignment_event_id,
                       (SELECT a.payload FROM task_events AS a
                         WHERE a.task_id = e.task_id AND a.id <= e.id
                           AND a.kind IN ('created', 'assigned')
                         ORDER BY a.id DESC LIMIT 1) AS assignment_payload
                  FROM task_events AS e
                 WHERE e.id > ? AND e.id <= ? AND e.kind IN ({placeholders})
                 ORDER BY e.id ASC
                """,
                (cursor, maximum, *_RELEVANT_EVENT_KINDS),
            ).fetchall()
            return (tuple(_event_change(row) for row in rows), maximum)
        finally:
            if connection.in_transaction:
                connection.rollback()


def _read_batch_messages(path: Path, cursor: int) -> tuple[tuple[MessageChange, ...], int]:
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "state.db", _REQUIRED_STATE_SCHEMA)
            maximum = _validate_id(
                connection.execute(
                    "SELECT COALESCE(MAX(id), ?) FROM messages WHERE id > ?",
                    (cursor, cursor),
                ).fetchone()[0],
                "state.db", "message high-water id",
            )
            bad_role = connection.execute(
                """
                SELECT id FROM messages
                 WHERE id > ? AND id <= ? AND typeof(role) != 'text'
                 ORDER BY id ASC LIMIT 1
                """,
                (cursor, maximum),
            ).fetchone()
            if bad_role is not None:
                message_id = _validate_id(bad_role[0], "state.db", "message id")
                raise DetectionError(f"state.db: invalid role for message {message_id}")
            malformed = connection.execute(
                """
                SELECT m.id
                  FROM messages AS m
                  LEFT JOIN sessions AS s ON s.id = m.session_id
                 WHERE m.id > ? AND m.id <= ? AND m.role = 'user'
                   AND (
                       s.id IS NULL
                       OR typeof(m.active) != 'integer' OR m.active NOT IN (0, 1)
                       OR typeof(s.archived) != 'integer' OR s.archived NOT IN (0, 1)
                       OR (
                           m.active = 1 AND s.archived = 0
                           AND (
                               typeof(m.timestamp) NOT IN ('integer', 'real')
                               OR m.timestamp < -1.7976931348623157e308
                               OR m.timestamp > 1.7976931348623157e308
                               OR typeof(m.compacted) != 'integer'
                               OR m.compacted NOT IN (0, 1)
                           )
                       )
                   )
                 ORDER BY m.id ASC LIMIT 1
                """,
                (cursor, maximum),
            ).fetchone()
            if malformed is not None:
                message_id = _validate_id(malformed[0], "state.db", "message id")
                raise DetectionError(f"state.db: invalid metadata for message {message_id}")
            rows = connection.execute(
                """
                SELECT m.id, m.timestamp, m.compacted, m.active, s.archived
                  FROM messages AS m
                  JOIN sessions AS s ON s.id = m.session_id
                 WHERE m.id > ? AND m.id <= ?
                   AND m.role = 'user' AND m.active = 1 AND s.archived = 0
                 ORDER BY m.id ASC LIMIT ?
                """,
                (cursor, maximum, _BATCH_MESSAGE_QUERY_LIMIT),
            ).fetchall()
            if len(rows) > _BATCH_MAX_MESSAGES:
                raise DetectionError("state.db: supervisor batch message limit exceeded")
            changes: list[MessageChange] = []
            for row in rows:
                message_id = _validate_id(row["id"], "state.db", "message id")
                if type(row["active"]) is not int or row["active"] != 1:
                    raise DetectionError(f"state.db: invalid active flag for message {message_id}")
                if type(row["archived"]) is not int or row["archived"] != 0:
                    raise DetectionError(f"state.db: invalid archived flag for message {message_id}")
                changes.append(MessageChange(
                    id=message_id,
                    session_id=_BATCH_REDACTED_SESSION_ID,
                    content="",
                    timestamp=_validate_timestamp(row["timestamp"]),
                    compacted=_validate_compacted(row["compacted"]),
                ))
            return tuple(changes), maximum
        finally:
            if connection.in_transaction:
                connection.rollback()


def _batch_length(value: Any, label: str, *, maximum: int, optional: bool) -> int:
    if value is None and optional:
        return 0
    if type(value) is not int or value < 0 or value > maximum:
        raise DetectionError(f"kanban.db: invalid or oversized {label}")
    return value


def _batch_event_queries(placeholders: str) -> tuple[str, str]:
    assignment_id = """(SELECT a.id FROM task_events AS a
        WHERE a.task_id = e.task_id AND a.id <= e.id
          AND a.kind IN ('created', 'assigned')
        ORDER BY a.id DESC LIMIT 1)"""
    assignment_payload = """(SELECT a.payload FROM task_events AS a
        WHERE a.task_id = e.task_id AND a.id <= e.id
          AND a.kind IN ('created', 'assigned')
        ORDER BY a.id DESC LIMIT 1)"""
    run_profile = """(SELECT r.profile FROM task_runs AS r
        WHERE r.id = e.run_id AND r.task_id = e.task_id)"""
    preflight = f"""
        SELECT e.id, e.run_id,
               length(CAST(e.task_id AS BLOB)) AS task_id_bytes,
               length(CAST(e.payload AS BLOB)) AS payload_bytes,
               length(CAST({run_profile} AS BLOB)) AS run_profile_bytes,
               {assignment_id} AS assignment_event_id,
               length(CAST({assignment_payload} AS BLOB)) AS assignment_payload_bytes
          FROM task_events AS e
         WHERE e.id > ? AND e.id <= ? AND e.kind IN ({placeholders})
         ORDER BY e.id ASC LIMIT ?
    """
    fetch = f"""
        SELECT e.id, e.task_id, e.run_id, e.kind, e.payload,
               {run_profile} AS run_profile,
               {assignment_id} AS assignment_event_id,
               {assignment_payload} AS assignment_payload
          FROM task_events AS e
         WHERE e.id > ? AND e.id <= ? AND e.kind IN ({placeholders})
         ORDER BY e.id ASC LIMIT ?
    """
    return preflight, fetch


def _read_batch_events(path: Path, cursor: int) -> tuple[tuple[EventChange, ...], int]:
    placeholders = ", ".join("?" for _ in _RELEVANT_EVENT_KINDS)
    preflight_sql, fetch_sql = _batch_event_queries(placeholders)
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "kanban.db", _REQUIRED_KANBAN_SCHEMA)
            maximum = _validate_id(
                connection.execute(
                    "SELECT COALESCE(MAX(id), ?) FROM task_events WHERE id > ?",
                    (cursor, cursor),
                ).fetchone()[0],
                "kanban.db", "event high-water id",
            )
            bad_kind = connection.execute(
                """
                SELECT id FROM task_events
                 WHERE id > ? AND id <= ? AND typeof(kind) != 'text'
                 ORDER BY id ASC LIMIT 1
                """,
                (cursor, maximum),
            ).fetchone()
            if bad_kind is not None:
                event_id = _validate_id(bad_kind[0], "kanban.db", "event id")
                raise DetectionError(f"kanban.db: invalid kind for event {event_id}")
            query_parameters = (
                cursor, maximum, *_RELEVANT_EVENT_KINDS, _BATCH_EVENT_QUERY_LIMIT
            )
            metadata = connection.execute(preflight_sql, query_parameters).fetchall()
            if len(metadata) > _BATCH_MAX_EVENTS:
                raise DetectionError("kanban.db: supervisor batch event limit exceeded")
            total = 0
            metadata_ids: list[int] = []
            for row in metadata:
                event_id = _validate_id(row["id"], "kanban.db", "event id")
                metadata_ids.append(event_id)
                _validate_optional_id(row["run_id"], "kanban.db", f"run id for event {event_id}")
                assignment_id_value = _validate_optional_id(
                    row["assignment_event_id"], "kanban.db",
                    f"assignment event id for event {event_id}",
                )
                lengths = (
                    _batch_length(row["task_id_bytes"], "task id", maximum=_BATCH_TASK_ID_MAX_BYTES, optional=False),
                    _batch_length(row["payload_bytes"], "payload", maximum=_PAYLOAD_JSON_MAX_BYTES, optional=True),
                    _batch_length(row["run_profile_bytes"], "run profile", maximum=_BATCH_ACTOR_MAX_BYTES, optional=True),
                    _batch_length(row["assignment_payload_bytes"], "assignment payload", maximum=_PAYLOAD_JSON_MAX_BYTES, optional=True),
                )
                if row["assignment_payload_bytes"] is not None and assignment_id_value is None:
                    raise DetectionError(f"kanban.db: invalid assignment event id for event {event_id}")
                total += sum(lengths)
                if total > _BATCH_TOTAL_EVENT_BYTES:
                    raise DetectionError("kanban.db: supervisor batch metadata limit exceeded")
            rows = connection.execute(fetch_sql, query_parameters).fetchall()
            if len(rows) != len(metadata) or [row["id"] for row in rows] != metadata_ids:
                raise DetectionError("kanban.db: inconsistent supervisor batch snapshot")
            changes = tuple(_event_change(row) for row in rows)
            for change in changes:
                if change.actor_profile is not None:
                    _batch_length(
                        len(change.actor_profile.encode("utf-8", "strict")),
                        "actor profile", maximum=_BATCH_ACTOR_MAX_BYTES, optional=False,
                    )
            return changes, maximum
        finally:
            if connection.in_transaction:
                connection.rollback()


def detect_batch_changes(
    state_db: Path,
    kanban_db: Path,
    *,
    profile: str,
    last_message_id: int,
    last_event_id: int,
) -> ChangeSet:
    """Read a bounded metadata-only change set for Supervisor batching."""
    if profile != "default":
        raise DetectionError("profile must be 'default'")
    _validate_cursor("last_message_id", last_message_id)
    _validate_cursor("last_event_id", last_event_id)
    try:
        messages, proposed_message_id = _read_batch_messages(state_db, last_message_id)
        events, proposed_event_id = _read_batch_events(kanban_db, last_event_id)
    except DetectionError:
        raise
    except (OSError, sqlite3.Error, UnicodeError, TypeError, ValueError,
            OverflowError, RecursionError) as error:
        raise DetectionError(
            f"batch change detection failed ({type(error).__name__})"
        ) from error
    return ChangeSet(messages, events, proposed_message_id, proposed_event_id)


def _capture_length(value: Any, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise DetectionError(f"state.db: invalid or oversized {label}")
    return value


def _capture_limit(value: Any, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise DetectionError(f"invalid {label}")
    return value


def _capture_message_metadata_error(connection: sqlite3.Connection, cursor: int, maximum: int) -> None:
    bad = connection.execute(
        "SELECT id FROM messages WHERE id>? AND id<=? AND typeof(role)!='text' ORDER BY id LIMIT 1",
        (cursor, maximum),
    ).fetchone()
    if bad is not None:
        identifier = _validate_id(bad[0], "state.db", "message id")
        raise DetectionError(f"state.db: invalid role for message {identifier}")
    bad = connection.execute(
        """SELECT m.id FROM messages m LEFT JOIN sessions s ON s.id=m.session_id
           WHERE m.id>? AND m.id<=? AND m.role='user' AND
             (s.id IS NULL OR typeof(m.active)!='integer' OR m.active NOT IN (0,1)
              OR typeof(s.archived)!='integer' OR s.archived NOT IN (0,1)
              OR (m.active=1 AND s.archived=0 AND
                 (typeof(m.timestamp) NOT IN ('integer','real')
                  OR m.timestamp < -1.7976931348623157e308
                  OR m.timestamp > 1.7976931348623157e308
                  OR typeof(m.compacted)!='integer' OR m.compacted NOT IN (0,1))))
           ORDER BY m.id LIMIT 1""", (cursor, maximum),
    ).fetchone()
    if bad is not None:
        identifier = _validate_id(bad[0], "state.db", "message id")
        raise DetectionError(f"state.db: invalid metadata for message {identifier}")


def _capture_raw_messages(connection: sqlite3.Connection, metadata: list[sqlite3.Row]) -> tuple[MessageChange, ...]:
    if not metadata:
        return ()
    identifiers = [_validate_id(row["id"], "state.db", "message id") for row in metadata]
    placeholders = ",".join("?" for _ in identifiers)
    rows = connection.execute(
        f"""SELECT m.id,m.session_id,m.content,m.timestamp,m.compacted,m.active,s.archived
              FROM messages m JOIN sessions s ON s.id=m.session_id
             WHERE m.id IN ({placeholders}) ORDER BY m.id LIMIT ?""",
        (*identifiers, len(identifiers)),
    ).fetchall()
    if [row["id"] for row in rows] != identifiers:
        raise DetectionError("state.db: inconsistent capture message snapshot")
    changes = tuple(_message_change(row) for row in rows)
    for metadata_row, change in zip(metadata, changes, strict=True):
        if (len(change.session_id.encode("utf-8", "strict")) != metadata_row["session_bytes"]
                or len(change.content.encode("utf-8", "strict")) != metadata_row["content_bytes"]):
            raise DetectionError("state.db: inconsistent capture message lengths")
    return changes


def _read_capture_messages(path: Path, cursor: int, pending_ids: tuple[int, ...], *,
                           limit: int, frozen: bool) -> tuple[tuple[MessageChange, ...], int]:
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "state.db", _REQUIRED_STATE_SCHEMA)
            maximum = _validate_id(connection.execute(
                "SELECT COALESCE(MAX(id),?) FROM messages WHERE id>?", (cursor, cursor)
            ).fetchone()[0], "state.db", "message high-water id")
            if limit == 0:
                return (), cursor
            if frozen:
                # ID-only observation deliberately never authorises session/content reads.
                _capture_message_metadata_error(connection, cursor, maximum)
                rows = connection.execute(
                    """SELECT m.id,m.timestamp,m.compacted
                         FROM messages m JOIN sessions s ON s.id=m.session_id
                        WHERE m.id>? AND m.id<=? AND m.role='user' AND m.active=1
                          AND s.archived=0 ORDER BY m.id LIMIT ?""",
                    (cursor, maximum, limit + 1),
                ).fetchall()
                chosen = rows[:limit]
                changes = tuple(MessageChange(
                    _validate_id(row["id"], "state.db", "message id"),
                    _CAPTURE_REDACTED_SESSION_ID, "", _validate_timestamp(row["timestamp"]),
                    _validate_compacted(row["compacted"]),
                ) for row in chosen)
                return changes, (changes[-1].id if len(rows) > limit else maximum)

            checked = tuple(sorted(
                _validate_id(value, "state.db", "pending message id") for value in pending_ids
            ))
            if len(checked) != len(set(checked)):
                raise DetectionError("state.db: duplicate pending message id")
            selected: list[sqlite3.Row] = []
            total = 0
            if checked:
                prefix = checked[:limit]
                placeholders = ",".join("?" for _ in prefix)
                rows = connection.execute(
                    f"""SELECT m.id,typeof(m.session_id) session_type,typeof(m.content) content_type,
                               length(CAST(m.session_id AS BLOB)) session_bytes,
                               length(CAST(m.content AS BLOB)) content_bytes,
                               m.timestamp,m.compacted,m.active,s.archived,m.role
                          FROM messages m LEFT JOIN sessions s ON s.id=m.session_id
                         WHERE m.id IN ({placeholders}) ORDER BY m.id LIMIT ?""",
                    (*prefix, len(prefix)),
                ).fetchall()
                if [row["id"] for row in rows] != list(prefix):
                    raise DetectionError("state.db: missing pending message")
                sizes: list[int] = []
                for row in rows:
                    identifier = _validate_id(row["id"], "state.db", "message id")
                    if (row["role"] != "user" or type(row["active"]) is not int or row["active"] != 1
                            or type(row["archived"]) is not int or row["archived"] != 0
                            or row["session_type"] != "text" or row["content_type"] != "text"):
                        raise DetectionError(f"state.db: invalid pending message {identifier}")
                    size = _capture_length(row["session_bytes"], "session id", _CAPTURE_SESSION_MAX_BYTES)
                    size += _capture_length(row["content_bytes"], "message content", _CAPTURE_CONTENT_MAX_BYTES)
                    _validate_timestamp(row["timestamp"]); _validate_compacted(row["compacted"])
                    sizes.append(size)
                for row, size in zip(rows, sizes, strict=True):
                    if total + size > _CAPTURE_TOTAL_MESSAGE_BYTES:
                        break
                    selected.append(row); total += size
                if len(selected) < len(checked):
                    return _capture_raw_messages(connection, selected), cursor

            remaining = limit - len(selected)
            _capture_message_metadata_error(connection, cursor, maximum)
            rows = connection.execute(
                """SELECT m.id,typeof(m.session_id) session_type,typeof(m.content) content_type,
                          length(CAST(m.session_id AS BLOB)) session_bytes,
                          length(CAST(m.content AS BLOB)) content_bytes,
                          m.timestamp,m.compacted,m.active,s.archived
                     FROM messages m JOIN sessions s ON s.id=m.session_id
                    WHERE m.id>? AND m.id<=? AND m.role='user' AND m.active=1 AND s.archived=0
                    ORDER BY m.id LIMIT ?""", (cursor, maximum, remaining + 1),
            ).fetchall()
            truncated = len(rows) > remaining
            sizes = []
            for row in rows[:remaining]:
                identifier = _validate_id(row["id"], "state.db", "message id")
                if row["session_type"] != "text" or row["content_type"] != "text":
                    raise DetectionError(f"state.db: invalid message strings for message {identifier}")
                size = _capture_length(row["session_bytes"], "session id", _CAPTURE_SESSION_MAX_BYTES)
                size += _capture_length(row["content_bytes"], "message content", _CAPTURE_CONTENT_MAX_BYTES)
                sizes.append(size)
            for row, size in zip(rows[:remaining], sizes, strict=True):
                if total + size > _CAPTURE_TOTAL_MESSAGE_BYTES:
                    truncated = True
                    break
                selected.append(row); total += size
            messages = _capture_raw_messages(connection, selected)
            new_ids = [row["id"] for row in selected if row["id"] > cursor]
            proposed = new_ids[-1] if truncated and new_ids else (cursor if truncated else maximum)
            return messages, proposed
        finally:
            if connection.in_transaction:
                connection.rollback()


def _read_capture_events(path: Path, cursor: int, *, limit: int) -> tuple[tuple[EventChange, ...], int]:
    if limit == 0:
        return (), cursor
    placeholders = ",".join("?" for _ in _RELEVANT_EVENT_KINDS)
    with contextlib.closing(_open_readonly(path)) as connection:
        connection.execute("BEGIN")
        try:
            _validate_schema(connection, "kanban.db", _REQUIRED_KANBAN_SCHEMA)
            maximum = _validate_id(connection.execute(
                "SELECT COALESCE(MAX(id),?) FROM task_events WHERE id>?", (cursor, cursor)
            ).fetchone()[0], "kanban.db", "event high-water id")
            bad = connection.execute(
                "SELECT id FROM task_events WHERE id>? AND id<=? AND typeof(kind)!='text' ORDER BY id LIMIT 1",
                (cursor, maximum),
            ).fetchone()
            if bad is not None:
                identifier = _validate_id(bad[0], "kanban.db", "event id")
                raise DetectionError(f"kanban.db: invalid kind for event {identifier}")
            rows = connection.execute(
                f"SELECT id,kind FROM task_events WHERE id>? AND id<=? AND kind IN ({placeholders}) "
                "ORDER BY id LIMIT ?", (cursor, maximum, *_RELEVANT_EVENT_KINDS, limit + 1),
            ).fetchall()
            events: list[EventChange] = []
            for row in rows[:limit]:
                identifier = _validate_id(row["id"], "kanban.db", "event id")
                kind = _validate_event_kind(row["kind"], identifier)
                events.append(EventChange(identifier, "capture-redacted", None, kind,
                                          _EVENT_CLASSIFICATIONS[kind], None, None))
            return tuple(events), (events[-1].id if len(rows) > limit else maximum)
        finally:
            if connection.in_transaction:
                connection.rollback()


def detect_capture_changes(state_db: Path, kanban_db: Path, *, profile: str,
                           last_message_id: int, last_event_id: int,
                           pending_message_ids: tuple[int, ...] = (),
                           message_limit: int = _CAPTURE_MAX_MESSAGES,
                           event_limit: int = _CAPTURE_MAX_EVENTS,
                           frozen: bool = False,
                           frozen_capacity: int = _CAPTURE_PENDING_ID_CAP) -> ChangeSet:
    """Read the finite prefix used only by CaptureService."""
    if profile != "default":
        raise DetectionError("profile must be 'default'")
    _validate_cursor("last_message_id", last_message_id)
    _validate_cursor("last_event_id", last_event_id)
    message_limit = _capture_limit(message_limit, "capture message limit", _CAPTURE_MAX_MESSAGES)
    event_limit = _capture_limit(event_limit, "capture event limit", _CAPTURE_MAX_EVENTS)
    frozen_capacity = _capture_limit(
        frozen_capacity, "frozen capture capacity", _CAPTURE_PENDING_ID_CAP
    )
    try:
        if frozen:
            message_limit = min(message_limit, frozen_capacity)
        messages, message_mark = _read_capture_messages(
            state_db, last_message_id, pending_message_ids, limit=message_limit, frozen=frozen
        )
        if frozen:
            event_limit = min(event_limit, frozen_capacity - len(messages))
        events, event_mark = _read_capture_events(kanban_db, last_event_id, limit=event_limit)
    except DetectionError:
        raise
    except (OSError, sqlite3.Error, UnicodeError, TypeError, ValueError,
            OverflowError, RecursionError) as error:
        raise DetectionError(f"capture change detection failed ({type(error).__name__})") from error
    return ChangeSet(messages, events, message_mark, event_mark)


def detect_changes(
    state_db: Path,
    kanban_db: Path,
    *,
    profile: str,
    last_message_id: int,
    last_event_id: int,
) -> ChangeSet:
    """Read changes without mutating either database or persisting cursors."""
    if profile != "default":
        raise DetectionError("profile must be 'default'")
    _validate_cursor("last_message_id", last_message_id)
    _validate_cursor("last_event_id", last_event_id)

    try:
        messages, proposed_message_id = _read_messages(state_db, last_message_id)
        events, proposed_event_id = _read_events(kanban_db, last_event_id)
    except DetectionError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError, RecursionError) as error:
        raise DetectionError(f"change detection failed: {error}") from error

    # Marks are exposed only after both independent reads completed successfully.
    return ChangeSet(
        messages=messages,
        events=events,
        proposed_message_id=proposed_message_id,
        proposed_event_id=proposed_event_id,
    )


@dataclass(frozen=True)
class CaptureRunResult:
    cards: tuple[CreatedCardRef, ...]
    state: SupervisorState


class CaptureService:
    def __init__(self, client: HermesKanbanClient):
        self.client = client

    @staticmethod
    def _persist(store: StateStore, state: SupervisorState) -> None:
        # Service owns the outer lock, so never call StateStore.write here.
        _state_from_data(json.loads(json.dumps(asdict(state))))
        store._write_unlocked(state)

    def run_once(
        self,
        store: StateStore,
        state_db: Path,
        kanban_db: Path,
        *,
        profile: str = "default",
    ) -> CaptureRunResult:
        if profile != "default":
            raise CaptureError("source profile must be 'default'")
        cards: list[CreatedCardRef] = []
        try:
            with StateLock(store.lock_path):
                if store.path.exists():
                    try:
                        state = store.read()
                    except StateError:
                        state = store._recover_unlocked()
                else:
                    state = initial_supervisor_state()
                    self._persist(store, state)

                if state.control_state == "emergency_stopped":
                    return CaptureRunResult((), state)

                pending_count = len(state.pending_message_ids) + len(state.pending_event_ids)
                if pending_count > _CAPTURE_PENDING_ID_CAP:
                    raise StateError("frozen pending id capacity exceeded")
                frozen = state.control_state == "frozen"
                remaining = _CAPTURE_PENDING_ID_CAP - pending_count if frozen else _CAPTURE_PENDING_ID_CAP
                changes = detect_capture_changes(
                    state_db, kanban_db, profile=profile,
                    last_message_id=state.last_message_id,
                    last_event_id=state.last_event_id,
                    pending_message_ids=() if frozen else state.pending_message_ids,
                    message_limit=min(_CAPTURE_MAX_MESSAGES, remaining),
                    event_limit=min(_CAPTURE_MAX_EVENTS, remaining),
                    frozen=frozen,
                    frozen_capacity=remaining,
                )
                if state.control_state == "frozen":
                    observed = record_frozen_observation(state, changes)
                    self._persist(store, observed)
                    return CaptureRunResult((), observed)
                if not card_formation_allowed(state):
                    raise CaptureError("card formation is not allowed")

                by_id: dict[int, MessageChange] = {}
                for message in changes.messages:
                    existing = by_id.get(message.id)
                    if existing is not None and existing != message:
                        raise CaptureError("conflicting source message snapshots")
                    by_id[message.id] = message

                current = state
                for message in sorted(by_id.values(), key=lambda item: item.id):
                    if message.content == BRIEFING_MACHINE_SEED:
                        pending_ids = tuple(
                            identifier for identifier in current.pending_message_ids
                            if identifier != message.id
                        )
                        acknowledged = replace(
                            current,
                            last_message_id=max(current.last_message_id, message.id),
                            pending_message_ids=pending_ids,
                        )
                        self._persist(store, acknowledged)
                        current = acknowledged
                        continue
                    projection = plan_capture(
                        message, profile=profile, extractor_version=current.extractor_version
                    )
                    card = self.client.create(projection)
                    pending_ids = tuple(
                        identifier for identifier in current.pending_message_ids
                        if identifier != message.id
                    )
                    acknowledged = replace(
                        current,
                        last_message_id=max(current.last_message_id, message.id),
                        pending_message_ids=pending_ids,
                    )
                    self._persist(store, acknowledged)
                    current = acknowledged
                    cards.append(card)

                if changes.proposed_message_id < current.last_message_id:
                    raise StateError("proposed message cursor cannot move backwards")
                if changes.proposed_event_id < current.last_event_id:
                    raise StateError("proposed event cursor cannot move backwards")
                final = replace(
                    current,
                    last_message_id=changes.proposed_message_id,
                    last_event_id=changes.proposed_event_id,
                    pending_event_ids=(),
                )
                if final != current:
                    self._persist(store, final)
                return CaptureRunResult(tuple(cards), final)
        except (CaptureError, DetectionError, StateError):
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError, RecursionError) as error:
            raise CaptureError(f"capture cycle failed ({type(error).__name__})") from error


@dataclass(frozen=True)
class StagePolicy:
    name: str
    active_goal_limit: int


@dataclass(frozen=True)
class SchedulingPolicy:
    worker_concurrency: int
    daily_dispatch_limit: int
    daily_supervisor_limit: int
    task_runtime_seconds: int
    normal_retry_limit: int
    replan_limit: int
    model_escalation_limit: int
    watcher_interval_seconds: int
    batch_cooldown_seconds: int


@dataclass(frozen=True)
class BudgetPolicy:
    paid_worker_soft_limit_usd: int


@dataclass(frozen=True)
class CapturePolicy:
    source_profile: str


@dataclass(frozen=True)
class PermissionsPolicy:
    denied_paths: tuple[str, ...]


@dataclass(frozen=True)
class BriefingPolicy:
    time: str
    timezone: str


@dataclass(frozen=True)
class RetentionPolicy:
    event_days: int


@dataclass(frozen=True)
class ModelsPolicy:
    supervisor: str
    verifier: str
    worker: str


@dataclass(frozen=True)
class Policy:
    stage: StagePolicy
    scheduling: SchedulingPolicy
    budget: BudgetPolicy
    capture: CapturePolicy
    permissions: PermissionsPolicy
    briefing: BriefingPolicy
    retention: RetentionPolicy
    models: ModelsPolicy


def _known_mapping(value: Any, section: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyError(f"{section}: expected object")
    unknown = set(value) - keys
    if unknown:
        raise PolicyError(f"{section}: unknown key {sorted(unknown)[0]!r}")
    missing = keys - set(value)
    if missing:
        raise PolicyError(f"{section}: missing required key {sorted(missing)[0]!r}")
    return value


def _integer(mapping: dict[str, Any], section: str, key: str, minimum: int = 0) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PolicyError(f"{section}.{key}: must be an integer >= {minimum}")
    return value


def load_policy(path: Path) -> Policy:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    root = _known_mapping(data, "policy", {
        "stage", "scheduling", "budget", "capture", "permissions",
        "briefing", "retention", "models",
    })
    stage = _known_mapping(root["stage"], "stage", {"name", "active_goal_limit"})
    scheduling = _known_mapping(root["scheduling"], "scheduling", {
        "worker_concurrency", "daily_dispatch_limit", "daily_supervisor_limit",
        "task_runtime_seconds", "normal_retry_limit", "replan_limit",
        "model_escalation_limit", "watcher_interval_seconds",
        "batch_cooldown_seconds",
    })
    budget = _known_mapping(root["budget"], "budget", {"paid_worker_soft_limit_usd"})
    capture = _known_mapping(root["capture"], "capture", {"source_profile"})
    permissions = _known_mapping(root["permissions"], "permissions", {"denied_paths"})
    briefing = _known_mapping(root["briefing"], "briefing", {"time", "timezone"})
    retention = _known_mapping(root["retention"], "retention", {"event_days"})
    models = _known_mapping(root["models"], "models", {"supervisor", "verifier", "worker"})

    _integer(stage, "stage", "active_goal_limit", minimum=1)
    if stage["name"] != "bootstrap":
        raise PolicyError("stage.name: must be 'bootstrap'")
    if stage["active_goal_limit"] != 1:
        raise PolicyError("bootstrap stage requires exactly 1 active goal")
    for key in (
        "worker_concurrency", "daily_dispatch_limit", "daily_supervisor_limit",
        "task_runtime_seconds", "watcher_interval_seconds", "batch_cooldown_seconds",
    ):
        _integer(scheduling, "scheduling", key, minimum=1)
    for key in ("normal_retry_limit", "replan_limit", "model_escalation_limit"):
        _integer(scheduling, "scheduling", key)
    _integer(budget, "budget", "paid_worker_soft_limit_usd")
    _integer(retention, "retention", "event_days", minimum=1)
    if capture["source_profile"] != "default":
        raise PolicyError("capture.source_profile: must be 'default'")
    briefing_time = briefing["time"]
    if not isinstance(briefing_time, str) or re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", briefing_time
    ) is None:
        raise PolicyError("briefing.time: must be strict 24-hour HH:MM")
    briefing_timezone = briefing["timezone"]
    if not isinstance(briefing_timezone, str) or not briefing_timezone:
        raise PolicyError("briefing.timezone: must be a valid timezone")
    try:
        ZoneInfo(briefing_timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise PolicyError("briefing.timezone: must be a valid timezone") from error
    model_aliases = {
        "supervisor": "strong_supervisor",
        "verifier": "strong_verifier",
        "worker": "cheap_worker",
    }
    for key, alias in model_aliases.items():
        if models[key] != alias:
            raise PolicyError(f"models.{key}: must be {alias!r}")
    denied_paths = permissions["denied_paths"]
    if (
        not isinstance(denied_paths, list)
        or any(not isinstance(path, str) or not path for path in denied_paths)
        or "05-Private/" not in denied_paths
    ):
        raise PolicyError("permissions.denied_paths must include '05-Private/'")

    return Policy(
        stage=StagePolicy(**stage),
        scheduling=SchedulingPolicy(**scheduling),
        budget=BudgetPolicy(**budget),
        capture=CapturePolicy(**capture),
        permissions=PermissionsPolicy(denied_paths=tuple(permissions["denied_paths"])),
        briefing=BriefingPolicy(**briefing),
        retention=RetentionPolicy(**retention),
        models=ModelsPolicy(**models),
    )


def _gate_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise GateError(f"{label}: invalid")
    return value


def _validate_gate_policy(policy: Policy) -> None:
    nested_types = (
        ("stage", StagePolicy),
        ("scheduling", SchedulingPolicy),
        ("budget", BudgetPolicy),
        ("capture", CapturePolicy),
        ("permissions", PermissionsPolicy),
        ("briefing", BriefingPolicy),
        ("retention", RetentionPolicy),
        ("models", ModelsPolicy),
    )
    if type(policy) is not Policy or any(
        type(getattr(policy, field)) is not expected
        for field, expected in nested_types
    ):
        raise GateError("policy: invalid")

    if type(policy.stage.name) is not str or policy.stage.name != "bootstrap":
        raise GateError("policy.stage.name: invalid")
    active_goal_limit = _gate_int(
        policy.stage.active_goal_limit, "policy.stage.active_goal_limit", minimum=1
    )
    if active_goal_limit != 1:
        raise GateError("policy.stage.active_goal_limit: invalid")

    positive = (
        (policy.scheduling.worker_concurrency, "worker_concurrency"),
        (policy.scheduling.daily_dispatch_limit, "daily_dispatch_limit"),
        (policy.scheduling.daily_supervisor_limit, "daily_supervisor_limit"),
        (policy.scheduling.task_runtime_seconds, "task_runtime_seconds"),
        (policy.scheduling.watcher_interval_seconds, "watcher_interval_seconds"),
        (policy.scheduling.batch_cooldown_seconds, "batch_cooldown_seconds"),
    )
    for value, label in positive:
        _gate_int(value, f"policy.scheduling.{label}", minimum=1)
    nonnegative = (
        (policy.scheduling.normal_retry_limit, "normal_retry_limit"),
        (policy.scheduling.replan_limit, "replan_limit"),
        (policy.scheduling.model_escalation_limit, "model_escalation_limit"),
    )
    for value, label in nonnegative:
        _gate_int(value, f"policy.scheduling.{label}")
    _gate_int(policy.budget.paid_worker_soft_limit_usd, "policy.budget.paid_worker_soft_limit_usd")

    if (
        type(policy.capture.source_profile) is not str
        or policy.capture.source_profile != "default"
    ):
        raise GateError("policy.capture.source_profile: invalid")

    denied_paths = policy.permissions.denied_paths
    if type(denied_paths) is not tuple or "05-Private/" not in denied_paths:
        raise GateError("policy.permissions.denied_paths: invalid")
    for denied_path in denied_paths:
        if type(denied_path) is not str or not denied_path:
            raise GateError("policy.permissions.denied_paths: invalid")
        try:
            denied_path.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise GateError("policy.permissions.denied_paths: invalid") from error

    briefing_time = policy.briefing.time
    if type(briefing_time) is not str or re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", briefing_time
    ) is None:
        raise GateError("policy.briefing.time: invalid")
    briefing_timezone = policy.briefing.timezone
    if type(briefing_timezone) is not str or not briefing_timezone:
        raise GateError("policy.briefing.timezone: invalid")
    try:
        ZoneInfo(briefing_timezone)
    except (ValueError, ZoneInfoNotFoundError, UnicodeError) as error:
        raise GateError("policy.briefing.timezone: invalid") from error

    _gate_int(policy.retention.event_days, "policy.retention.event_days", minimum=1)

    model_aliases = (
        (policy.models.supervisor, "supervisor", "strong_supervisor"),
        (policy.models.verifier, "verifier", "strong_verifier"),
        (policy.models.worker, "worker", "cheap_worker"),
    )
    for value, field, alias in model_aliases:
        if type(value) is not str or value != alias:
            raise GateError(f"policy.models.{field}: invalid")


def _validate_gate_state(state: SupervisorState) -> None:
    if type(state) is not SupervisorState or type(state.daily_budget) is not DailyBudget:
        raise GateError("state: invalid")
    try:
        _state_from_data(json.loads(json.dumps(asdict(state))))
    except (StateError, TypeError, ValueError, RecursionError) as error:
        raise GateError("state: invalid") from error


def _validate_gate_request(request: GateRequest) -> None:
    if type(request) is not GateRequest:
        raise GateError("request: invalid")
    if type(request.kind) is not str or request.kind not in (
        "supervisor_run", "activate_primary_goal", "dispatch_child", "continue_running"
    ):
        raise GateError("request.kind: invalid")
    if request.goal_id is not None and (
        type(request.goal_id) is not str or not request.goal_id
    ):
        raise GateError("request.goal_id: invalid")
    _gate_int(request.active_worker_count, "request.active_worker_count")
    _gate_int(request.paid_worker_usd, "request.paid_worker_usd")
    if type(request.safety_critical) is not bool:
        raise GateError("request.safety_critical: invalid")
    if type(request.data_loss_risk) is not bool:
        raise GateError("request.data_loss_risk: invalid")
    if request.kind in ("activate_primary_goal", "dispatch_child") and request.goal_id is None:
        raise GateError("request.goal_id: required")


def _budget_blocked_decision(
    reason_code: str,
    budget: DailyBudget,
    primary_goal_id: str | None,
    request: GateRequest,
) -> GateDecision:
    if request.data_loss_risk:
        return GateDecision(
            "needs_human", "data_loss_budget_override_required", budget, primary_goal_id
        )
    if request.safety_critical:
        return GateDecision(
            "needs_human", "safety_budget_override_required", budget, primary_goal_id
        )
    return GateDecision("schedule", reason_code, budget, primary_goal_id)


def _validate_gate_decision(decision: GateDecision) -> None:
    if type(decision) is not GateDecision or type(decision.effective_budget) is not DailyBudget:
        raise GateError("decision: invalid")
    if decision.action not in ("allow", "schedule", "needs_human"):
        raise GateError("decision.action: invalid")
    if (
        type(decision.reason_code) is not str
        or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", decision.reason_code) is None
    ):
        raise GateError("decision.reason_code: invalid")
    budget = decision.effective_budget
    if budget.date is not None:
        if type(budget.date) is not str:
            raise GateError("decision.effective_budget.date: invalid")
        try:
            if calendar_date.fromisoformat(budget.date).isoformat() != budget.date:
                raise ValueError
        except ValueError as error:
            raise GateError("decision.effective_budget.date: invalid") from error
    _gate_int(budget.supervisor_runs, "decision.effective_budget.supervisor_runs")
    _gate_int(budget.dispatches, "decision.effective_budget.dispatches")
    _gate_int(budget.paid_worker_usd, "decision.effective_budget.paid_worker_usd")
    if decision.next_primary_goal_id is not None and (
        type(decision.next_primary_goal_id) is not str or not decision.next_primary_goal_id
    ):
        raise GateError("decision.next_primary_goal_id: invalid")


def gate_decision_report(decision: GateDecision) -> dict[str, Any]:
    """Return a minimal deterministic, JSON-safe representation for dry runs."""
    _validate_gate_decision(decision)
    budget = decision.effective_budget
    return {
        "action": decision.action,
        "reason_code": decision.reason_code,
        "effective_budget": {
            "date": budget.date,
            "supervisor_runs": budget.supervisor_runs,
            "dispatches": budget.dispatches,
            "paid_worker_usd": budget.paid_worker_usd,
        },
        "next_primary_goal_id": decision.next_primary_goal_id,
    }


def decide_gate(
    policy: Policy,
    state: SupervisorState,
    request: GateRequest,
    now: datetime,
) -> GateDecision:
    """Return a pure Stage0 reservation decision without performing side effects."""
    if type(now) is not datetime or now.tzinfo is None:
        raise GateError("now: timezone-aware datetime required")
    try:
        offset = now.utcoffset()
    except Exception as error:
        raise GateError("now: invalid timezone value") from error
    if offset is None:
        raise GateError("now: timezone-aware datetime required")
    _validate_gate_policy(policy)
    _validate_gate_state(state)
    _validate_gate_request(request)
    validated_zone = ZoneInfo(policy.briefing.timezone)
    try:
        today = now.astimezone(validated_zone).date().isoformat()
    except Exception as error:
        raise GateError("now: invalid timezone value") from error
    budget = state.daily_budget
    if budget.date is None or budget.date < today:
        budget = DailyBudget(today, 0, 0, 0)
    elif budget.date > today:
        return GateDecision(
            "needs_human", "budget_clock_rollback", budget,
            state.last_accepted_primary_goal_id,
        )
    if state.control_state == "emergency_stopped":
        return GateDecision(
            "needs_human", "emergency_stop_active", budget,
            state.last_accepted_primary_goal_id,
        )
    if state.control_state == "paused":
        return GateDecision(
            "schedule", "control_paused", budget,
            state.last_accepted_primary_goal_id,
        )
    if state.control_state == "frozen":
        return GateDecision(
            "schedule", "control_frozen", budget,
            state.last_accepted_primary_goal_id,
        )
    if request.kind == "continue_running":
        return GateDecision(
            "allow", "running_work_continues", budget,
            state.last_accepted_primary_goal_id,
        )
    if request.kind == "activate_primary_goal":
        if type(request.goal_id) is not str or not request.goal_id:
            raise GateError("request.goal_id: required")
        primary = state.last_accepted_primary_goal_id
        if primary is None:
            return GateDecision("allow", "primary_goal_accepted", budget, request.goal_id)
        if primary == request.goal_id:
            return GateDecision("allow", "primary_goal_reused", budget, primary)
        if request.data_loss_risk:
            return GateDecision(
                "allow", "data_loss_primary_goal_preemption", budget, request.goal_id
            )
        if request.safety_critical:
            return GateDecision(
                "allow", "safety_primary_goal_preemption", budget, request.goal_id
            )
        return GateDecision("schedule", "bootstrap_primary_goal_limit", budget, primary)
    if request.kind == "dispatch_child":
        if type(request.goal_id) is not str or not request.goal_id:
            raise GateError("request.goal_id: required")
        primary = state.last_accepted_primary_goal_id
        if primary is None:
            return GateDecision("schedule", "primary_goal_required", budget, None)
        if request.goal_id != primary:
            return GateDecision("schedule", "bootstrap_primary_goal_limit", budget, primary)
        if request.active_worker_count >= policy.scheduling.worker_concurrency:
            return _budget_blocked_decision(
                "worker_concurrency_limit", budget, primary, request
            )
        if budget.dispatches >= policy.scheduling.daily_dispatch_limit:
            return _budget_blocked_decision("daily_dispatch_limit", budget, primary, request)
        if (
            budget.paid_worker_usd + request.paid_worker_usd
            > policy.budget.paid_worker_soft_limit_usd
        ):
            return _budget_blocked_decision("paid_worker_soft_limit", budget, primary, request)
        return GateDecision(
            "allow",
            "dispatch_allowed",
            replace(
                budget,
                dispatches=budget.dispatches + 1,
                paid_worker_usd=budget.paid_worker_usd + request.paid_worker_usd,
            ),
            primary,
        )
    if request.kind == "supervisor_run":
        if budget.supervisor_runs >= policy.scheduling.daily_supervisor_limit:
            return _budget_blocked_decision(
                "supervisor_daily_limit",
                budget,
                state.last_accepted_primary_goal_id,
                request,
            )
        return GateDecision(
            "allow",
            "supervisor_run_allowed",
            replace(budget, supervisor_runs=budget.supervisor_runs + 1),
            state.last_accepted_primary_goal_id,
        )
    raise GateError("request.kind: unreachable")


def _batch_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise BatchError(f"{label}: invalid")
    return value


def _batch_flags(events: tuple[EventChange, ...]) -> tuple[bool, bool, bool]:
    emergency = safety = data_loss = False
    for event in events:
        payload = event.payload
        if payload is not None and type(payload) is not dict:
            raise BatchError("event payload: invalid")
        for key in ("emergency", "safety_critical", "data_loss_risk"):
            if payload is not None and key in payload and type(payload[key]) is not bool:
                raise BatchError(f"event {event.id} {key}: expected bool")
        if payload:
            emergency = emergency or payload.get("emergency", False)
            safety = safety or payload.get("safety_critical", False)
            data_loss = data_loss or payload.get("data_loss_risk", False)
    return emergency or safety or data_loss, safety, data_loss


def _validate_batch_policy(policy: Policy) -> None:
    try:
        _validate_gate_policy(policy)
    except GateError as error:
        raise BatchError("batch policy: invalid") from error
    if policy.scheduling.task_runtime_seconds != 1800:
        raise BatchError("batch runtime policy must be 1800 seconds")
    if policy.scheduling.normal_retry_limit != 1:
        raise BatchError("batch retry policy must be exactly one retry")


def plan_supervisor_batch(
    changes: ChangeSet, state: SupervisorState, policy: Policy
) -> SupervisorBatchProjection:
    """Project metadata-only accumulated changes into one deterministic card."""
    if type(changes) is not ChangeSet:
        raise BatchError("changes: invalid")
    if type(state) is not SupervisorState or state.schema_version != 2:
        raise BatchError("state: invalid")
    _validate_batch_policy(policy)
    try:
        _validate_gate_state(state)
    except (GateError, StateError) as error:
        raise BatchError("batch state: invalid") from error
    if type(changes.messages) is not tuple or type(changes.events) is not tuple:
        raise BatchError("change collections: invalid")
    message_ids: list[int] = []
    for message in changes.messages:
        if type(message) is not MessageChange:
            raise BatchError("message: invalid")
        identifier = _batch_int(message.id, "message id")
        if type(message.session_id) is not str or type(message.content) is not str:
            raise BatchError("message fields: invalid")
        if type(message.timestamp) not in (int, float) or not math.isfinite(message.timestamp):
            raise BatchError("message timestamp: invalid")
        if type(message.compacted) is not bool:
            raise BatchError("message compacted: invalid")
        message_ids.append(identifier)
    event_ids: list[int] = []
    event_summaries: list[dict[str, Any]] = []
    for event in changes.events:
        if type(event) is not EventChange:
            raise BatchError("event: invalid")
        identifier = _batch_int(event.id, "event id")
        if (
            type(event.task_id) is not str or not event.task_id
            or (event.run_id is not None and (
                type(event.run_id) is not int or event.run_id < 0
            ))
            or type(event.kind) is not str or not event.kind
            or type(event.classification) is not str or not event.classification
            or (event.actor_profile is not None and (
                type(event.actor_profile) is not str or not event.actor_profile
            ))
        ):
            raise BatchError("event fields: invalid")
        for text in (event.task_id, event.kind, event.classification, event.actor_profile):
            if text is not None:
                try:
                    text.encode("utf-8", "strict")
                except UnicodeEncodeError as error:
                    raise BatchError("event fields: invalid") from error
        event_ids.append(identifier)
        event_summaries.append({
            "actor_profile": event.actor_profile,
            "classification": event.classification,
            "id": identifier,
            "kind": event.kind,
            "run_id": event.run_id,
            "task_id": event.task_id,
        })
    message_ids = sorted(set(message_ids))
    event_ids = sorted(set(event_ids))
    if len(message_ids) != len(changes.messages) or len(event_ids) != len(changes.events):
        raise BatchError("duplicate source id")
    message_end = _batch_int(changes.proposed_message_id, "proposed message id")
    event_end = _batch_int(changes.proposed_event_id, "proposed event id")
    message_start = _batch_int(state.last_supervisor_message_id, "supervisor message cursor")
    event_start = _batch_int(state.last_supervisor_event_id, "supervisor event cursor")
    if message_end < message_start or event_end < event_start:
        raise BatchError("batch cursor moved backwards")
    if any(identifier <= message_start or identifier > message_end for identifier in message_ids):
        raise BatchError("message id outside batch window")
    if any(identifier <= event_start or identifier > event_end for identifier in event_ids):
        raise BatchError("event id outside batch window")
    if not message_ids and not event_ids:
        raise BatchError("batch has no relevant changes")
    emergency, safety, data_loss = _batch_flags(changes.events)
    canonical_key = json.dumps(
        {"schema": 2, "version": 1, "message_cursor": message_start,
         "event_cursor": event_start},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    key = "supervisor-batch:v1:" + hashlib.sha256(canonical_key).hexdigest()[:32]
    if state.mode == "shadow":
        contract = {
            "allowed_temperatures": [], "allowed_workspaces": [],
            "child_dispatch": False, "real_apply": False,
        }
    elif state.mode in ("limited", "eco"):
        contract = {
            "allowed_temperatures": ["research", "build"],
            "allowed_workspaces": ["scratch", "project_bound_worktree"],
            "child_dispatch": True, "real_apply": False,
        }
    else:
        raise BatchError("mode: invalid")
    body_object = {
        "batch_key": key,
        "contract": contract,
        "emergency": emergency,
        "event_ids": event_ids,
        "events": sorted(event_summaries, key=lambda item: item["id"]),
        "gate_policy": {
            "daily_supervisor_limit": policy.scheduling.daily_supervisor_limit,
            "data_loss_precedence": True,
            "observe_executes": False,
            "forbidden_workspaces": ["main", "dir", "live"],
        },
        "instruction": _BATCH_INSTRUCTION,
        "message_ids": message_ids,
        "mode": state.mode,
        "schema": "supervisor-batch/v1",
        "source_cursors": {
            "event": {"end": event_end, "start": event_start},
            "message": {"end": message_end, "start": message_start},
        },
    }
    try:
        body = json.dumps(
            body_object, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise BatchError("batch body serialization failed") from error
    if len(body.encode("utf-8")) > 65_536:
        raise BatchError("batch body exceeds 64KiB")
    title = _batch_title(message_start, message_end, event_start, event_end)
    if len(title) > 160:
        raise BatchError("batch title exceeds limit")
    return SupervisorBatchProjection(
        title, body, key, tuple(message_ids), tuple(event_ids), emergency, safety,
        data_loss, state.mode, message_start, event_start, message_end, event_end,
    )


@dataclass(frozen=True)
class SupervisorBatchResult:
    action: str
    reason_code: str
    state: SupervisorState
    projection: SupervisorBatchProjection | None = None
    ack: SupervisorBatchAck | None = None
    gate: GateDecision | None = None
    message_ids: tuple[int, ...] = ()
    event_ids: tuple[int, ...] = ()

    @property
    def reason(self) -> str:
        return self.reason_code

    @property
    def card(self) -> CreatedCardRef | None:
        return None if self.ack is None else self.ack.card


def _validate_batch_result(result: Any) -> SupervisorBatchResult:
    if type(result) is not SupervisorBatchResult:
        raise BatchError("batch result: invalid")
    try:
        _validate_gate_state(result.state)
    except (GateError, StateError, TypeError, ValueError, RecursionError) as error:
        raise BatchError("batch result state: invalid") from error
    if result.action not in {"no_change", "accumulating", "scheduled", "needs_human", "enqueued"}:
        raise BatchError("batch result action: invalid")
    if (type(result.reason_code) is not str or len(result.reason_code) > 64
            or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", result.reason_code) is None):
        raise BatchError("batch result reason_code: invalid")
    if type(result.message_ids) is not tuple or type(result.event_ids) is not tuple:
        raise BatchError("batch result ids: invalid")
    message_ids = _batch_ids(list(result.message_ids), "batch result message ids")
    event_ids = _batch_ids(list(result.event_ids), "batch result event ids")

    if result.action == "no_change":
        if (result.reason_code != "no_changes" or message_ids or event_ids
                or result.projection is not None or result.ack is not None or result.gate is not None):
            raise BatchError("inconsistent no_change batch result")
        return result
    if not message_ids and not event_ids:
        raise BatchError("batch result has no relevant ids")
    if result.action == "accumulating":
        if (result.reason_code != "batch_cooldown_active"
                or result.projection is not None or result.ack is not None or result.gate is not None):
            raise BatchError("inconsistent accumulating batch result")
        return result
    if result.action == "scheduled" and result.reason_code == "batch_clock_rollback":
        if result.projection is not None or result.ack is not None or result.gate is not None:
            raise BatchError("inconsistent clock rollback batch result")
        return result
    if result.action in {"scheduled", "needs_human"}:
        if result.projection is not None or result.ack is not None or type(result.gate) is not GateDecision:
            raise BatchError("inconsistent gated batch result")
        try:
            _validate_gate_decision(result.gate)
        except GateError as error:
            raise BatchError("batch result gate: invalid") from error
        expected_action = "schedule" if result.action == "scheduled" else "needs_human"
        if (result.gate.action != expected_action
                or result.gate.reason_code != result.reason_code
                or result.state.daily_budget != result.gate.effective_budget
                or result.state.last_accepted_primary_goal_id
                != result.gate.next_primary_goal_id):
            raise BatchError("inconsistent gated batch result")
        return result
    if (result.action != "enqueued" or result.reason_code != "supervisor_batch_enqueued"
            or type(result.projection) is not SupervisorBatchProjection
            or type(result.ack) is not SupervisorBatchAck or type(result.gate) is not GateDecision):
        raise BatchError("inconsistent enqueued batch result")
    ack = _validate_batch_ack(result.ack, result.projection)
    try:
        _validate_gate_decision(result.gate)
    except GateError as error:
        raise BatchError("batch result gate: invalid") from error
    if (result.gate.action != "allow"
            or result.gate.reason_code != "supervisor_run_allowed"
            or result.message_ids != ack.message_ids or result.event_ids != ack.event_ids
            or result.state.last_supervisor_message_id != ack.acknowledged_message_id
            or result.state.last_supervisor_event_id != ack.acknowledged_event_id
            or result.state.last_supervisor_enqueued_at is None
            or result.state.daily_budget != result.gate.effective_budget
            or result.state.last_accepted_primary_goal_id != result.gate.next_primary_goal_id):
        raise BatchError("inconsistent enqueued batch result")
    return result


class SupervisorBatchService:
    """Atomically gate and enqueue one accumulated Supervisor batch."""

    def __init__(self, client: Any):
        if not callable(getattr(client, "create_supervisor_batch", None)):
            raise BatchError("batch client: invalid")
        self.client = client

    @staticmethod
    def _epoch(now: datetime) -> int:
        if type(now) is not datetime or now.tzinfo is None:
            raise BatchError("now: timezone-aware datetime required")
        try:
            offset = now.utcoffset()
            timestamp = now.timestamp()
        except Exception as error:
            raise BatchError("now: invalid timezone value") from error
        if offset is None or not math.isfinite(timestamp) or timestamp < 0:
            raise BatchError("now: invalid timezone value")
        return int(timestamp)

    def run_once(
        self,
        store: StateStore,
        state_db: Path,
        kanban_db: Path,
        policy: Policy,
        now: datetime,
        *,
        profile: str = "default",
    ) -> SupervisorBatchResult:
        if type(store) is not StateStore:
            raise BatchError("state store: invalid")
        if profile != "default" or type(profile) is not str:
            raise BatchError("profile must be 'default'")
        epoch = self._epoch(now)
        try:
            with StateLock(store.lock_path):
                if store.path.exists():
                    try:
                        state = store.read()
                    except StateError:
                        state = store._recover_unlocked()
                else:
                    state = initial_supervisor_state()
                    store._write_unlocked(state)
                _validate_batch_policy(policy)
                changes = detect_batch_changes(
                    state_db, kanban_db, profile=profile,
                    last_message_id=state.last_supervisor_message_id,
                    last_event_id=state.last_supervisor_event_id,
                )
                if not changes.messages and not changes.events:
                    advanced = replace(
                        state,
                        last_supervisor_message_id=changes.proposed_message_id,
                        last_supervisor_event_id=changes.proposed_event_id,
                    )
                    result = _validate_batch_result(
                        SupervisorBatchResult("no_change", "no_changes", advanced)
                    )
                    if advanced != state:
                        store._write_unlocked(advanced)
                    return result

                emergency, safety, data_loss = _batch_flags(changes.events)
                source_message_ids = tuple(sorted(message.id for message in changes.messages))
                source_event_ids = tuple(sorted(event.id for event in changes.events))
                last_enqueued = state.last_supervisor_enqueued_at
                if last_enqueued is not None:
                    if last_enqueued > epoch:
                        return _validate_batch_result(SupervisorBatchResult(
                            "scheduled", "batch_clock_rollback", state,
                            message_ids=source_message_ids, event_ids=source_event_ids,
                        ))
                    elapsed = epoch - last_enqueued
                    if elapsed < policy.scheduling.batch_cooldown_seconds and not emergency:
                        return _validate_batch_result(SupervisorBatchResult(
                            "accumulating", "batch_cooldown_active", state,
                            message_ids=source_message_ids, event_ids=source_event_ids,
                        ))

                decision = decide_gate(
                    policy, state,
                    GateRequest(
                        "supervisor_run", safety_critical=safety,
                        data_loss_risk=data_loss,
                    ),
                    now,
                )
                if decision.action != "allow":
                    normalized = state
                    if decision.effective_budget != state.daily_budget:
                        normalized = replace(state, daily_budget=decision.effective_budget)
                    result = _validate_batch_result(SupervisorBatchResult(
                        "scheduled" if decision.action == "schedule" else "needs_human",
                        decision.reason_code, normalized, gate=decision,
                        message_ids=source_message_ids, event_ids=source_event_ids,
                    ))
                    if normalized != state:
                        store._write_unlocked(normalized)
                    return result

                projection = plan_supervisor_batch(changes, state, policy)
                ack = _validate_batch_ack(
                    self.client.create_supervisor_batch(projection), projection
                )
                committed = replace(
                    state,
                    last_supervisor_message_id=ack.acknowledged_message_id,
                    last_supervisor_event_id=ack.acknowledged_event_id,
                    last_supervisor_enqueued_at=epoch,
                    daily_budget=decision.effective_budget,
                    last_accepted_primary_goal_id=decision.next_primary_goal_id,
                )
                result = _validate_batch_result(SupervisorBatchResult(
                    "enqueued", "supervisor_batch_enqueued", committed,
                    projection=projection, ack=ack, gate=decision,
                    message_ids=ack.message_ids, event_ids=ack.event_ids,
                ))
                store._write_unlocked(committed)
                return result
        except (BatchError, CaptureError, DetectionError, GateError, StateError):
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError, RecursionError) as error:
            raise BatchError(f"batch cycle failed ({type(error).__name__})") from error


def supervisor_batch_report(result: SupervisorBatchResult) -> dict[str, Any] | None:
    result = _validate_batch_result(result)
    if result.action in ("no_change", "accumulating"):
        return None
    report: dict[str, Any] = {
        "action": result.action,
        "reason_code": result.reason_code,
        "message_count": len(result.message_ids),
        "event_count": len(result.event_ids),
        "message_ids": list(result.message_ids),
        "event_ids": list(result.event_ids),
    }
    card = result.card
    if card is not None:
        report["card"] = {
            "id": card.id, "status": card.status, "existing": card.existing,
        }
    if result.gate is not None:
        report["gate"] = gate_decision_report(result.gate)
    return report


@dataclass(frozen=True)
class PreparedBriefing:
    title: str
    markdown: str
    decisions: tuple[BriefingDecision, ...]
    human_actions: tuple[str, ...]
    cursor: int
    marker: str
    artifact_path: Path
    state_path: Path


_BRIEFING_MAX_ROWS = 256
_BRIEFING_FIELD_MAX_BYTES = 512
_BRIEFING_TOTAL_RAW_BYTES = 256 * 1024
_BRIEFING_MAX_DECISION_MAPPINGS = 128
_BRIEFING_ARTIFACT_MAX_BYTES = 32 * 1024
_BRIEFING_OWNER = re.compile(r"supervisor(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?")
_BRIEFING_DECISION_KEYS = {
    "key", "question", "options", "recommendation", "dangerous", "importance",
}
_BRIEFING_HUMAN_ACTION_KEYS = {"text"}


def _briefing_text(value: Any, label: str, *, maximum: int = _BRIEFING_FIELD_MAX_BYTES) -> str:
    if type(value) is not str or not value:
        raise BriefingError(f"invalid {label}")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeError as error:
        raise BriefingError(f"invalid {label}") from error
    if len(encoded) > maximum or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise BriefingError(f"invalid {label}")
    return value


def _briefing_json(raw: Any, label: str, maximum: int) -> dict[str, Any]:
    if type(raw) is not str:
        raise BriefingError(f"invalid {label}")
    value = _strict_json_loads(
        raw, max_bytes=maximum, error_type=BriefingError, message=f"invalid {label}"
    )
    if type(value) is not dict:
        raise BriefingError(f"invalid {label}")
    return value


def _decision_contract(value: Any) -> tuple[str, str, tuple[str, ...], str, bool, int]:
    if type(value) is not dict or set(value) != _BRIEFING_DECISION_KEYS:
        raise BriefingError("invalid structured decision")
    key = _briefing_text(value["key"], "decision key", maximum=128)
    if re.fullmatch(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", key) is None:
        raise BriefingError("invalid decision key")
    question = _briefing_text(value["question"], "decision question", maximum=256)
    options_value = value["options"]
    if type(options_value) is not list or not 2 <= len(options_value) <= 8:
        raise BriefingError("invalid decision options")
    options = tuple(
        _briefing_text(item, "decision option", maximum=64) for item in options_value
    )
    if len(options) != len(set(options)):
        raise BriefingError("invalid decision options")
    recommendation = _briefing_text(
        value["recommendation"], "decision recommendation", maximum=64
    )
    if recommendation not in options or type(value["dangerous"]) is not bool:
        raise BriefingError("invalid structured decision")
    importance = value["importance"]
    if type(importance) is not int or not 0 <= importance <= 100:
        raise BriefingError("invalid decision importance")
    return key, question, options, recommendation, value["dangerous"], importance


def _human_action_contract(value: Any) -> str:
    if type(value) is not dict or set(value) != _BRIEFING_HUMAN_ACTION_KEYS:
        raise BriefingError("invalid structured human action")
    return _briefing_text(value["text"], "human action", maximum=256)


def _open_private_directory(path: Path, *, create: bool) -> int:
    if (
        type(path) is not type(Path())
        or not path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        raise BriefingError("invalid private directory")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise BriefingError("invalid private directory")
    descriptor = os.open("/", flags | nofollow)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags | nofollow, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o700, dir_fd=descriptor)
                child = os.open(component, flags | nofollow, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise BriefingError("invalid private directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_private_regular(path: Path, maximum: int, label: str) -> bytes:
    if type(path) is not type(Path()) or type(maximum) is not int or maximum <= 0:
        raise BriefingError(f"invalid {label}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if type(nofollow) is not int:
        raise BriefingError(f"invalid {label}")
    directory_fd = _open_private_directory(path.parent, create=False)
    try:
        fd = os.open(path.name, flags | nofollow, dir_fd=directory_fd)
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_size < 0
                or metadata.st_size > maximum
            ):
                raise BriefingError(f"invalid {label}")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(fd, min(remaining, 64 * 1024))
                if not chunk:
                    raise BriefingError(f"invalid {label}")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(fd, 1):
                raise BriefingError(f"invalid {label}")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


def _atomic_private_write(path: Path, payload: bytes) -> None:
    if type(path) is not type(Path()) or len(payload) > _STATE_JSON_MAX_BYTES:
        raise BriefingError("invalid briefing persistence target")
    directory_fd = -1
    temporary_name = f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    try:
        directory_fd = _open_private_directory(path.parent, create=True)
        try:
            existing = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_nlink != 1
            or existing.st_uid != os.geteuid()
            or existing.st_mode & 0o077
        ):
            raise BriefingError("invalid briefing persistence target")
        fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                fd = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
    except BriefingError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise BriefingError("briefing persistence failed") from error
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _briefing_default_state(month: str) -> dict[str, Any]:
    return {
        "schema_version": 1, "month": month, "cursor": 0, "next_decision": 1,
        "decision_ids": {}, "pin_action_recorded": False, "delivery_anomalies": [],
        "open_decisions": {}, "last_delivered_date": None, "pending": None,
    }


def _validate_briefing_state(value: Any, month: str) -> dict[str, Any]:
    keys = {
        "schema_version", "month", "cursor", "next_decision", "decision_ids",
        "pin_action_recorded", "delivery_anomalies", "open_decisions",
        "last_delivered_date", "pending",
    }
    if type(value) is not dict or set(value) != keys or value["schema_version"] != 1:
        raise BriefingError("invalid briefing state")
    if value["month"] != month or type(value["cursor"]) is not int or value["cursor"] < 0:
        raise BriefingError("invalid briefing state")
    if type(value["next_decision"]) is not int or not 1 <= value["next_decision"] <= 1000:
        raise BriefingError("invalid briefing state")
    mappings = value["decision_ids"]
    if type(mappings) is not dict or len(mappings) > _BRIEFING_MAX_DECISION_MAPPINGS:
        raise BriefingError("invalid briefing state")
    if any(
        type(key) is not str or re.fullmatch(r"D[1-9][0-9]*", identifier) is None
        for key, identifier in mappings.items()
    ) or len(set(mappings.values())) != len(mappings):
        raise BriefingError("invalid briefing state")
    if type(value["pin_action_recorded"]) is not bool:
        raise BriefingError("invalid briefing state")
    open_decisions = value["open_decisions"]
    if type(open_decisions) is not dict or len(open_decisions) > _BRIEFING_MAX_DECISION_MAPPINGS:
        raise BriefingError("invalid briefing state")
    for key, contract in open_decisions.items():
        checked = _decision_contract(contract)
        if key != checked[0] or key not in mappings:
            raise BriefingError("invalid briefing state")
    delivered = value["last_delivered_date"]
    if delivered is not None:
        try:
            if type(delivered) is not str or calendar_date.fromisoformat(delivered).isoformat() != delivered:
                raise ValueError
        except ValueError as error:
            raise BriefingError("invalid briefing state") from error
    anomalies = value["delivery_anomalies"]
    if type(anomalies) is not list or len(anomalies) > 8 or any(
        type(item) is not str or item not in {"discord_delivery_failed"} for item in anomalies
    ):
        raise BriefingError("invalid briefing state")
    pending = value["pending"]
    if pending is not None:
        pending_keys = {
            "date", "cursor", "marker", "artifact", "discord_status",
            "session_done", "included_anomalies",
        }
        if (
            type(pending) is not dict or set(pending) != pending_keys
            or type(pending["date"]) is not str
            or type(pending["cursor"]) is not int or pending["cursor"] < value["cursor"]
            or type(pending["marker"]) is not str
            or type(pending["artifact"]) is not str
            or pending["discord_status"] not in {"none", "pending", "attempted", "failed"}
            or type(pending["session_done"]) is not bool
            or type(pending["included_anomalies"]) is not list
            or len(pending["included_anomalies"]) > 8
            or len(set(pending["included_anomalies"])) != len(pending["included_anomalies"])
            or any(
                type(item) is not str or item not in {"discord_delivery_failed"}
                for item in pending["included_anomalies"]
            )
        ):
            raise BriefingError("invalid briefing state")
        try:
            pending_day = calendar_date.fromisoformat(pending["date"])
        except ValueError as error:
            raise BriefingError("invalid briefing state") from error
        expected_date = pending_day.isoformat()
        expected_marker = (
            f"<!-- supervisor-briefing:{expected_date}:e{pending['cursor']} -->"
        )
        if (
            expected_date != pending["date"]
            or not expected_date.startswith(f"{month}-")
            or pending["artifact"] != f"{expected_date}.md"
            or pending["marker"] != expected_marker
        ):
            raise BriefingError("invalid briefing state")
    return value


def _read_briefing_state(path: Path, month: str) -> dict[str, Any]:
    try:
        payload = _read_private_regular(path, _STATE_JSON_MAX_BYTES, "briefing state")
        value = _strict_json_loads(
            payload.decode("utf-8", "strict"), max_bytes=_STATE_JSON_MAX_BYTES,
            error_type=BriefingError, message="invalid briefing state",
        )
        stored_month = value.get("month") if type(value) is dict else None
        if type(stored_month) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}", stored_month) is None:
            raise BriefingError("invalid briefing state")
        checked = _validate_briefing_state(value, stored_month)
        if stored_month == month or checked["pending"] is not None:
            return checked
        checked.update({
            "month": month,
            "pin_action_recorded": False,
            "last_delivered_date": None,
        })
        return _validate_briefing_state(checked, month)
    except FileNotFoundError:
        return _briefing_default_state(month)
    except BriefingError:
        raise
    except (OSError, UnicodeError) as error:
        raise BriefingError("invalid briefing state") from error


def _write_briefing_state(path: Path, state: dict[str, Any], month: str) -> None:
    checked = _validate_briefing_state(state, month)
    payload = (json.dumps(checked, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_private_write(path, payload)


def _briefing_schema(connection: sqlite3.Connection) -> None:
    required = {
        "tasks": {"id", "title", "status", "created_by", "result", "current_run_id", "block_kind"},
        "task_events": {"id", "task_id", "run_id", "kind", "payload", "created_at"},
        "task_runs": {"id", "task_id", "status", "outcome", "summary", "error"},
    }
    for table, columns in required.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows or not columns.issubset({row[1] for row in rows if type(row[1]) is str}):
            raise BriefingError("incompatible Kanban schema")


def _read_briefing_rows(
    kanban_db: Path, cursor: int,
) -> tuple[list[tuple[Any, ...]], int]:
    try:
        connection = _open_readonly(kanban_db)
        with contextlib.closing(connection):
            connection.execute("BEGIN")
            _briefing_schema(connection)
            metadata = connection.execute(
                """SELECT e.id, length(cast(e.task_id AS blob)),
                          length(cast(e.kind AS blob)), length(cast(e.payload AS blob)),
                          length(cast(t.title AS blob)), length(cast(t.status AS blob)),
                          length(cast(t.created_by AS blob)), length(cast(t.result AS blob)),
                          length(cast(t.block_kind AS blob)), length(cast(r.status AS blob)),
                          length(cast(r.summary AS blob)), length(cast(r.outcome AS blob))
                   FROM task_events e JOIN tasks t ON t.id=e.task_id
                   LEFT JOIN task_runs r ON r.id=e.run_id
                   WHERE e.id > ? ORDER BY e.id LIMIT ?""",
                (cursor, _BRIEFING_MAX_ROWS + 1),
            ).fetchall()
            if len(metadata) > _BRIEFING_MAX_ROWS:
                raise BriefingError("briefing row limit exceeded")
            total = 0
            caps = (
                256, 64, 16 * 1024, 160, 64, 128,
                16 * 1024, 128, 64, 512, 128,
            )
            for row in metadata:
                if type(row[0]) is not int or row[0] <= cursor:
                    raise BriefingError("invalid briefing metadata")
                for size, cap in zip(row[1:], caps, strict=True):
                    if size is not None and (
                        type(size) is not int or size < 0 or size > cap
                    ):
                        raise BriefingError("invalid briefing metadata")
                    total += 0 if size is None else size
            if total > _BRIEFING_TOTAL_RAW_BYTES:
                raise BriefingError("briefing byte limit exceeded")
            rows = connection.execute(
                """SELECT e.id,e.task_id,e.kind,e.payload,t.title,t.status,t.created_by,
                          t.result,t.block_kind,r.status,r.outcome,r.summary
                   FROM task_events e JOIN tasks t ON t.id=e.task_id
                   LEFT JOIN task_runs r ON r.id=e.run_id
                   WHERE e.id > ? ORDER BY e.id LIMIT ?""",
                (cursor, _BRIEFING_MAX_ROWS),
            ).fetchall()
            highwater_row = connection.execute(
                "SELECT coalesce(max(id), ?) FROM task_events", (cursor,)
            ).fetchone()
            connection.rollback()
        if highwater_row is None or type(highwater_row[0]) is not int:
            raise BriefingError("invalid briefing highwater")
        return rows, max(cursor, highwater_row[0])
    except BriefingError:
        raise
    except (sqlite3.Error, OSError, TypeError, ValueError) as error:
        raise BriefingError("Kanban briefing read failed") from error


def prepare_briefing(kanban_db: Path, state_root: Path, day: str) -> PreparedBriefing | None:
    """Persist one deterministic bounded daily projection before any delivery."""
    try:
        parsed_day = calendar_date.fromisoformat(day)
    except (TypeError, ValueError) as error:
        raise BriefingError("invalid briefing date") from error
    if parsed_day.isoformat() != day or type(state_root) is not type(Path()):
        raise BriefingError("invalid briefing date or state root")
    requested_month = day[:7]
    state_path = state_root / "briefings" / "state.json"
    state = _read_briefing_state(state_path, requested_month)
    month = state["month"]
    month_root = state_root / "briefings" / month
    if state["pending"] is not None:
        pending = state["pending"]
        artifact_path = month_root / pending["artifact"]
        try:
            payload = _read_private_regular(
                artifact_path,
                _BRIEFING_ARTIFACT_MAX_BYTES,
                "pending briefing artifact",
            )
            markdown = payload.decode("utf-8", "strict")
        except (OSError, UnicodeError) as error:
            raise BriefingError("invalid pending briefing artifact") from error
        if len(payload) > _BRIEFING_ARTIFACT_MAX_BYTES or pending["marker"] not in markdown:
            raise BriefingError("invalid pending briefing artifact")
        decisions = _decisions_from_markdown(markdown)
        return PreparedBriefing(
            f"Supervisor Console — {month}", markdown, decisions, (), pending["cursor"],
            pending["marker"], artifact_path, state_path,
        )
    rows, highwater = _read_briefing_rows(kanban_db, state["cursor"])
    outcomes: list[str] = []
    anomalies: list[str] = list(state["delivery_anomalies"])
    actions: list[str] = []
    candidates: dict[str, tuple[str, tuple[str, ...], str, bool, int]] = {
        key: _decision_contract(contract)[1:]
        for key, contract in state["open_decisions"].items()
    }
    observed_relevant = False
    for row in rows:
        identifier, task_id, kind, payload_raw, title, status, created_by, result_raw, block_kind, run_status, outcome, run_summary = row
        if (
            type(identifier) is not int or type(task_id) is not str or type(kind) is not str
            or type(title) is not str or type(status) is not str or type(created_by) is not str
        ):
            raise BriefingError("invalid briefing row")
        if _BRIEFING_OWNER.fullmatch(created_by) is None:
            continue
        observed_relevant = True
        safe_title = _briefing_text(title, "task title", maximum=160)
        safe_kind = _briefing_text(kind, "event kind", maximum=64)
        payload = {} if payload_raw is None else _briefing_json(payload_raw, "event payload", 16 * 1024)
        result = {} if result_raw is None else _briefing_json(result_raw, "task result", 16 * 1024)
        for container in (payload, result):
            if "decision" in container:
                key, question, options, recommendation, dangerous, importance = _decision_contract(container["decision"])
                candidate = (question, options, recommendation, dangerous, importance)
                if key in candidates and candidates[key] != candidate:
                    raise BriefingError("conflicting structured decision")
                candidates[key] = candidate
                state["open_decisions"][key] = container["decision"]
            if "human_action" in container:
                actions.append(_human_action_contract(container["human_action"]))
        summary = None
        for container in (payload, result):
            if "summary" in container:
                summary = _briefing_text(container["summary"], "summary")
                break
            if "reason" in container:
                summary = _briefing_text(container["reason"], "reason")
                break
        if summary is None and run_summary is not None:
            summary = _briefing_text(run_summary, "run summary")
        summary = summary or safe_title
        if safe_kind in {"completed", "done", "applied", "reviewed"} or status in {"done", "review"}:
            suffix = "（適用候補）" if status == "review" else ""
            outcomes.append(f"{safe_title}: {summary}{suffix}")
        if safe_kind in {"blocked", "failed", "error"} or status == "blocked" or run_status == "failed":
            reason = block_kind if block_kind is not None else outcome
            safe_reason = ""
            if reason is not None:
                safe_reason = ": " + _briefing_text(reason, "anomaly reason", maximum=128)
            anomalies.append(f"{safe_title}{safe_reason}")
    if (
        not outcomes and not anomalies and not actions
        and (not candidates or (not observed_relevant and state["last_delivered_date"] == day))
    ):
        if highwater != state["cursor"]:
            state["cursor"] = highwater
            _write_briefing_state(state_path, state, month)
        return None
    mappings = state["decision_ids"]
    next_decision = state["next_decision"]
    for key in sorted(candidates):
        if key not in mappings:
            if len(mappings) >= _BRIEFING_MAX_DECISION_MAPPINGS:
                raise BriefingError("decision mapping limit exceeded")
            mappings[key] = f"D{next_decision}"
            next_decision += 1
    state["next_decision"] = next_decision
    decisions = tuple(
        BriefingDecision(mappings[key], key, *candidate)
        for key, candidate in sorted(
            candidates.items(), key=lambda item: (-item[1][4], item[0])
        )[:10]
    )
    marker = f"<!-- supervisor-briefing:{day}:e{highwater} -->"
    title = f"Supervisor Console — {month}"
    lines = [f"# {title}", marker, "", "## changed outcomes"]
    lines.extend(f"- {item}" for item in sorted(set(outcomes)))
    if not outcomes:
        lines.append("- なし")
    lines.extend(["", "## Decisions"])
    for decision in decisions:
        danger = " [DANGEROUS]" if decision.dangerous else ""
        lines.append(f"- {decision.id}{danger} {decision.question} | options: {' / '.join(decision.options)} | recommendation: {decision.recommendation} | key: {decision.key}")
    if not decisions:
        lines.append("- なし")
    lines.extend(["", "## anomalies"])
    lines.extend(f"- {item}" for item in sorted(set(anomalies)))
    if not anomalies:
        lines.append("- なし")
    lines.extend(["", "## Human Actions"])
    lines.extend(f"- {item}" for item in sorted(set(actions)))
    if not actions:
        lines.append("- なし")
    markdown = "\n".join(lines) + "\n"
    encoded = markdown.encode("utf-8")
    if len(encoded) > _BRIEFING_ARTIFACT_MAX_BYTES:
        raise BriefingError("briefing artifact exceeds limit")
    artifact_name = f"{day}.md"
    artifact_path = month_root / artifact_name
    _atomic_private_write(artifact_path, encoded)
    state["pending"] = {
        "date": day, "cursor": highwater, "marker": marker, "artifact": artifact_name,
        "discord_status": "pending" if decisions else "none", "session_done": False,
        "included_anomalies": sorted(set(state["delivery_anomalies"])),
    }
    _write_briefing_state(state_path, state, month)
    return PreparedBriefing(
        title, markdown, decisions, tuple(sorted(set(actions))), highwater, marker,
        artifact_path, state_path,
    )


BRIEFING_MACHINE_SEED = "[supervisor-console-machine-seed:v1]"
_BRIEFING_MAX_SESSION_MESSAGES = 4096


def _briefing_session_id(month: str) -> str:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", month) is None:
        raise BriefingError("invalid briefing month")
    return f"supervisor-console-{month}"


def _session_record(value: Any, *, title: str) -> str | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise BriefingError("invalid session lookup result")
    session_id = value.get("id")
    if (
        type(session_id) is not str or not session_id or len(session_id) > 128
        or value.get("title") != title or value.get("source") != "cli"
    ):
        raise BriefingError("invalid session lookup result")
    return session_id


def _append_pin_action(prepared: PreparedBriefing) -> PreparedBriefing:
    lines = prepared.markdown.rstrip("\n").splitlines()
    pin_line = "- Pin Console: WebUIでこの月次Consoleをピン留めしてください。"
    if pin_line in lines:
        return replace(
            prepared,
            human_actions=tuple(sorted(set(prepared.human_actions + ("Pin Console",)))),
        )
    try:
        heading = lines.index("## Human Actions")
    except ValueError as error:
        raise BriefingError("invalid briefing artifact") from error
    if heading + 1 < len(lines) and lines[heading + 1] == "- なし":
        lines.pop(heading + 1)
    lines.insert(heading + 1, pin_line)
    markdown = "\n".join(lines) + "\n"
    payload = markdown.encode("utf-8")
    if len(payload) > _BRIEFING_ARTIFACT_MAX_BYTES:
        raise BriefingError("briefing artifact exceeds limit")
    _atomic_private_write(prepared.artifact_path, payload)
    return replace(
        prepared, markdown=markdown,
        human_actions=tuple(sorted(set(prepared.human_actions + ("Pin Console",)))),
    )


def _deliver_session(
    store: Any, prepared: PreparedBriefing, prompt_text: str, *, new_session: bool,
) -> str:
    if type(prompt_text) is not str:
        raise BriefingError("invalid briefing prompt")
    try:
        if not prompt_text or len(prompt_text.encode("utf-8", "strict")) > _PROMPT_SIZE_LIMIT:
            raise BriefingError("invalid briefing prompt")
    except UnicodeError as error:
        raise BriefingError("invalid briefing prompt") from error
    session_id = _briefing_session_id(prepared.title[-7:])
    try:
        if new_session:
            returned = store.create_session(session_id, "cli", system_prompt=prompt_text)
            if returned != session_id:
                raise BriefingError("session create returned invalid id")
            result = store.set_session_title(session_id, prepared.title)
            if result is not True:
                raise BriefingError("session title returned invalid result")
        messages = store.get_messages(
            session_id,
            include_inactive=False,
            limit=_BRIEFING_MAX_SESSION_MESSAGES + 1,
            offset=0,
        )
        if type(messages) is not list:
            raise BriefingError("invalid session messages")
        if len(messages) > _BRIEFING_MAX_SESSION_MESSAGES:
            raise BriefingError("session message limit exceeded")
        system_present = False
        seed_present = False
        marker_present = False
        for message in messages:
            if type(message) is not dict or type(message.get("role")) is not str:
                raise BriefingError("invalid session messages")
            content = message.get("content")
            if content is not None and type(content) is not str:
                raise BriefingError("invalid session messages")
            if message["role"] == "system":
                if content != prompt_text:
                    raise BriefingError("conflicting session system prompt")
                system_present = True
            if content == BRIEFING_MACHINE_SEED and message["role"] == "user":
                seed_present = True
            if (
                content is not None
                and message["role"] == "assistant"
                and prepared.marker in content
            ):
                marker_present = True
        if not system_present and messages:
            raise BriefingError("missing session system prompt")
        required_appends = sum((not system_present, not seed_present, not marker_present))
        if len(messages) + required_appends > _BRIEFING_MAX_SESSION_MESSAGES:
            raise BriefingError("session message limit exceeded")
        if not system_present:
            message_id = store.append_message(session_id, "system", prompt_text)
            if type(message_id) is not int or message_id <= 0:
                raise BriefingError("session append returned invalid id")
        if not seed_present:
            message_id = store.append_message(session_id, "user", BRIEFING_MACHINE_SEED)
            if type(message_id) is not int or message_id <= 0:
                raise BriefingError("session append returned invalid id")
        if not marker_present:
            message_id = store.append_message(session_id, "assistant", prepared.markdown)
            if type(message_id) is not int or message_id <= 0:
                raise BriefingError("session append returned invalid id")
        return session_id
    except BriefingError:
        raise
    except Exception as error:
        raise BriefingError(f"session delivery failed ({type(error).__name__})") from error


def _discord_payload(prepared: PreparedBriefing, webui_url: str) -> str:
    if (
        type(webui_url) is not str or len(webui_url) > 2048
        or re.fullmatch(r"https?://[^\s]+", webui_url) is None
    ):
        raise BriefingError("invalid WebUI URL")
    if not prepared.decisions:
        raise BriefingError("Discord payload requires a decision")
    decision = prepared.decisions[0]
    value = {
        "decision_count": len(prepared.decisions),
        "most_important": {"id": decision.id, "question": decision.question},
        "webui_url": webui_url,
    }
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > 4096:
        raise BriefingError("Discord payload exceeds limit")
    return payload


def _run_discord(
    executable: str, target: str, payload: str, runner: Callable[..., Any] | None,
) -> None:
    if (
        type(executable) is not str or not executable or "\x00" in executable
        or type(target) is not str
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", target) is None
        or len(target) > 64
    ):
        raise BriefingError("invalid Discord delivery configuration")
    argv = [executable, "send", "--to", target, payload, "--json"]
    try:
        if runner is None:
            completed = _bounded_subprocess_run(
                argv, environment=dict(os.environ), timeout=30.0, output_limit=16 * 1024
            )
        else:
            completed = runner(
                argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="strict", timeout=30.0, check=False,
                shell=False, env=dict(os.environ),
            )
    except Exception as error:
        raise BriefingError(f"Discord delivery failed ({type(error).__name__})") from error
    if (
        type(getattr(completed, "returncode", None)) is not int
        or type(getattr(completed, "stdout", None)) is not str
        or type(getattr(completed, "stderr", None)) is not str
    ):
        raise BriefingError("Discord delivery returned invalid result")
    if completed.returncode != 0:
        raise BriefingError(f"Discord delivery exited with status {completed.returncode}")


def run_briefing_cycle(
    kanban_db: Path,
    state_root: Path,
    day: str,
    session_store: Any,
    prompt_text: str,
    hermes_executable: str,
    discord_target: str,
    webui_url: str,
    *,
    runner: Callable[..., Any] | None = None,
    route: str = "nightly",
) -> dict[str, Any] | None:
    """Prepare, idempotently import, notify at-most-once, then acknowledge cursor."""
    if route != "nightly":
        raise BriefingError("invalid briefing route")
    prepared = prepare_briefing(kanban_db, state_root, day)
    if prepared is None:
        return None
    month = prepared.title[-7:]
    title = prepared.title
    try:
        lookup = session_store.get_session_by_title(title)
    except Exception as error:
        raise BriefingError(f"session lookup failed ({type(error).__name__})") from error
    existing_session_id = _session_record(lookup, title=title)
    if existing_session_id is not None and existing_session_id != _briefing_session_id(month):
        raise BriefingError("monthly session id mismatch")
    state = _read_briefing_state(prepared.state_path, month)
    pending = state["pending"]
    if pending is None:
        raise BriefingError("missing pending briefing")
    new_session = existing_session_id is None
    if new_session and not state["pin_action_recorded"]:
        prepared = _append_pin_action(prepared)
        state["pin_action_recorded"] = True
        _write_briefing_state(prepared.state_path, state, month)
    session_id = _deliver_session(
        session_store, prepared, prompt_text, new_session=new_session
    )
    state = _read_briefing_state(prepared.state_path, month)
    pending = state["pending"]
    if pending is None:
        raise BriefingError("missing pending briefing")
    pending["session_done"] = True
    included_anomalies = set(pending["included_anomalies"])
    state["delivery_anomalies"] = [
        item for item in state["delivery_anomalies"] if item not in included_anomalies
    ]
    _write_briefing_state(prepared.state_path, state, month)
    if prepared.decisions and pending["discord_status"] == "pending":
        # At-most-once boundary: checkpoint intent before invoking the external sender.
        pending["discord_status"] = "attempted"
        _write_briefing_state(prepared.state_path, state, month)
        try:
            _run_discord(
                hermes_executable, discord_target,
                _discord_payload(prepared, webui_url), runner,
            )
        except BriefingError:
            state = _read_briefing_state(prepared.state_path, month)
            state["pending"]["discord_status"] = "failed"
            if "discord_delivery_failed" not in state["delivery_anomalies"]:
                state["delivery_anomalies"].append("discord_delivery_failed")
            _write_briefing_state(prepared.state_path, state, month)
            raise
    state = _read_briefing_state(prepared.state_path, month)
    pending = state["pending"]
    if pending is None or not pending["session_done"]:
        raise BriefingError("incomplete briefing delivery")
    if pending["discord_status"] == "pending":
        raise BriefingError("incomplete Discord delivery")
    state["cursor"] = pending["cursor"]
    state["last_delivered_date"] = pending["date"]
    state["pending"] = None
    _write_briefing_state(prepared.state_path, state, month)
    return {
        "action": "delivered", "decision_count": len(prepared.decisions),
        "session_id": session_id,
    }


def _decisions_from_markdown(markdown: str) -> tuple[BriefingDecision, ...]:
    decisions: list[BriefingDecision] = []
    pattern = re.compile(
        r"^- (D[1-9][0-9]*)( \[DANGEROUS\])? (.+) \| options: (.+) \| recommendation: (.+) \| key: ([a-z0-9_.-]+)$"
    )
    for line in markdown.splitlines():
        match = pattern.fullmatch(line)
        if match:
            identifier, danger, question, options_raw, recommendation, key = match.groups()
            options = tuple(options_raw.split(" / "))
            decisions.append(BriefingDecision(
                identifier, key, question, options, recommendation, danger is not None, 0
            ))
    return tuple(decisions)


@dataclass(frozen=True)
class WatchCycleResult:
    mode_changed: bool
    mode: str
    capture: CaptureRunResult
    batch: SupervisorBatchResult


def _validate_watch_client(client: Any) -> None:
    if (
        not callable(getattr(client, "create", None))
        or not callable(getattr(client, "create_supervisor_batch", None))
    ):
        raise CaptureError("watch client: invalid")


def run_watch_cycle(
    store: StateStore,
    state_db: Path,
    kanban_db: Path,
    policy: Policy,
    client: Any,
    now: datetime,
    *,
    profile: str = "default",
    mode: str | None = None,
) -> WatchCycleResult:
    """Run exactly one Capture pass followed by one Supervisor batch pass."""
    if type(store) is not StateStore:
        raise StateError("state store: invalid")
    path_type = type(Path())
    if type(state_db) is not path_type or type(kanban_db) is not path_type:
        raise DetectionError("watch database path: invalid")
    if type(policy) is not Policy:
        raise BatchError("watch policy: invalid")
    if type(profile) is not str or profile != "default":
        raise CaptureError("source profile must be 'default'")
    if mode is not None and (type(mode) is not str or mode not in ("shadow", "limited", "eco")):
        raise StateError("mode: invalid")
    _validate_watch_client(client)
    SupervisorBatchService._epoch(now)

    mode_changed = False
    if mode is not None:
        _, mode_changed = store.set_mode(mode)
    capture = CaptureService(client).run_once(
        store, state_db, kanban_db, profile=profile
    )
    batch = SupervisorBatchService(client).run_once(
        store, state_db, kanban_db, policy, now, profile=profile
    )
    return WatchCycleResult(mode_changed, batch.state.mode, capture, batch)


def _validate_card_ref(card: Any) -> CreatedCardRef:
    if type(card) is not CreatedCardRef:
        raise BatchError("watch capture card: invalid")
    for value in (card.id, card.title, card.status):
        if type(value) is not str or not value:
            raise BatchError("watch capture card: invalid")
        try:
            value.encode("utf-8", "strict")
        except UnicodeError as error:
            raise BatchError("watch capture card: invalid") from error
    if card.status not in _KANBAN_TASK_STATUSES - {"archived"} or type(card.existing) is not bool:
        raise BatchError("watch capture card: invalid")
    return card


def watch_cycle_report(result: WatchCycleResult) -> dict[str, Any] | None:
    """Return only IDs, counts, mode metadata, and the existing safe batch report."""
    if (
        type(result) is not WatchCycleResult
        or type(result.mode_changed) is not bool
        or type(result.mode) is not str
        or result.mode not in ("shadow", "limited", "eco")
        or type(result.capture) is not CaptureRunResult
    ):
        raise BatchError("watch result: invalid")
    capture = result.capture
    if type(capture.cards) is not tuple or type(capture.state) is not SupervisorState:
        raise BatchError("watch capture result: invalid")
    try:
        _validate_gate_state(capture.state)
    except (GateError, StateError, TypeError, ValueError, RecursionError) as error:
        raise BatchError("watch capture state: invalid") from error
    cards = tuple(_validate_card_ref(card) for card in capture.cards)
    batch = _validate_batch_result(result.batch)
    if batch.state.mode != result.mode or capture.state.mode != result.mode:
        raise BatchError("watch result mode: inconsistent")
    batch_report = supervisor_batch_report(batch)
    if not result.mode_changed and not cards and batch_report is None:
        return None
    report: dict[str, Any] = {}
    if result.mode_changed:
        report.update({"mode_changed": True, "mode": result.mode})
    if cards:
        report["capture"] = {
            "card_count": len(cards),
            "card_ids": [card.id for card in cards],
        }
    if batch_report is not None:
        report["batch"] = batch_report
    return report


def _safe_change_summary(changes: ChangeSet) -> dict[str, Any]:
    return {
        "messages": [
            {"id": message.id, "session_id": message.session_id}
            for message in changes.messages
        ],
        "events": [
            {
                "id": event.id,
                "task_id": event.task_id,
                "kind": event.kind,
                "actor_profile": event.actor_profile,
                "classification": event.classification,
            }
            for event in changes.events
        ],
        "proposed_message_id": changes.proposed_message_id,
        "proposed_event_id": changes.proposed_event_id,
    }


def _safe_state_summary(state: SupervisorState) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "mode": state.mode,
        "control_state": state.control_state,
        "last_message_id": state.last_message_id,
        "last_event_id": state.last_event_id,
        "pending_message_count": len(state.pending_message_ids),
        "pending_event_count": len(state.pending_event_ids),
        "emergency_stop_requested_at": state.emergency_stop_requested_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-policy")
    validate.add_argument("--policy", type=Path, required=True)
    watch = subparsers.add_parser("watch")
    watch.add_argument("--dry-run", action="store_true")
    watch.add_argument("--policy", type=Path, required=True)
    watch.add_argument("--state-db", type=Path, required=True)
    watch.add_argument("--kanban-db", type=Path, required=True)
    watch.add_argument("--last-message-id", type=int, default=0)
    watch.add_argument("--last-event-id", type=int, default=0)
    watch.add_argument("--profile", default="default")
    watch.add_argument("--state", type=Path)
    watch.add_argument("--board", default="supervisor")
    watch.add_argument("--hermes", default="hermes")
    watch.add_argument("--mode", choices=("shadow", "limited", "eco"))
    gc = subparsers.add_parser("gc")
    gc.add_argument("--older-than", required=True)
    gc.add_argument("--state-root", type=Path, required=True)
    gc.add_argument("--dry-run", action="store_true")
    brief = subparsers.add_parser("brief")
    brief.add_argument("--kanban-db", type=Path, required=True)
    brief.add_argument("--state-root", type=Path, required=True)
    brief.add_argument("--hermes", required=True)
    brief.add_argument("--discord-target", default="discord")
    brief.add_argument("--webui-url", default="https://ser7")
    brief.add_argument("--prompt", type=Path, required=True)
    brief.add_argument("--date")
    state_parser = subparsers.add_parser("state")
    state_commands = state_parser.add_subparsers(dest="state_command", required=True)
    state_init = state_commands.add_parser("init")
    state_init.add_argument("--state", type=Path, required=True)
    state_show = state_commands.add_parser("show")
    state_show.add_argument("--state", type=Path, required=True)
    state_control = state_commands.add_parser("control")
    state_control.add_argument("--state", type=Path, required=True)
    state_control.add_argument(
        "action", choices=("pause", "freeze", "resume", "emergency-stop")
    )
    bootstrap = subparsers.add_parser("bootstrap-profiles")
    bootstrap.add_argument("--dry-run", action="store_true")
    bootstrap.add_argument("--hermes", default="hermes")
    bootstrap.add_argument(
        "--prompt-dir",
        type=Path,
        default=_CANONICAL_PROMPT_DIR,
    )
    args = parser.parse_args()

    if args.command == "watch" and not args.dry_run and args.state is None:
        print("watch: --state is required for actual runs", file=sys.stderr)
        return 2

    if args.command == "brief":
        try:
            if args.date is None:
                day = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
            else:
                day = args.date
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if type(nofollow) is not int:
                raise BriefingError("prompt read requires O_NOFOLLOW")
            fd = os.open(args.prompt, flags | nofollow)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise BriefingError("prompt must be a single-link regular file")
                payload = os.read(fd, _PROMPT_SIZE_LIMIT + 1)
                if len(payload) != metadata.st_size or len(payload) > _PROMPT_SIZE_LIMIT:
                    raise BriefingError("prompt size invalid")
            finally:
                os.close(fd)
            prompt_text = payload.decode("utf-8", "strict")
            from hermes_state import SessionDB
            report = run_briefing_cycle(
                args.kanban_db, args.state_root, day, SessionDB(), prompt_text,
                args.hermes, args.discord_target, args.webui_url,
            )
        except (BriefingError, ImportError, OSError, UnicodeError) as error:
            print(f"brief: {type(error).__name__}", file=sys.stderr)
            return 2
        if report is not None:
            print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0

    if args.command == "gc":
        try:
            result = collect_stale_state_temps(
                args.state_root, parse_older_than(args.older_than),
                now=time.time(), dry_run=args.dry_run,
            )
        except (GCError, StateError) as error:
            print(f"gc: {error}", file=sys.stderr)
            return 2
        if result.candidates:
            print(json.dumps(
                {"candidates": list(result.candidates), "deleted": list(result.deleted)},
                ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            ))
        return 0

    if args.command == "bootstrap-profiles":
        if not args.dry_run:
            print("bootstrap-profiles: --dry-run is required; no changes made", file=sys.stderr)
            return 2
        try:
            prompt_dir = _lexical_absolute_path(args.prompt_dir)
            if prompt_dir != _CANONICAL_PROMPT_DIR:
                raise ProfileBootstrapError("prompt directory must be canonical")
            prompt_sources = validate_prompt_sources(prompt_dir)
            profile_list = HermesProfileClient(args.hermes).list_profiles()
            operations = plan_profile_bootstrap(
                profile_list, prompt_sources, executable=args.hermes
            )
        except ProfileBootstrapError as error:
            print(f"bootstrap-profiles: {error}", file=sys.stderr)
            return 2
        report = {
            "dry_run": True,
            "source_profile": "default",
            "operations": [
                {
                    "profile": operation.profile,
                    "status": operation.status,
                    "argv": operation.argv,
                    "prompt_source": operation.prompt_source,
                }
                for operation in operations
            ],
        }
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0

    if args.command == "state":
        try:
            store = StateStore(args.state)
            if args.state_command == "init":
                supervisor_state = store.initialize()
            elif args.state_command == "show":
                supervisor_state = store.read()
            else:
                supervisor_state = store.control(args.action)
        except StateError as error:
            print(f"state: {error}", file=sys.stderr)
            return 2
        print(json.dumps(_safe_state_summary(supervisor_state), ensure_ascii=True,
                         sort_keys=True, separators=(",", ":")))
        return 0

    try:
        policy = load_policy(args.policy)
    except (PolicyError, json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        print(f"invalid policy: {error}", file=sys.stderr)
        return 2

    if args.command == "validate-policy":
        print(f"stage={policy.stage.name} active_goals={policy.stage.active_goal_limit}")
        return 0
    if not args.dry_run:
        assert args.state is not None
        try:
            client = HermesKanbanClient(args.hermes, args.board)
            result = run_watch_cycle(
                StateStore(args.state), args.state_db, args.kanban_db, policy, client,
                datetime.now(timezone.utc), profile=args.profile, mode=args.mode,
            )
            report = watch_cycle_report(result)
        except (CaptureError, BatchError, DetectionError, GateError, StateError) as error:
            print(f"watch: {error}", file=sys.stderr)
            return 2
        if report is not None:
            print(json.dumps(
                report, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ))
        return 0
    try:
        changes = detect_changes(
            args.state_db,
            args.kanban_db,
            profile=args.profile,
            last_message_id=args.last_message_id,
            last_event_id=args.last_event_id,
        )
    except DetectionError as error:
        print(f"watch: {error}", file=sys.stderr)
        return 2
    if changes.messages or changes.events:
        print(json.dumps(_safe_change_summary(changes), ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
