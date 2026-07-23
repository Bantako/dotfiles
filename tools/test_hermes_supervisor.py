#!/usr/bin/env python3
"""Behavior tests for the Hermes Supervisor policy validator."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermes_supervisor  # noqa: E402
from hermes_supervisor import PolicyError, load_policy  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "tools" / "hermes_supervisor.py"
POLICY = REPO_ROOT / "home" / "modules" / "ai" / "hermes-supervisor" / "policy.json"


class ChangeDetectionTests(unittest.TestCase):
    @staticmethod
    def make_databases(directory: str) -> tuple[Path, Path]:
        state_db = Path(directory) / "state.db"
        kanban_db = Path(directory) / "kanban.db"
        with closing(sqlite3.connect(state_db)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, source TEXT, title TEXT,
                    archived, ended_at REAL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
                    content TEXT, timestamp REAL, active,
                    compacted INTEGER
                );
                """
            )
        with closing(sqlite3.connect(kanban_db)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, status TEXT, assignee TEXT,
                    result TEXT, block_kind TEXT, current_run_id INTEGER
                );
                CREATE TABLE task_events (
                    id INTEGER PRIMARY KEY, task_id, run_id INTEGER,
                    kind TEXT, payload, created_at INTEGER
                );
                CREATE TABLE task_runs (
                    id INTEGER PRIMARY KEY, task_id, profile
                );
                """
            )
        return state_db, kanban_db

    def test_returns_new_user_messages_in_id_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("s1", "cli", "capture", 0, None),
                )
                connection.executemany(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (3, "s1", "user", "third", 3.0, 1, 0),
                        (1, "s1", "user", "old", 1.0, 1, 0),
                        (2, "s1", "user", "second", 2.0, 1, 0),
                    ],
                )

            changes = hermes_supervisor.detect_changes(
                state_db,
                kanban_db,
                profile="default",
                last_message_id=1,
                last_event_id=0,
            )

        self.assertEqual([message.id for message in changes.messages], [2, 3])
        self.assertEqual([message.content for message in changes.messages], ["second", "third"])
        self.assertEqual(changes.proposed_message_id, 3)

    def test_message_poll_uses_one_snapshot_for_high_water_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, _ = self.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as writer, writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("s1", "cli", "capture", 0, None),
                )
                writer.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "s1", "user", "first", 1, 1, 0),
                )

            original_open = hermes_supervisor._open_readonly
            inserted = False

            class InsertBeforeRows:
                def __init__(self, connection: sqlite3.Connection):
                    self.connection = connection

                def execute(self, sql: str, parameters: object = ()):
                    nonlocal inserted
                    if "SELECT m.id" in sql and not inserted:
                        with closing(sqlite3.connect(state_db)) as writer, writer:
                            writer.execute(
                                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (2, "s1", "user", "concurrent", 2, 1, 0),
                            )
                        inserted = True
                    return self.connection.execute(sql, parameters)  # type: ignore[arg-type]

                def __getattr__(self, name: str):
                    return getattr(self.connection, name)

            with mock.patch.object(
                hermes_supervisor,
                "_open_readonly",
                side_effect=lambda path: InsertBeforeRows(original_open(path)),
            ):
                first, first_mark = hermes_supervisor._read_messages(state_db, 0)

            second, second_mark = hermes_supervisor._read_messages(state_db, first_mark)
            third, third_mark = hermes_supervisor._read_messages(state_db, second_mark)

        self.assertTrue(all(message.id <= first_mark for message in first))
        self.assertEqual([message.id for message in first], [1])
        self.assertEqual(first_mark, 1)
        self.assertEqual([message.id for message in second], [2])
        self.assertEqual(second_mark, 2)
        self.assertEqual(third, ())
        self.assertEqual(third_mark, 2)

    def test_event_poll_uses_one_snapshot_for_high_water_rows_and_actor_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as writer, writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    (1, "first", None, "blocked", "{}", 1),
                )

            original_open = hermes_supervisor._open_readonly
            inserted = False

            class InsertBeforeRows:
                def __init__(self, connection: sqlite3.Connection):
                    self.connection = connection

                def execute(self, sql: str, parameters: object = ()):
                    nonlocal inserted
                    if "SELECT e.id" in sql and not inserted:
                        with closing(sqlite3.connect(kanban_db)) as writer, writer:
                            writer.executemany(
                                "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                                [
                                    (2, "second", None, "assigned", '{"assignee":"new"}', 2),
                                    (3, "second", None, "blocked", "{}", 3),
                                ],
                            )
                        inserted = True
                    return self.connection.execute(sql, parameters)  # type: ignore[arg-type]

                def __getattr__(self, name: str):
                    return getattr(self.connection, name)

            with mock.patch.object(
                hermes_supervisor,
                "_open_readonly",
                side_effect=lambda path: InsertBeforeRows(original_open(path)),
            ):
                first, first_mark = hermes_supervisor._read_events(kanban_db, 0)

            second, second_mark = hermes_supervisor._read_events(kanban_db, first_mark)
            third, third_mark = hermes_supervisor._read_events(kanban_db, second_mark)

        self.assertTrue(all(event.id <= first_mark for event in first))
        self.assertEqual([event.id for event in first], [1])
        self.assertEqual(first_mark, 1)
        self.assertEqual([event.id for event in second], [3])
        self.assertEqual(second[0].actor_profile, "new")
        self.assertEqual(second_mark, 3)
        self.assertEqual(third, ())
        self.assertEqual(third_mark, 3)

    def test_detects_actual_terminal_and_rejection_event_representations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("done", "done", "builder", "ok", None, None),
                        ("human", "blocked", "builder", None, "needs_input", None),
                        ("verifier", "blocked", "verifier", None, None, 7),
                    ],
                )
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (4, "verifier", 7, "blocked", '{"reason":"gate rejected"}', 4),
                        (2, "done", 1, "completed", '{"summary":"ok"}', 2),
                        (3, "human", 2, "commented", None, 3),
                    ],
                )
                connection.executemany(
                    "INSERT INTO task_runs VALUES (?, ?, ?)",
                    [(1, "done", "builder"), (7, "verifier", "verifier")],
                )

            changes = hermes_supervisor.detect_changes(
                state_db,
                kanban_db,
                profile="default",
                last_message_id=0,
                last_event_id=1,
            )

        self.assertEqual([event.id for event in changes.events], [2, 4])
        self.assertEqual([event.kind for event in changes.events], ["completed", "blocked"])
        self.assertEqual(changes.events[1].classification, "blocked")
        self.assertEqual(changes.events[1].actor_profile, "verifier")
        self.assertEqual(changes.events[1].payload, {"reason": "gate rejected"})
        self.assertEqual(changes.proposed_event_id, 4)

    def test_event_actor_and_classification_are_grounded_at_event_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                    ("review", "done", "builder", "later", None, None),
                )
                connection.execute(
                    "INSERT INTO task_runs VALUES (?, ?, ?)",
                    (7, "review", "verifier"),
                )
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "review", None, "created", '{"assignee":"builder"}', 1),
                        (2, "review", 7, "blocked", '{"reason":"rejected"}', 2),
                        (3, "review", None, "assigned", '{"assignee":"builder"}', 3),
                    ],
                )

            changes = hermes_supervisor.detect_changes(
                state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
            )

        self.assertEqual(len(changes.events), 1)
        self.assertEqual(changes.events[0].actor_profile, "verifier")
        self.assertEqual(changes.events[0].classification, "blocked")

    def test_event_actor_falls_back_to_latest_assignment_without_tasks_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute("DROP TABLE tasks")
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "task", None, "created", '{"assignee":"creator"}', 1),
                        (2, "task", None, "assigned", '{"assignee":"verifier"}', 2),
                        (3, "task", None, "completion_blocked_hallucination", '{}', 3),
                        (4, "task", None, "assigned", '{"assignee":"builder"}', 4),
                    ],
                )

            changes = hermes_supervisor.detect_changes(
                state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
            )

        self.assertEqual(changes.events[0].actor_profile, "verifier")
        self.assertEqual(changes.events[0].classification, "rejected")

    def test_filters_capture_and_advances_over_irrelevant_tails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    [("live", "cli", "live", 0, None), ("old", "cli", "old", 1, None)],
                )
                connection.executemany(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (1, "live", "assistant", "assistant", 1, 1, 0),
                        (2, "live", "tool", "tool", 2, 1, 0),
                        (3, "live", "system", "system", 3, 1, 0),
                        (4, "live", "user", "inactive", 4, 0, 0),
                        (5, "old", "user", "archived", 5, 1, 0),
                        (6, "live", "user", "compacted but valid", 6, 1, 1),
                        (7, "live", "assistant", "tail", 7, 1, 0),
                    ],
                )
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                    ("task", "blocked", "worker", None, None, None),
                )
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "task", None, "gave_up", '{"trigger_outcome":"crashed"}', 1),
                        (2, "task", None, "dependency_wait", '{"kind":"dependency"}', 2),
                        (3, "task", None, "block_loop_detected", '{"limit":2}', 3),
                        (4, "task", None, "completion_blocked_hallucination", '{"phantom_cards":["t_bad"]}', 4),
                        (5, "task", None, "commented", None, 5),
                        (6, "task", None, "assigned", '{"assignee":"worker"}', 6),
                    ],
                )

            first = hermes_supervisor.detect_changes(
                state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
            )
            second = hermes_supervisor.detect_changes(
                state_db,
                kanban_db,
                profile="default",
                last_message_id=first.proposed_message_id,
                last_event_id=first.proposed_event_id,
            )

        self.assertEqual([message.id for message in first.messages], [6])
        self.assertTrue(first.messages[0].compacted)
        self.assertEqual(first.proposed_message_id, 7)
        self.assertEqual([event.id for event in first.events], [1, 2, 3, 4])
        self.assertEqual(
            [event.classification for event in first.events],
            ["blocked", "waiting", "blocked", "rejected"],
        )
        self.assertEqual(first.proposed_event_id, 6)
        self.assertEqual(second.messages, ())
        self.assertEqual(second.events, ())
        self.assertEqual(second.proposed_message_id, 7)
        self.assertEqual(second.proposed_event_id, 6)

    def test_rejects_non_default_profile_and_invalid_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            with self.assertRaisesRegex(hermes_supervisor.DetectionError, "profile"):
                hermes_supervisor.detect_changes(
                    state_db, kanban_db, profile="worker", last_message_id=0, last_event_id=0
                )
            for value in (-1, True, 1.0, "1", None):
                with self.subTest(value=value):
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_changes(
                            state_db,
                            kanban_db,
                            profile="default",
                            last_message_id=value,  # type: ignore[arg-type]
                            last_event_id=0,
                        )

    def test_missing_or_incompatible_databases_fail_closed_without_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.db"
            valid_state, valid_kanban = self.make_databases(directory)
            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.detect_changes(
                    missing, valid_kanban, profile="default", last_message_id=0, last_event_id=0
                )
            self.assertFalse(missing.exists())

            broken = Path(directory) / "broken.db"
            with closing(sqlite3.connect(broken)) as connection, connection:
                connection.execute("CREATE TABLE task_events (id INTEGER)")
            with self.assertRaises(hermes_supervisor.DetectionError) as caught:
                hermes_supervisor.detect_changes(
                    valid_state, broken, profile="default", last_message_id=0, last_event_id=0
                )
            self.assertNotIn("ChangeSet", str(caught.exception))

            missing_runs = Path(directory) / "missing-runs.db"
            with closing(sqlite3.connect(missing_runs)) as connection, connection:
                connection.execute(
                    "CREATE TABLE task_events "
                    "(id INTEGER, task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER)"
                )
            with self.assertRaisesRegex(hermes_supervisor.DetectionError, "task_runs"):
                hermes_supervisor.detect_changes(
                    valid_state, missing_runs, profile="default", last_message_id=0, last_event_id=0
                )

            with closing(sqlite3.connect(valid_state)) as connection, connection:
                connection.execute("DROP TABLE sessions")
            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.detect_changes(
                    valid_state, valid_kanban, profile="default", last_message_id=0, last_event_id=0
                )

    def test_readonly_connection_rejects_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="supervisor ?# ") as directory:
            state_db, _ = self.make_databases(directory)
            with closing(hermes_supervisor._open_readonly(state_db)) as connection:
                with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                    connection.execute(
                        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                        ("write", "cli", "write", 0, None),
                    )

    def test_rejects_invalid_event_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.make_databases(directory)
            for value in (-1, True, 1.0, "1", None):
                with self.subTest(value=value):
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_changes(
                            state_db,
                            kanban_db,
                            profile="default",
                            last_message_id=0,
                            last_event_id=value,  # type: ignore[arg-type]
                        )

    def test_malformed_run_id_and_deep_payload_are_detection_errors(self) -> None:
        for run_id, payload in (
            (float("inf"), "{}"),
            (None, '{"nested":' * 10000 + "null" + "}" * 10000),
        ):
            with self.subTest(run_id=run_id):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        connection.execute(
                            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                            (1, "task", run_id, "blocked", payload, 1),
                        )
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_changes(
                            state_db,
                            kanban_db,
                            profile="default",
                            last_message_id=0,
                            last_event_id=0,
                        )

    def test_rejects_malformed_message_row_values_without_coercion(self) -> None:
        cases = (
            ("content-null", None, 1, 0, 0, "s1"),
            ("content-blob", sqlite3.Binary(b"content"), 1, 0, 0, "s1"),
            ("timestamp-infinite", "content", float("inf"), 0, 0, "s1"),
            ("compacted", "content", 1, 2, 0, "s1"),
            ("active-real", "content", 1, 0, 0, "s1"),
            ("archived-real", "content", 1, 0, 0.0, "s1"),
            ("session-id-blob", "content", 1, 0, 0, sqlite3.Binary(b"s1")),
        )
        for name, content, timestamp, compacted, archived, session_id in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    active: object = 1.0 if name == "active-real" else 1
                    with closing(sqlite3.connect(state_db)) as connection, connection:
                        connection.execute(
                            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                            (session_id, "cli", "capture", archived, None),
                        )
                        connection.execute(
                            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (1, session_id, "user", content, timestamp, active, compacted),
                        )
                    with self.assertRaisesRegex(
                        hermes_supervisor.DetectionError, "state.db: invalid"
                    ):
                        hermes_supervisor.detect_changes(
                            state_db, kanban_db, profile="default",
                            last_message_id=0, last_event_id=0,
                        )

    def test_rejects_malformed_event_row_values_without_coercion(self) -> None:
        cases = (
            ("run-id-real", 1.5, "task", "{}", None, None),
            ("run-id-text", "run", "task", "{}", None, None),
            ("task-id-numeric", None, 7, "{}", None, None),
            ("task-id-empty", None, "", "{}", None, None),
            ("payload-blob", None, "task", sqlite3.Binary(b"{}"), None, None),
            ("payload-numeric", None, "task", 7, None, None),
            ("run-profile-blob", 1, "task", "{}", sqlite3.Binary(b"worker"), None),
            ("run-profile-numeric", 1, "task", "{}", 7, None),
            ("run-profile-empty", 1, "task", "{}", "", None),
            ("assignment-payload-blob", None, "task", "{}", None, sqlite3.Binary(b'{"assignee":"worker"}')),
            ("assignment-payload-numeric", None, "task", "{}", None, 7),
            ("assignee-empty", None, "task", "{}", None, '{"assignee":""}'),
        )
        for name, run_id, task_id, payload, run_profile, assignment in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        event_id = 1
                        if assignment is not None:
                            connection.execute(
                                "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                                (1, task_id, None, "assigned", assignment, 1),
                            )
                            event_id = 2
                        if run_profile is not None:
                            connection.execute(
                                "INSERT INTO task_runs VALUES (?, ?, ?)",
                                (1, task_id, run_profile),
                            )
                        connection.execute(
                            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                            (event_id, task_id, run_id, "blocked", payload, event_id),
                        )
                    with self.assertRaisesRegex(
                        hermes_supervisor.DetectionError, "kanban.db: invalid"
                    ):
                        hermes_supervisor.detect_changes(
                            state_db, kanban_db, profile="default",
                            last_message_id=0, last_event_id=0,
                        )

    def test_rejects_non_text_event_kinds_within_high_water_range(self) -> None:
        for kind in (sqlite3.Binary(b"blocked"), 7, 1.5, None):
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        connection.execute("DROP TABLE task_events")
                        connection.execute(
                            "CREATE TABLE task_events "
                            "(id INTEGER PRIMARY KEY, task_id, run_id INTEGER, kind, payload, created_at INTEGER)"
                        )
                        connection.executemany(
                            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                            [
                                (1, "task", None, "commented", None, 1),
                                (2, "task", None, kind, None, 2),
                                (3, "task", None, "assigned", "{}", 3),
                            ],
                        )

                    with self.assertRaisesRegex(
                        hermes_supervisor.DetectionError,
                        "kanban.db: invalid kind for event 2",
                    ):
                        hermes_supervisor.detect_changes(
                            state_db, kanban_db, profile="default",
                            last_message_id=0, last_event_id=1,
                        )

    def test_rejects_non_text_message_roles_within_high_water_range(self) -> None:
        for role in (sqlite3.Binary(b"user"), 7, 1.5, None):
            with self.subTest(role=role):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    with closing(sqlite3.connect(state_db)) as connection, connection:
                        connection.execute("DROP TABLE messages")
                        connection.execute(
                            "CREATE TABLE messages "
                            "(id INTEGER PRIMARY KEY, session_id TEXT, role, content TEXT, "
                            "timestamp REAL, active, compacted INTEGER)"
                        )
                        connection.execute(
                            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                            ("s1", "cli", "capture", 0, None),
                        )
                        connection.executemany(
                            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [
                                (1, "s1", "assistant", "old", 1, 1, 0),
                                (2, "s1", role, "bad", 2, 1, 0),
                                (3, "s1", "tool", "tail", 3, 1, 0),
                            ],
                        )

                    with self.assertRaisesRegex(
                        hermes_supervisor.DetectionError,
                        "state.db: invalid role for message 2",
                    ):
                        hermes_supervisor.detect_changes(
                            state_db, kanban_db, profile="default",
                            last_message_id=1, last_event_id=0,
                        )

    def test_event_kind_validator_rejects_non_strings_and_unknown_strings(self) -> None:
        for kind in (None, 1, 1.0, sqlite3.Binary(b"blocked"), "unknown", ""):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(hermes_supervisor.DetectionError, "invalid kind"):
                    hermes_supervisor._validate_event_kind(kind, 7)

    def test_scalar_validators_reject_dynamic_values_without_coercion(self) -> None:
        malformed_ids = (True, -1, 1.0, float("inf"), "1", sqlite3.Binary(b"1"))
        for value in malformed_ids:
            with self.subTest(contract="id", value=value):
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor._validate_id(value, "db", "id")
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor._validate_optional_id(value, "db", "id")

        for value in (True, None, float("inf"), float("nan"), "1", sqlite3.Binary(b"1")):
            with self.subTest(contract="timestamp", value=value):
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor._validate_timestamp(value)

        for value in (True, -1, 2, 0.0, "0", sqlite3.Binary(b"0")):
            with self.subTest(contract="compacted", value=value):
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor._validate_compacted(value)

        for value in (None, "", 1, sqlite3.Binary(b"worker")):
            with self.subTest(contract="non-empty-string", value=value):
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor._validate_string(value, "db", "value")
                if value is not None:
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor._validate_optional_string(value, "db", "value")

        self.assertEqual(
            hermes_supervisor._validate_string("", "db", "content", empty_allowed=True),
            "",
        )
        self.assertIsNone(hermes_supervisor._validate_optional_id(None, "db", "id"))
        self.assertIsNone(hermes_supervisor._validate_optional_string(None, "db", "value"))
        malformed_assignment_row = {
            "run_profile": None,
            "assignment_payload": "{}",
            "assignment_event_id": 1.5,
        }
        with self.assertRaisesRegex(hermes_supervisor.DetectionError, "assignment event id"):
            hermes_supervisor._event_actor(malformed_assignment_row, 7)  # type: ignore[arg-type]

    def test_malformed_assignment_payload_and_assignee_fail_closed(self) -> None:
        for assignment in ('{"assignee":1}', "[]", "{"):
            with self.subTest(assignment=assignment):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = self.make_databases(directory)
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        connection.executemany(
                            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                            [
                                (1, "task", None, "assigned", assignment, 1),
                                (2, "task", None, "blocked", "{}", 2),
                            ],
                        )
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_changes(
                            state_db,
                            kanban_db,
                            profile="default",
                            last_message_id=0,
                            last_event_id=0,
                        )

    def test_change_contracts_are_frozen(self) -> None:
        values = (
            hermes_supervisor.MessageChange(1, "s", "content", 1.0, False),
            hermes_supervisor.EventChange(1, "t", None, "blocked", "blocked", None, {}),
            hermes_supervisor.ChangeSet((), (), 0, 0),
        )
        for value in values:
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    value.id = 2  # type: ignore[attr-defined,misc]

    def test_readonly_connections_close_on_all_outcomes(self) -> None:
        class ConnectionSpy:
            def __init__(self, connection: sqlite3.Connection, fail_query: bool = False):
                self.connection = connection
                self.fail_query = fail_query
                self.closed = False
                self.begin_count = 0
                self.in_transaction_at_close: bool | None = None
                self.statements: list[str] = []

            def execute(self, sql: str, parameters: object = ()):
                self.statements.append(sql)
                if self.fail_query and "SELECT COALESCE" in sql:
                    raise sqlite3.OperationalError("injected query failure")
                result = self.connection.execute(sql, parameters)  # type: ignore[arg-type]
                if sql == "BEGIN":
                    self.begin_count += 1
                return result

            def close(self) -> None:
                self.in_transaction_at_close = self.connection.in_transaction
                self.closed = True
                self.connection.close()

            def __getattr__(self, name: str):
                return getattr(self.connection, name)

        original_open = hermes_supervisor._open_readonly

        def run_case(kind: str) -> list[ConnectionSpy]:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            state_db, kanban_db = self.make_databases(temporary.name)
            if kind == "schema":
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    connection.execute("DROP TABLE sessions")
            elif kind == "decode":
                with closing(sqlite3.connect(kanban_db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                        (1, "task", None, "blocked", "{", 1),
                    )
            elif kind == "value":
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                        ("s1", "cli", "capture", 0, None),
                    )
                    connection.execute(
                        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (1, "s1", "user", None, 1, 1, 0),
                    )
            elif kind == "preflight":
                with closing(sqlite3.connect(kanban_db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                        (1, "task", None, sqlite3.Binary(b"blocked"), "{}", 1),
                    )
            elif kind == "role-preflight":
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                        ("s1", "cli", "capture", 0, None),
                    )
                    connection.execute(
                        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (1, "s1", sqlite3.Binary(b"user"), "content", 1, 1, 0),
                    )
            spies: list[ConnectionSpy] = []

            def open_spy(path: Path) -> ConnectionSpy:
                spy = ConnectionSpy(original_open(path), fail_query=(kind == "query"))
                spies.append(spy)
                return spy

            with mock.patch.object(hermes_supervisor, "_open_readonly", side_effect=open_spy):
                if kind == "success":
                    hermes_supervisor.detect_changes(
                        state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
                    )
                else:
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_changes(
                            state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
                        )
            return spies

        for kind in (
            "success", "schema", "query", "decode", "value", "preflight", "role-preflight"
        ):
            with self.subTest(kind=kind):
                spies = run_case(kind)
                self.assertTrue(spies)
                self.assertTrue(all(spy.closed for spy in spies))
                self.assertTrue(all(spy.begin_count == 1 for spy in spies))
                self.assertTrue(
                    all(spy.in_transaction_at_close is False for spy in spies)
                )
                if kind in ("preflight", "role-preflight"):
                    preflight_spy = spies[-1]
                    expression = "typeof(kind)" if kind == "preflight" else "typeof(role)"
                    preflight_index = next(
                        index for index, sql in enumerate(preflight_spy.statements)
                        if expression in sql
                    )
                    self.assertLess(preflight_spy.statements.index("BEGIN"), preflight_index)


class StrictPayloadTests(unittest.TestCase):
    def test_payload_rejects_duplicate_safety_flags_in_both_orders(self) -> None:
        for flag in ("emergency", "safety_critical", "data_loss_risk"):
            for values in (("true", "false"), ("false", "true")):
                with self.subTest(flag=flag, values=values):
                    raw = f'{{"{flag}":{values[0]},"{flag}":{values[1]}}}'
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor._decode_payload(raw, 7)

    def test_payload_rejects_nested_duplicate_constants_deep_unicode_and_size(self) -> None:
        cases = (
            '{"nested":{"key":1,"key":2}}',
            '{"value":NaN}',
            '{"value":Infinity}',
            '{"value":-Infinity}',
            '{"value":1e999}',
            '{"value":-1e999}',
            '{"value":"\\ud800"}',
            '{"value":' + "[" * 33 + "0" + "]" * 33 + "}",
            '{"value":"' + "x" * hermes_supervisor._PAYLOAD_JSON_MAX_BYTES + '"}',
            '{"value":' + "9" * 5000 + "}",
        )
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(hermes_supervisor.DetectionError) as caught:
                    hermes_supervisor._decode_payload(raw, 8)
                self.assertNotIn(raw[:40], str(caught.exception))

    def test_assignment_payload_uses_same_strict_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "task", None, "assigned", '{"assignee":"safe","assignee":"unsafe"}', 1),
                        (2, "task", None, "blocked", "{}", 2),
                    ],
                )
            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.detect_changes(
                    state_db, kanban_db, profile="default",
                    last_message_id=0, last_event_id=0,
                )


class SupervisorStateTests(unittest.TestCase):
    def test_state_read_rejects_ambiguous_nonstandard_deep_and_oversized_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.initialize()
            canonical = path.read_text(encoding="utf-8").strip()
            v1 = canonical.replace('"schema_version":2', '"schema_version":1').replace(
                ',"last_supervisor_event_id":0,"last_supervisor_message_id":0', ""
            )
            cases = {
                "duplicate-v2": canonical.replace(
                    '"control_state":"running"',
                    '"control_state":"emergency_stopped","control_state":"running"',
                ),
                "duplicate-v1": v1.replace(
                    '"control_state":"running"',
                    '"control_state":"emergency_stopped","control_state":"running"',
                ),
                "nested-duplicate": canonical.replace(
                    '"dispatches":0', '"dispatches":1,"dispatches":0'
                ),
                "nan": canonical.replace('"paid_worker_usd":0', '"paid_worker_usd":NaN'),
                "infinity": canonical.replace('"paid_worker_usd":0', '"paid_worker_usd":Infinity'),
                "negative-infinity": canonical.replace(
                    '"paid_worker_usd":0', '"paid_worker_usd":-Infinity'
                ),
                "exponent-overflow": canonical.replace(
                    '"paid_worker_usd":0', '"paid_worker_usd":1e999'
                ),
                "negative-exponent-overflow": canonical.replace(
                    '"paid_worker_usd":0', '"paid_worker_usd":-1e999'
                ),
                "deep": canonical.replace('"paid_worker_usd":0', '"paid_worker_usd":' + "[" * 33 + "0" + "]" * 33),
                "oversized": canonical + (" " * (hermes_supervisor._STATE_JSON_MAX_BYTES + 1)),
            }
            for name, raw in cases.items():
                with self.subTest(name=name):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaises(hermes_supervisor.StateError):
                        store.read()

    def test_invalid_raw_state_initialization_quarantines_and_freezes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path, clock=lambda: 123)
            store.initialize()
            raw = path.read_text(encoding="utf-8").replace(
                '"control_state":"running"',
                '"control_state":"emergency_stopped","control_state":"running"',
            )
            path.write_text(raw, encoding="utf-8")

            recovered = store.initialize()

            self.assertEqual(recovered.control_state, "frozen")
            self.assertTrue(Path(f"{path}.corrupt.123").exists())

    def test_exponent_overflow_state_initialization_quarantines_and_freezes(self) -> None:
        for token in ("1e999", "-1e999"):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                store = hermes_supervisor.StateStore(path, clock=lambda: 123)
                store.initialize()
                raw = path.read_text(encoding="utf-8").replace(
                    '"paid_worker_usd":0', f'"paid_worker_usd":{token}'
                )
                path.write_text(raw, encoding="utf-8")

                with self.assertRaises(hermes_supervisor.StateError):
                    store.read()
                recovered = store.initialize()

                self.assertEqual(recovered.control_state, "frozen")
                self.assertEqual(Path(f"{path}.corrupt.123").read_text(encoding="utf-8"), raw)

    def test_existing_state_parent_permissions_are_never_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "shared"
            parent.mkdir(mode=0o755)
            parent.chmod(0o755)
            path = parent / "state.json"

            store = hermes_supervisor.StateStore(path)
            store.initialize()
            store.control("pause")
            with hermes_supervisor.StateLock(store.lock_path):
                pass

            self.assertEqual(parent.stat().st_mode & 0o777, 0o755)

    def test_all_new_nested_state_directories_are_exactly_private_under_umask(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "one" / "two" / "state.json"
            previous = os.umask(0o777)
            try:
                hermes_supervisor.StateStore(path).initialize()
            finally:
                os.umask(previous)

            self.assertEqual((root / "one").stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "one" / "two").stat().st_mode & 0o777, 0o700)

    def test_missing_state_initializes_exact_frozen_defaults_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "private" / "state.json"
            state = hermes_supervisor.StateStore(state_path).initialize()

            self.assertEqual(
                state,
                hermes_supervisor.SupervisorState(
                    schema_version=2,
                    mode="shadow",
                    control_state="running",
                    last_message_id=0,
                    last_event_id=0,
                    last_supervisor_enqueued_at=None,
                    daily_budget=hermes_supervisor.DailyBudget(
                        date=None, supervisor_runs=0, dispatches=0, paid_worker_usd=0
                    ),
                    pending_message_ids=(),
                    pending_event_ids=(),
                    last_accepted_primary_goal_id=None,
                    extractor_version="v1",
                    emergency_stop_requested_at=None,
                    last_supervisor_message_id=0,
                    last_supervisor_event_id=0,
                ),
            )
            self.assertEqual(state_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FrozenInstanceError):
                state.daily_budget.dispatches = 1  # type: ignore[misc]

    def test_initialize_at_high_water_sets_both_cursors_once_and_refuses_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "state.json"
            store = hermes_supervisor.StateStore(path)
            state = store.initialize_at(last_message_id=45123, last_event_id=7)
            self.assertEqual(
                (
                    state.mode,
                    state.control_state,
                    state.last_message_id,
                    state.last_event_id,
                    state.last_supervisor_message_id,
                    state.last_supervisor_event_id,
                ),
                ("shadow", "running", 45123, 7, 45123, 7),
            )
            before = path.read_bytes()
            with self.assertRaisesRegex(hermes_supervisor.StateError, "already initialized"):
                store.initialize_at(last_message_id=99999, last_event_id=99)
            self.assertEqual(path.read_bytes(), before)
            for index, (message_id, event_id) in enumerate(
                ((True, 0), (0, True), (-1, 0), (0, -1))
            ):
                with self.subTest(message_id=message_id, event_id=event_id):
                    other = hermes_supervisor.StateStore(Path(directory) / f"bad-{index}")
                    with self.assertRaises(hermes_supervisor.StateError):
                        other.initialize_at(
                            last_message_id=message_id, last_event_id=event_id
                        )

    def test_state_init_cli_accepts_explicit_high_water_marks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "state.json"
            argv = [
                "hermes-supervisor-runtime", "state", "init", "--state", str(path),
                "--last-message-id", "45123", "--last-event-id", "7",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                self.assertEqual(hermes_supervisor.main(), 0)
            state = hermes_supervisor.StateStore(path).read()
            self.assertEqual(
                (
                    state.last_message_id,
                    state.last_event_id,
                    state.last_supervisor_message_id,
                    state.last_supervisor_event_id,
                ),
                (45123, 7, 45123, 7),
            )

    def test_read_round_trips_and_rejects_strict_schema_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            expected = store.initialize()
            self.assertEqual(store.read(), expected)
            valid = json.loads(path.read_text(encoding="utf-8"))

            cases: list[tuple[str, object]] = []
            unknown = dict(valid, unexpected=1)
            cases.append(("unknown", unknown))
            missing = dict(valid)
            del missing["mode"]
            cases.append(("missing", missing))
            for key, value in (
                ("schema_version", True),
                ("last_message_id", -1),
                ("last_event_id", 1.0),
                ("last_supervisor_message_id", True),
                ("last_supervisor_event_id", -1),
                ("mode", "unsafe"),
                ("control_state", "unknown"),
                ("extractor_version", ""),
                ("extractor_version", "v2"),
                ("extractor_version", "arbitrary"),
                ("extractor_version", 1),
                ("extractor_version", None),
                ("pending_message_ids", [1, 1]),
                ("pending_event_ids", [True]),
            ):
                malformed = dict(valid)
                malformed[key] = value
                cases.append((key, malformed))
            nested_unknown = dict(valid)
            nested_unknown["daily_budget"] = dict(valid["daily_budget"], extra=0)
            cases.append(("nested-unknown", nested_unknown))
            nested_bool = dict(valid)
            nested_bool["daily_budget"] = dict(valid["daily_budget"], dispatches=True)
            cases.append(("nested-bool", nested_bool))

            for name, malformed in cases:
                with self.subTest(name=name):
                    path.write_text(json.dumps(malformed), encoding="utf-8")
                    with self.assertRaises(hermes_supervisor.StateError):
                        store.read()

    def test_raw_v1_migrates_in_memory_and_next_write_is_canonical_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            current = store.initialize()
            legacy = json.loads(path.read_text(encoding="utf-8"))
            legacy["schema_version"] = 1
            del legacy["last_supervisor_message_id"]
            del legacy["last_supervisor_event_id"]
            path.write_text(json.dumps(legacy), encoding="utf-8")

            migrated = store.read()
            self.assertEqual(migrated.schema_version, 2)
            self.assertEqual(migrated.last_supervisor_message_id, 0)
            self.assertEqual(migrated.last_supervisor_event_id, 0)
            store.write(migrated)
            rewritten = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(rewritten["schema_version"], 2)
            self.assertEqual(set(rewritten), set(asdict(current)))

    def test_raw_v1_with_mixed_v2_keys_and_schema1_dataclass_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            current = store.initialize()
            mixed = json.loads(path.read_text(encoding="utf-8"))
            mixed["schema_version"] = 1
            del mixed["last_supervisor_event_id"]
            path.write_text(json.dumps(mixed), encoding="utf-8")
            with self.assertRaises(hermes_supervisor.StateError):
                store.read()
            with self.assertRaises(hermes_supervisor.StateError):
                store.write(replace(current, schema_version=1))

    def test_read_rejects_pending_ids_beyond_corresponding_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.initialize()
            valid = json.loads(path.read_text(encoding="utf-8"))

            for pending_key, cursor_key in (
                ("pending_message_ids", "last_message_id"),
                ("pending_event_ids", "last_event_id"),
            ):
                with self.subTest(pending_key=pending_key):
                    malformed = dict(valid)
                    malformed[cursor_key] = 4
                    malformed[pending_key] = [5]
                    path.write_text(json.dumps(malformed), encoding="utf-8")
                    with self.assertRaises(hermes_supervisor.StateError):
                        store.read()

    def test_atomic_write_is_canonical_private_and_replace_failure_preserves_old(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            original = store.initialize()
            old_bytes = path.read_bytes()
            path.chmod(0o666)
            changed = replace(original, control_state="paused")

            with mock.patch.object(hermes_supervisor.os, "replace", side_effect=OSError("injected")):
                with self.assertRaises(hermes_supervisor.StateError):
                    store.write(changed)
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(store.read(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

            store.write(changed)
            self.assertEqual(store.read(), changed)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                path.read_bytes(),
                (json.dumps(json.loads(path.read_text()), sort_keys=True,
                            separators=(",", ":")) + "\n").encode(),
            )

    def test_directory_fsync_failure_reports_uncertain_visible_new_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            original = store.initialize()
            changed = replace(original, control_state="paused")
            real_fsync = os.fsync
            calls = 0

            def fail_directory_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("directory fsync")
                return real_fsync(fd)

            with mock.patch.object(hermes_supervisor.os, "fsync", side_effect=fail_directory_fsync):
                with self.assertRaisesRegex(
                    hermes_supervisor.StateError, "commit durability is uncertain"
                ):
                    store.write(changed)

            self.assertEqual(store.read(), changed)
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

    def test_temp_is_fchmodded_before_write_and_old_state_survives_fchmod_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            original = store.initialize()
            old_bytes = path.read_bytes()
            real_fchmod = os.fchmod

            def fail_for_temp(fd, mode):
                target = os.readlink(f"/proc/self/fd/{fd}")
                if Path(target).name.startswith(f".{path.name}.tmp."):
                    raise OSError("temp fchmod")
                return real_fchmod(fd, mode)

            with mock.patch.object(hermes_supervisor.os, "fchmod", side_effect=fail_for_temp):
                with self.assertRaises(hermes_supervisor.StateError):
                    store.write(replace(original, control_state="paused"))

            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

    def test_replace_alone_sets_private_mode_without_post_replace_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            original = store.initialize()
            path.chmod(0o666)
            chmod_paths: list[object] = []
            real_chmod = os.chmod

            def recording_chmod(target, mode, **kwargs):
                chmod_paths.append(target)
                return real_chmod(target, mode, **kwargs)

            previous = os.umask(0o137)
            try:
                with mock.patch.object(hermes_supervisor.os, "chmod", side_effect=recording_chmod):
                    store.write(replace(original, control_state="paused"))
            finally:
                os.umask(previous)

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(path, chmod_paths)

    def test_file_fsync_failure_preserves_old_state_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            original = store.initialize()
            old_bytes = path.read_bytes()
            with mock.patch.object(hermes_supervisor.os, "fsync", side_effect=OSError("fsync")):
                with self.assertRaises(hermes_supervisor.StateError):
                    store.write(replace(original, control_state="paused"))
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(store.read(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

    def test_initialize_write_failure_is_a_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with mock.patch.object(hermes_supervisor.os, "replace", side_effect=OSError("replace")):
                with self.assertRaises(hermes_supervisor.StateError):
                    hermes_supervisor.StateStore(path).initialize()
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

    def test_recovery_link_failure_is_fail_closed_without_altering_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)

            with mock.patch.object(
                hermes_supervisor.os, "link", side_effect=PermissionError("hard links denied")
            ):
                with self.assertRaises(hermes_supervisor.StateError):
                    hermes_supervisor.StateStore(path, clock=lambda: 123).initialize()

            self.assertEqual(path.read_bytes(), corrupt)
            self.assertEqual(list(path.parent.glob("*.corrupt.*")), [])

    def test_recovery_link_collision_race_uses_new_suffix_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)
            first = Path(f"{path}.corrupt.123")
            real_link = os.link
            attempted = False

            def collide_once(source, destination, *, follow_symlinks=True):
                nonlocal attempted
                if not attempted:
                    attempted = True
                    Path(destination).write_bytes(b"racer")
                    raise FileExistsError(destination)
                return real_link(source, destination, follow_symlinks=follow_symlinks)

            with mock.patch.object(hermes_supervisor.os, "link", side_effect=collide_once):
                recovered = hermes_supervisor.StateStore(path, clock=lambda: 123).initialize()

            self.assertEqual(recovered, hermes_supervisor.initial_supervisor_state(frozen=True))
            self.assertEqual(first.read_bytes(), b"racer")
            self.assertEqual(Path(f"{first}.1").read_bytes(), corrupt)

    def test_recovery_pre_replace_failure_keeps_corrupt_source_and_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)
            path.chmod(0o640)
            store = hermes_supervisor.StateStore(path, clock=lambda: 123)

            with mock.patch.object(
                hermes_supervisor.os, "replace", side_effect=OSError("injected pre-replace")
            ):
                with self.assertRaises(hermes_supervisor.StateError):
                    store.initialize()

            quarantine = Path(f"{path}.corrupt.123")
            self.assertEqual(path.read_bytes(), corrupt)
            self.assertEqual(quarantine.read_bytes(), corrupt)
            self.assertEqual(quarantine.stat().st_mode & 0o777, 0o640)

            recovered = store.initialize()
            self.assertEqual(recovered, hermes_supervisor.initial_supervisor_state(frozen=True))
            self.assertEqual(store.read(), recovered)
            self.assertEqual(recovered.control_state, "frozen")

    def test_recovery_directory_fsync_failure_preserves_durability_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            corrupt = b"{broken"
            path.write_bytes(corrupt)
            store = hermes_supervisor.StateStore(path, clock=lambda: 123)
            real_fsync = os.fsync
            calls = 0

            def fail_directory_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("directory fsync")
                return real_fsync(fd)

            with mock.patch.object(
                hermes_supervisor.os, "fsync", side_effect=fail_directory_fsync
            ):
                with self.assertRaises(hermes_supervisor.StateError) as raised:
                    store.initialize()

            frozen = hermes_supervisor.initial_supervisor_state(frozen=True)
            self.assertIn("commit durability is uncertain", str(raised.exception))
            self.assertEqual(store.read(), frozen)
            self.assertEqual(Path(f"{path}.corrupt.123").read_bytes(), corrupt)
            self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])
            self.assertIs(type(raised.exception), hermes_supervisor.StateDurabilityError)

    def test_initialize_quarantines_corruption_collision_safely_and_recovers_frozen(self) -> None:
        corruptions = (b"{", b"{\xff}", b'{"schema_version":99}')
        for index, contents in enumerate(corruptions):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                path.write_bytes(contents)
                path.chmod(0o640)
                first_collision = Path(f"{path}.corrupt.123")
                first_collision.write_text("occupied")

                recovered = hermes_supervisor.StateStore(path, clock=lambda: 123).initialize()

                self.assertEqual(recovered, hermes_supervisor.initial_supervisor_state(frozen=True))
                quarantine = Path(f"{path}.corrupt.123.1")
                self.assertEqual(quarantine.read_bytes(), contents)
                self.assertEqual(quarantine.stat().st_mode & 0o777, 0o640)
                self.assertEqual(first_collision.read_text(), "occupied")
                self.assertEqual(hermes_supervisor.StateStore(path).read(), recovered)

    def test_control_transitions_preserve_state_and_decisions_fail_closed(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            mode="eco",
            last_message_id=7,
            last_event_id=8,
            last_supervisor_enqueued_at=9,
            daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 2, 3, 1),
            pending_message_ids=(4, 7),
            pending_event_ids=(8,),
            last_accepted_primary_goal_id="goal",
            emergency_stop_requested_at=10,
        )
        for action, expected in (
            ("pause", "paused"), ("freeze", "frozen"), ("resume", "running")
        ):
            with self.subTest(action=action):
                changed = hermes_supervisor.transition_control(state, action, now=99)
                self.assertEqual(changed.control_state, expected)
                self.assertEqual(replace(changed, control_state=state.control_state), state)
        stopped = hermes_supervisor.transition_control(state, "emergency-stop", now=99)
        self.assertEqual(stopped.control_state, "emergency_stopped")
        self.assertEqual(stopped.emergency_stop_requested_at, 99)
        self.assertEqual(
            replace(stopped, control_state=state.control_state,
                    emergency_stop_requested_at=state.emergency_stop_requested_at), state
        )
        with self.assertRaises(hermes_supervisor.StateError):
            hermes_supervisor.transition_control(state, "invalid", now=99)
        self.assertTrue(hermes_supervisor.dispatch_allowed(state))
        self.assertTrue(hermes_supervisor.card_formation_allowed(state))
        self.assertFalse(hermes_supervisor.dispatch_allowed(
            replace(state, control_state="paused")
        ))
        self.assertTrue(hermes_supervisor.card_formation_allowed(
            replace(state, control_state="paused")
        ))
        for control in ("frozen", "emergency_stopped"):
            self.assertFalse(hermes_supervisor.card_formation_allowed(
                replace(state, control_state=control)
            ))

    def test_frozen_observation_advances_marks_uniquely_and_is_idempotent(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(frozen=True),
            last_message_id=2,
            last_event_id=3,
            pending_message_ids=(1,),
            pending_event_ids=(2,),
        )
        changes = hermes_supervisor.ChangeSet(
            messages=(
                hermes_supervisor.MessageChange(4, "s", "secret", 1.0, False),
                hermes_supervisor.MessageChange(4, "s", "secret", 1.0, False),
            ),
            events=(
                hermes_supervisor.EventChange(5, "t", None, "blocked", "blocked", None, {}),
            ),
            proposed_message_id=6,
            proposed_event_id=7,
        )
        observed = hermes_supervisor.record_frozen_observation(state, changes)
        self.assertEqual(observed.last_message_id, 6)
        self.assertEqual(observed.last_event_id, 7)
        self.assertEqual(observed.pending_message_ids, (1, 4))
        self.assertEqual(observed.pending_event_ids, (2, 5))
        self.assertEqual(hermes_supervisor.record_frozen_observation(observed, changes), observed)
        with self.assertRaises(hermes_supervisor.StateError):
            hermes_supervisor.record_frozen_observation(
                replace(state, control_state="running"), changes
            )

    def test_frozen_observation_enforces_cursor_pending_and_observed_id_invariants(self) -> None:
        message = lambda identifier: hermes_supervisor.MessageChange(  # noqa: E731
            identifier, "s", "content", 1.0, False
        )
        event = lambda identifier: hermes_supervisor.EventChange(  # noqa: E731
            identifier, "t", None, "blocked", "blocked", None, {}
        )
        base = replace(
            hermes_supervisor.initial_supervisor_state(frozen=True),
            last_message_id=5,
            last_event_id=5,
            pending_message_ids=(3,),
            pending_event_ids=(3,),
        )

        for field, invalid in (
            ("pending_message_ids", (6,)),
            ("pending_event_ids", (6,)),
        ):
            with self.subTest(invalid_state=field):
                with self.assertRaises(hermes_supervisor.StateError):
                    hermes_supervisor.record_frozen_observation(
                        replace(base, **{field: invalid}),
                        hermes_supervisor.ChangeSet((), (), 5, 5),
                    )

        boundary = hermes_supervisor.record_frozen_observation(
            base,
            hermes_supervisor.ChangeSet((message(6),), (event(6),), 6, 6),
        )
        self.assertEqual(boundary.pending_message_ids, (3, 6))
        self.assertEqual(boundary.pending_event_ids, (3, 6))

        for kind, changes in (
            ("message", hermes_supervisor.ChangeSet((message(7),), (), 6, 5)),
            ("event", hermes_supervisor.ChangeSet((), (event(7),), 5, 6)),
            ("stale-message", hermes_supervisor.ChangeSet((message(4),), (), 5, 5)),
            ("stale-event", hermes_supervisor.ChangeSet((), (event(4),), 5, 5)),
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(hermes_supervisor.StateError):
                    hermes_supervisor.record_frozen_observation(base, changes)

        replay = hermes_supervisor.ChangeSet((message(3),), (event(3),), 5, 5)
        self.assertEqual(hermes_supervisor.record_frozen_observation(base, replay), base)

        for malformed in (True, -1, 1.0, "1", None):
            for kind, changes in (
                ("message", hermes_supervisor.ChangeSet((message(malformed),), (), 5, 5)),
                ("event", hermes_supervisor.ChangeSet((), (event(malformed),), 5, 5)),
            ):
                with self.subTest(kind=kind, malformed=malformed):
                    with self.assertRaises(hermes_supervisor.StateError):
                        hermes_supervisor.record_frozen_observation(base, changes)

        advanced = hermes_supervisor.record_frozen_observation(
            base, hermes_supervisor.ChangeSet((), (), 8, 9)
        )
        self.assertEqual((advanced.last_message_id, advanced.last_event_id), (8, 9))
        self.assertEqual(advanced.pending_message_ids, base.pending_message_ids)
        self.assertEqual(advanced.pending_event_ids, base.pending_event_ids)

    def test_store_invalid_observation_preserves_bytes_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.write(hermes_supervisor.initial_supervisor_state(frozen=True))
            old_bytes = path.read_bytes()
            invalid = hermes_supervisor.ChangeSet(
                (hermes_supervisor.MessageChange(2, "s", "content", 1.0, False),),
                (),
                1,
                0,
            )

            with self.assertRaises(hermes_supervisor.StateError):
                store.record_frozen_observation(invalid)

            self.assertEqual(path.read_bytes(), old_bytes)
            with hermes_supervisor.StateLock(store.lock_path):
                pass

    def test_store_records_frozen_observation_atomically_and_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.write(hermes_supervisor.initial_supervisor_state(frozen=True))
            changes = hermes_supervisor.ChangeSet(
                messages=(hermes_supervisor.MessageChange(4, "s", "secret", 1.0, False),),
                events=(hermes_supervisor.EventChange(
                    5, "t", None, "blocked", "blocked", None, {}
                ),),
                proposed_message_id=6,
                proposed_event_id=7,
            )
            expected = hermes_supervisor.record_frozen_observation(store.read(), changes)

            first = store.record_frozen_observation(changes)
            second = store.record_frozen_observation(changes)

            self.assertEqual(first, expected)
            self.assertEqual(second, expected)
            self.assertEqual(store.read(), expected)

    def test_store_observation_one_lock_covers_read_helper_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.write(hermes_supervisor.initial_supervisor_state(frozen=True))
            changes = hermes_supervisor.ChangeSet((), (), 0, 0)
            original_helper = hermes_supervisor.record_frozen_observation
            helper_saw_busy = False

            def observing_helper(state, observed_changes):
                nonlocal helper_saw_busy
                with self.assertRaises(hermes_supervisor.StateBusyError):
                    with hermes_supervisor.StateLock(store.lock_path):
                        pass
                helper_saw_busy = True
                return original_helper(state, observed_changes)

            with mock.patch.object(
                hermes_supervisor, "record_frozen_observation", side_effect=observing_helper
            ):
                store.record_frozen_observation(changes)

            self.assertTrue(helper_saw_busy)
            with hermes_supervisor.StateLock(store.lock_path):
                pass

    def test_store_observation_busy_is_immediate_and_preserves_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path)
            store.write(hermes_supervisor.initial_supervisor_state(frozen=True))
            old_bytes = path.read_bytes()

            with hermes_supervisor.StateLock(store.lock_path):
                with self.assertRaises(hermes_supervisor.StateBusyError):
                    store.record_frozen_observation(
                        hermes_supervisor.ChangeSet((), (), 0, 0)
                    )

            self.assertEqual(path.read_bytes(), old_bytes)
            with hermes_supervisor.StateLock(store.lock_path):
                pass

    def test_emergency_callback_observes_persisted_stop_and_failure_leaves_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(path, clock=lambda: 456)
            store.initialize()
            observed: list[hermes_supervisor.SupervisorState] = []

            stopped = store.emergency_stop(
                lambda: observed.append(hermes_supervisor.StateStore(path).read())
            )
            self.assertEqual(stopped.control_state, "emergency_stopped")
            self.assertEqual(stopped.emergency_stop_requested_at, 456)
            self.assertEqual(observed, [stopped])

            def fail() -> None:
                self.assertEqual(
                    hermes_supervisor.StateStore(path).read().control_state,
                    "emergency_stopped",
                )
                raise RuntimeError("callback failed")

            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                store.emergency_stop(fail)
            self.assertEqual(store.read().control_state, "emergency_stopped")

    def test_lock_rejects_symlink_without_mutating_victim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "victim"
            victim.write_bytes(b"do not change")
            victim.chmod(0o640)
            lock = root / "state.lock"
            lock.symlink_to(victim)

            with self.assertRaises(hermes_supervisor.StateError):
                with hermes_supervisor.StateLock(lock):
                    self.fail("symlink lock was acquired")

            self.assertEqual(victim.read_bytes(), b"do not change")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o640)

    def test_lock_rejects_hardlink_without_mutating_victim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "victim"
            victim.write_bytes(b"do not change")
            victim.chmod(0o640)
            lock = root / "state.lock"
            os.link(victim, lock)

            with self.assertRaises(hermes_supervisor.StateError):
                with hermes_supervisor.StateLock(lock):
                    self.fail("hardlinked lock was acquired")

            self.assertEqual(victim.read_bytes(), b"do not change")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o640)

    def test_lock_rejects_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "state.lock"
            os.mkfifo(lock, 0o640)

            started = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; sys.path.insert(0, sys.argv[1]); "
                        "from pathlib import Path; "
                        "from hermes_supervisor import StateError, StateLock; "
                        "\ntry:\n StateLock(Path(sys.argv[2])).__enter__()"
                        "\nexcept StateError:\n sys.exit(0)"
                        "\nelse:\n sys.exit(2)"
                    ),
                    str(CLI.parent),
                    str(lock),
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )

            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertEqual(lock.stat().st_mode & 0o777, 0o640)

    def test_lock_acquisition_failures_close_opened_fd_exactly_once(self) -> None:
        failures = (
            ("fstat", hermes_supervisor.os, "fstat"),
            ("fchmod", hermes_supervisor.os, "fchmod"),
            ("flock", hermes_supervisor.fcntl, "flock"),
        )
        for name, owner, attribute in failures:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                lock = Path(directory) / "state.lock"
                real_open = os.open
                real_close = os.close
                opened: list[int] = []
                closed: list[int] = []

                def recording_open(path, flags, mode=0o777):
                    fd = real_open(path, flags, mode)
                    opened.append(fd)
                    return fd

                def recording_close(fd):
                    closed.append(fd)
                    return real_close(fd)

                with (
                    mock.patch.object(hermes_supervisor.os, "open", side_effect=recording_open),
                    mock.patch.object(hermes_supervisor.os, "close", side_effect=recording_close),
                    mock.patch.object(owner, attribute, side_effect=OSError(f"injected {name}")),
                ):
                    with self.assertRaisesRegex(hermes_supervisor.StateError, name):
                        hermes_supervisor.StateLock(lock).__enter__()

                self.assertEqual(len(opened), 1)
                self.assertEqual(closed, opened)
                self.assertFalse(Path(f"/proc/self/fd/{opened[0]}").exists())

    def test_symlink_lock_to_state_cannot_split_lock_across_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            store = hermes_supervisor.StateStore(state_path)
            original = store.initialize()
            old_bytes = state_path.read_bytes()
            store.lock_path.unlink()
            store.lock_path.symlink_to(state_path)

            with self.assertRaises(hermes_supervisor.StateError):
                store.control("pause")

            self.assertEqual(state_path.read_bytes(), old_bytes)
            self.assertEqual(store.read(), original)
            self.assertTrue(store.lock_path.is_symlink())

    def test_lock_fails_closed_if_no_follow_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "state.lock"
            with mock.patch.object(hermes_supervisor.os, "O_NOFOLLOW", new=None):
                with self.assertRaises(hermes_supervisor.StateError):
                    hermes_supervisor.StateLock(lock).__enter__()
            self.assertFalse(lock.exists())

    def test_lock_is_nonblocking_across_processes_and_released_after_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "state.lock"
            code = (
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from pathlib import Path; from hermes_supervisor import StateLock; "
                "lock=StateLock(Path(sys.argv[2])); lock.__enter__(); "
                "print('ready', flush=True); sys.stdin.readline(); lock.__exit__(None,None,None)"
            )
            holder = subprocess.Popen(
                [sys.executable, "-c", code, str(CLI.parent), str(lock)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

            def cleanup_holder() -> None:
                if holder.poll() is None:
                    holder.kill()
                holder.communicate()

            self.addCleanup(cleanup_holder)
            assert holder.stdout is not None
            self.assertEqual(holder.stdout.readline(), "ready\n")

            with self.assertRaises(hermes_supervisor.StateBusyError):
                with hermes_supervisor.StateLock(lock):
                    self.fail("busy lock was acquired")
            self.assertEqual(lock.stat().st_mode & 0o777, 0o600)

            _, stderr = holder.communicate("release\n", timeout=5)
            self.assertEqual(holder.returncode, 0, stderr)
            with hermes_supervisor.StateLock(lock):
                pass

    def test_state_cli_init_control_show_and_concise_corruption_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local" / "state.json"
            init = subprocess.run(
                [sys.executable, str(CLI), "state", "init", "--state", str(path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertEqual(json.loads(init.stdout)["control_state"], "running")
            paused = subprocess.run(
                [
                    sys.executable, str(CLI), "state", "control",
                    "--state", str(path),
                    "--audit", str(path.parent / "audit.jsonl"),
                    "--board", "fixture",
                    "--hermes", "/fake/hermes",
                    "pause",
                ],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(paused.returncode, 0, paused.stderr)
            self.assertEqual(json.loads(paused.stdout)["control_state"], "paused")
            shown = subprocess.run(
                [sys.executable, str(CLI), "state", "show", "--state", str(path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["control_state"], "paused")
            self.assertEqual(shown.stderr, "")
            shown.stdout.encode("ascii")

            path.write_bytes(b"{")
            corrupt = subprocess.run(
                [sys.executable, str(CLI), "state", "show", "--state", str(path)],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(corrupt.returncode, 0)
            self.assertEqual(corrupt.stdout, "")
            self.assertIn("state:", corrupt.stderr)
            self.assertNotIn("Traceback", corrupt.stderr)
            self.assertEqual(path.read_bytes(), b"{")
            self.assertEqual(list(path.parent.glob("*.corrupt.*")), [])


class WatchCliTests(unittest.TestCase):
    def run_watch(
        self,
        state_db: Path,
        kanban_db: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "watch",
                "--dry-run",
                "--policy",
                str(POLICY),
                "--state-db",
                str(state_db),
                "--kanban-db",
                str(kanban_db),
                "--profile",
                "default",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_no_changes_has_empty_stdout_and_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            result = self.run_watch(state_db, kanban_db)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_dry_run_uses_existing_state_cursor_without_writing_or_hermes_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("s1", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "s1", "user", "private", 1, 1, 0),
                )
            state = Path(directory) / "private" / "state.json"
            hermes_supervisor.StateStore(state).initialize_at(
                last_message_id=1, last_event_id=0
            )
            before = state.read_bytes()
            marker = Path(directory) / "hermes-called"
            fake = Path(directory) / "hermes"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n", encoding="utf-8")
            fake.chmod(0o700)
            result = self.run_watch(
                state_db, kanban_db, "--state", str(state), "--mode", "limited",
                "--hermes", str(fake), "--board", "supervisor",
            )
            after = state.read_bytes()
            marker_exists = marker.exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(after, before)
        self.assertFalse(marker_exists)

    def test_dry_run_rejects_missing_state_and_ambiguous_explicit_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            missing = Path(directory) / "missing" / "state.json"
            absent = self.run_watch(state_db, kanban_db, "--state", str(missing))
            self.assertEqual(absent.returncode, 2)
            self.assertEqual(absent.stdout, "")
            self.assertIn("watch:", absent.stderr)
            self.assertFalse(missing.exists())

            state = Path(directory) / "state.json"
            hermes_supervisor.StateStore(state).initialize()
            conflict = self.run_watch(
                state_db, kanban_db, "--state", str(state), "--last-message-id", "0"
            )
            self.assertEqual(conflict.returncode, 2)
            self.assertEqual(conflict.stdout, "")
            self.assertEqual(
                conflict.stderr, "watch: explicit cursors conflict with --state\n"
            )

    def test_actual_watch_requires_state_before_policy_or_hermes_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "hermes-called"
            fake = Path(directory) / "hermes"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n", encoding="utf-8")
            fake.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(CLI), "watch", "--policy", str(Path(directory) / "missing"),
                 "--state-db", str(Path(directory) / "missing-state.db"),
                 "--kanban-db", str(Path(directory) / "missing-kanban.db"),
                 "--hermes", str(fake)],
                capture_output=True, text=True, check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "watch: --state is required for actual runs\n")
        self.assertFalse(marker.exists())

    def test_actual_no_change_runs_one_cycle_and_initializes_shadow_without_hermes_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            state = Path(directory) / "state-root" / "state.json"
            marker = Path(directory) / "hermes-called"
            fake = Path(directory) / "hermes"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n", encoding="utf-8")
            fake.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(CLI), "watch", "--policy", str(POLICY),
                 "--state-db", str(state_db), "--kanban-db", str(kanban_db),
                 "--state", str(state), "--hermes", str(fake), "--board", "supervisor"],
                capture_output=True, text=True, check=False,
            )
            persisted = json.loads(state.read_text(encoding="utf-8")) if state.exists() else None

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(persisted["mode"], "shadow")
        self.assertFalse(marker.exists())

    def test_changes_emit_one_safe_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("s1", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (2, "s1", "user", "private user content", 2, 1, 0),
                )
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                    ("task", "done", "builder", "private result", None, None),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    (3, "task", None, "completed", '{"summary":"private payload"}', 3),
                )
            result = self.run_watch(state_db, kanban_db)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["messages"], [{"id": 2, "session_id": "s1"}])
        self.assertEqual(
            payload["events"],
            [{
                "id": 3,
                "task_id": "task",
                "kind": "completed",
                "actor_profile": None,
                "classification": "completed",
            }],
        )
        self.assertEqual(payload["proposed_message_id"], 2)
        self.assertEqual(payload["proposed_event_id"], 3)
        self.assertNotIn("private", result.stdout)
        self.assertNotIn("payload", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_lone_surrogate_actor_payload_fails_closed_without_leaking_raw_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("session", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "session", "user", "private content", 1, 1, 0),
                )
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "task", None, "assigned", '{"assignee":"\\ud800"}', 1),
                        (2, "task", None, "completion_blocked_hallucination", '{"secret":"private payload"}', 2),
                    ],
                )
            result = self.run_watch(state_db, kanban_db)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid payload", result.stderr)
        self.assertNotIn("\\ud800", result.stderr)
        self.assertNotIn("private payload", result.stderr)
        self.assertNotIn("private content", result.stderr)

    def test_blocked_summary_preserves_builder_and_verifier_event_time_actors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("build", "done", "other", "later", None, None),
                        ("review", "done", "builder", "later", None, None),
                    ],
                )
                connection.executemany(
                    "INSERT INTO task_runs VALUES (?, ?, ?)",
                    [(10, "build", "builder"), (11, "review", "verifier")],
                )
                connection.executemany(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (1, "build", 10, "blocked", '{"secret":"builder reason"}', 1),
                        (2, "review", 11, "blocked", '{"secret":"verifier reason"}', 2),
                        (3, "review", None, "assigned", '{"assignee":"builder"}', 3),
                    ],
                )
            result = self.run_watch(state_db, kanban_db)

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            [(event["actor_profile"], event["classification"]) for event in payload["events"]],
            [("builder", "blocked"), ("verifier", "blocked")],
        )
        self.assertNotIn("reason", result.stdout)
        self.assertNotIn("payload", result.stdout)

    def test_malformed_rows_have_concise_errors_without_traceback(self) -> None:
        for run_id, payload in (
            (float("inf"), "{}"),
            (None, '{"nested":' * 10000 + "null" + "}" * 10000),
        ):
            with self.subTest(run_id=run_id):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        connection.execute(
                            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                            (1, "task", run_id, "blocked", payload, 1),
                        )
                    result = self.run_watch(state_db, kanban_db)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("watch:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_dynamic_type_errors_are_concise_for_message_and_event_rows(self) -> None:
        for source in ("message", "event"):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as directory:
                    state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
                    if source == "message":
                        with closing(sqlite3.connect(state_db)) as connection, connection:
                            connection.execute(
                                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                                ("s1", "cli", "capture", 0, None),
                            )
                            connection.execute(
                                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (1, "s1", "user", None, 1, 1, 0),
                            )
                    else:
                        with closing(sqlite3.connect(kanban_db)) as connection, connection:
                            connection.execute(
                                "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                                (1, "task", None, "blocked", sqlite3.Binary(b"{}"), 1),
                            )
                    result = self.run_watch(state_db, kanban_db)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("watch:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_non_text_event_kind_is_concise_without_stdout_or_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                    (1, "task", None, sqlite3.Binary(b"blocked"), "{}", 1),
                )
            result = self.run_watch(state_db, kanban_db)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "watch: kanban.db: invalid kind for event 1\n")
        self.assertNotIn("Traceback", result.stderr)

    def test_detection_errors_are_concise_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, kanban_db = ChangeDetectionTests.make_databases(directory)
            missing = Path(directory) / "missing-state.db"
            result = self.run_watch(missing, kanban_db)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("watch:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(missing.exists())

    def test_actual_watch_without_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "watch",
                    "--policy",
                    str(POLICY),
                    "--state-db",
                    str(state_db),
                    "--kanban-db",
                    str(kanban_db),
                    "--profile",
                    "default",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "watch: --state is required for actual runs\n")
        self.assertNotIn("Traceback", result.stderr)


class PolicyLoadingTests(unittest.TestCase):
    def load_data(self, data: dict[str, object]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_policy(path)

    def repository_data(self) -> dict[str, object]:
        return json.loads(POLICY.read_text(encoding="utf-8"))

    def test_repository_policy_has_agreed_initial_values(self) -> None:
        policy = load_policy(POLICY)

        self.assertEqual(policy.stage.name, "bootstrap")
        self.assertEqual(policy.stage.active_goal_limit, 1)
        self.assertEqual(policy.scheduling.worker_concurrency, 3)
        self.assertEqual(policy.scheduling.daily_dispatch_limit, 6)
        self.assertEqual(policy.scheduling.daily_supervisor_limit, 12)
        self.assertEqual(policy.scheduling.task_runtime_seconds, 1800)
        self.assertEqual(policy.scheduling.normal_retry_limit, 1)
        self.assertEqual(policy.scheduling.replan_limit, 1)
        self.assertEqual(policy.scheduling.model_escalation_limit, 1)
        self.assertEqual(policy.scheduling.watcher_interval_seconds, 600)
        self.assertEqual(policy.scheduling.batch_cooldown_seconds, 1800)
        self.assertEqual(policy.budget.paid_worker_soft_limit_usd, 2)
        self.assertEqual(policy.capture.source_profile, "default")
        self.assertEqual(policy.permissions.denied_paths, ("05-Private/",))
        self.assertEqual(policy.briefing.time, "21:00")
        self.assertEqual(policy.briefing.timezone, "Asia/Tokyo")
        self.assertEqual(policy.retention.event_days, 30)
        self.assertEqual(policy.models.supervisor, "strong_supervisor")
        self.assertEqual(policy.models.verifier, "strong_verifier")
        self.assertEqual(policy.models.worker, "cheap_worker")

    def test_unknown_keys_fail_closed_at_every_schema_level(self) -> None:
        for section in (None, "stage", "scheduling", "budget", "capture", "permissions", "briefing", "retention", "models"):
            with self.subTest(section=section or "root"):
                data = self.repository_data()
                target = data if section is None else data[section]
                if not isinstance(target, dict):
                    self.fail(f"{section} is not an object")
                target["unexpected"] = True
                with self.assertRaisesRegex(PolicyError, "unknown key"):
                    self.load_data(data)

    def test_missing_required_keys_fail_closed_at_every_schema_level(self) -> None:
        original = self.repository_data()
        cases: list[tuple[str | None, str]] = [
            (None, key) for key in original
        ]
        for section, value in original.items():
            if isinstance(value, dict):
                cases.extend((section, key) for key in value)

        for section, key in cases:
            with self.subTest(section=section or "root", key=key):
                data = self.repository_data()
                target = data if section is None else data[section]
                if not isinstance(target, dict):
                    self.fail(f"{section} is not an object")
                del target[key]
                with self.assertRaisesRegex(PolicyError, "missing required key"):
                    self.load_data(data)

    def test_negative_limits_fail_closed(self) -> None:
        numeric_fields = (
            ("stage", "active_goal_limit"),
            ("scheduling", "worker_concurrency"),
            ("scheduling", "daily_dispatch_limit"),
            ("scheduling", "daily_supervisor_limit"),
            ("scheduling", "task_runtime_seconds"),
            ("scheduling", "normal_retry_limit"),
            ("scheduling", "replan_limit"),
            ("scheduling", "model_escalation_limit"),
            ("scheduling", "watcher_interval_seconds"),
            ("scheduling", "batch_cooldown_seconds"),
            ("budget", "paid_worker_soft_limit_usd"),
            ("retention", "event_days"),
        )
        for section, key in numeric_fields:
            with self.subTest(section=section, key=key):
                data = self.repository_data()
                target = data[section]
                if not isinstance(target, dict):
                    self.fail(f"{section} is not an object")
                target[key] = -1
                with self.assertRaisesRegex(PolicyError, "must be"):
                    self.load_data(data)

    def test_zero_is_only_allowed_for_disableable_limits(self) -> None:
        disableable = (
            ("scheduling", "normal_retry_limit"),
            ("scheduling", "replan_limit"),
            ("scheduling", "model_escalation_limit"),
            ("budget", "paid_worker_soft_limit_usd"),
        )
        for section, key in disableable:
            with self.subTest(kind="allowed", section=section, key=key):
                data = self.repository_data()
                target = data[section]
                if not isinstance(target, dict):
                    self.fail(f"{section} is not an object")
                target[key] = 0
                self.load_data(data)

        positive = (
            ("stage", "active_goal_limit"),
            ("scheduling", "worker_concurrency"),
            ("scheduling", "daily_dispatch_limit"),
            ("scheduling", "daily_supervisor_limit"),
            ("scheduling", "task_runtime_seconds"),
            ("scheduling", "watcher_interval_seconds"),
            ("scheduling", "batch_cooldown_seconds"),
            ("retention", "event_days"),
        )
        for section, key in positive:
            with self.subTest(kind="rejected", section=section, key=key):
                data = self.repository_data()
                target = data[section]
                if not isinstance(target, dict):
                    self.fail(f"{section} is not an object")
                target[key] = 0
                with self.assertRaisesRegex(PolicyError, ">= 1"):
                    self.load_data(data)

    def test_bootstrap_stage_requires_exactly_one_active_goal(self) -> None:
        data = self.repository_data()
        stage = data["stage"]
        if not isinstance(stage, dict):
            self.fail("stage is not an object")
        stage["active_goal_limit"] = 2

        with self.assertRaisesRegex(PolicyError, "bootstrap.*exactly 1"):
            self.load_data(data)

    def test_stage_name_requires_bootstrap_string(self) -> None:
        for value in ("production", "", None, False, []):
            with self.subTest(value=value):
                data = self.repository_data()
                stage = data["stage"]
                if not isinstance(stage, dict):
                    self.fail("stage is not an object")
                stage["name"] = value
                with self.assertRaisesRegex(PolicyError, "stage.name"):
                    self.load_data(data)

    def test_capture_source_profile_requires_default_string(self) -> None:
        for value in ("production", "", None, False, []):
            with self.subTest(value=value):
                data = self.repository_data()
                capture = data["capture"]
                if not isinstance(capture, dict):
                    self.fail("capture is not an object")
                capture["source_profile"] = value
                with self.assertRaisesRegex(PolicyError, "capture.source_profile"):
                    self.load_data(data)

    def test_private_path_cannot_be_omitted_from_denied_paths(self) -> None:
        data = self.repository_data()
        permissions = data["permissions"]
        if not isinstance(permissions, dict):
            self.fail("permissions is not an object")
        permissions["denied_paths"] = ["another-denied-path/"]

        with self.assertRaisesRegex(PolicyError, "05-Private/"):
            self.load_data(data)

    def test_denied_paths_requires_list_of_non_empty_strings(self) -> None:
        for value in (None, False, "05-Private/", ["05-Private/", None], ["05-Private/", ""]):
            with self.subTest(value=value):
                data = self.repository_data()
                permissions = data["permissions"]
                if not isinstance(permissions, dict):
                    self.fail("permissions is not an object")
                permissions["denied_paths"] = value
                with self.assertRaisesRegex(PolicyError, "permissions.denied_paths"):
                    self.load_data(data)

    def test_briefing_time_requires_strict_24_hour_hh_mm(self) -> None:
        for value in ("9:00", "24:00", "99:99", "", None, False, []):
            with self.subTest(value=value):
                data = self.repository_data()
                briefing = data["briefing"]
                if not isinstance(briefing, dict):
                    self.fail("briefing is not an object")
                briefing["time"] = value
                with self.assertRaisesRegex(PolicyError, "briefing.time"):
                    self.load_data(data)

    def test_briefing_timezone_requires_valid_zoneinfo_name(self) -> None:
        for value in ("Not/A_Zone", "/etc/passwd", "", None, False, []):
            with self.subTest(value=value):
                data = self.repository_data()
                briefing = data["briefing"]
                if not isinstance(briefing, dict):
                    self.fail("briefing is not an object")
                briefing["timezone"] = value
                with self.assertRaisesRegex(PolicyError, "briefing.timezone"):
                    self.load_data(data)

    def test_models_require_exact_configured_aliases(self) -> None:
        aliases = {
            "supervisor": "strong_supervisor",
            "verifier": "strong_verifier",
            "worker": "cheap_worker",
        }
        for key, alias in aliases.items():
            for value in ("provider/model-name", "", None, False, []):
                with self.subTest(key=key, alias=alias, value=value):
                    data = self.repository_data()
                    models = data["models"]
                    if not isinstance(models, dict):
                        self.fail("models is not an object")
                    models[key] = value
                    with self.assertRaisesRegex(PolicyError, f"models.{key}"):
                        self.load_data(data)


class CapturePlannerTests(unittest.TestCase):
    def message(self, **changes):
        values = {"id": 7, "session_id": "session-a", "content": "raw 日本語 content", "timestamp": 12.5, "compacted": False}
        values.update(changes)
        return hermes_supervisor.MessageChange(**values)

    def test_projection_is_frozen_deterministic_and_preserves_raw_source(self) -> None:
        projection = hermes_supervisor.plan_capture(
            self.message(), profile="default", extractor_version="v1"
        )
        same = hermes_supervisor.plan_capture(
            self.message(), profile="default", extractor_version="v1"
        )
        self.assertEqual(projection, same)
        self.assertTrue(projection.idempotency_key.startswith("supervisor-capture:v1:"))
        self.assertIn("Source profile: default", projection.body)
        self.assertIn("Source session: session-a", projection.body)
        self.assertIn("Source message: 7", projection.body)
        self.assertIn("Source timestamp: 12.5", projection.body)
        self.assertIn("Extractor version: v1", projection.body)
        self.assertTrue(projection.body.endswith("raw 日本語 content"))
        with self.assertRaises(FrozenInstanceError):
            projection.title = "changed"  # type: ignore[misc]

    def test_key_domain_separates_every_component_and_rejects_bad_sources(self) -> None:
        base = hermes_supervisor.plan_capture(self.message(), profile="default", extractor_version="v1")
        variants = (
            (self.message(session_id="session-b"), "default", "v1"),
            (self.message(id=8), "default", "v1"),
            (self.message(), "default", "v2"),
        )
        self.assertEqual(len({base.idempotency_key, *(hermes_supervisor.plan_capture(m, profile=p, extractor_version=e).idempotency_key for m, p, e in variants)}), 4)
        for message, profile, extractor in (
            (self.message(session_id=""), "default", "v1"),
            (self.message(id=True), "default", "v1"),
            (self.message(timestamp=float("nan")), "default", "v1"),
            (self.message(), "worker", "v1"),
            (self.message(), "default", ""),
        ):
            with self.subTest(message=message, profile=profile, extractor=extractor):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.plan_capture(message, profile=profile, extractor_version=extractor)

    def test_oversize_and_correction_are_bounded_unresolved_and_surrogate_safe(self) -> None:
        content = "修正: " + "x" * 10000
        projection = hermes_supervisor.plan_capture(
            self.message(session_id="bad\ud800/\n session", content=content),
            profile="default", extractor_version="v1",
        )
        self.assertLessEqual(len(projection.title), 160)
        self.assertLessEqual(len(projection.body), 2048)
        self.assertIn(content[:512], projection.body)
        self.assertNotIn(content[:513], projection.body)
        self.assertIn("verbatim, truncated", projection.body)
        self.assertEqual(projection.relation_kind, "correction_candidate")
        self.assertIsNone(projection.relation_target)
        self.assertIn("unresolved", projection.body)
        self.assertNotIn("/\n session", projection.body)
        projection.title.encode("ascii")
        projection.body.encode("utf-8")


class HermesKanbanClientTests(unittest.TestCase):
    BOARD = "supervisor-test"

    def projection(self, content: str = "hello"):
        return hermes_supervisor.plan_capture(
            hermes_supervisor.MessageChange(7, "s", content, 1.0, False),
            profile="default", extractor_version="v1",
        )

    def production_fixture(self, directory: str) -> Path:
        executable = Path(directory) / "fake hermes"
        executable.write_text(f"#!{sys.executable}\n" + """import json, os, sys, time
mode = os.environ['FIXTURE_MODE']
valid = json.dumps({'id':'task-1','title':'capture','status':'triage','body':None,'assignee':None}, separators=(',', ':')).encode()
if mode == 'sleep':
    time.sleep(2)
elif mode == 'large-stdout':
    sys.stdout.buffer.write(b'x' * 200000)
elif mode == 'large-stderr':
    sys.stderr.buffer.write(b'x' * 200000)
elif mode == 'invalid-stdout':
    sys.stdout.buffer.write(b'\\xff')
elif mode == 'invalid-stderr':
    sys.stdout.buffer.write(valid); sys.stderr.buffer.write(b'\\xff')
else:
    sys.stdout.buffer.write(valid + b' ' * int(os.environ.get('STDOUT_PAD', '0')))
    sys.stderr.buffer.write(b'e' * int(os.environ.get('STDERR_SIZE', '0')))
if os.environ.get('EXIT_NONZERO') == '1':
    raise SystemExit(7)
""", encoding="utf-8")
        executable.chmod(0o700)
        return executable

    def production_client(self, executable: Path, mode: str, **changes):
        values = {
            "output_limit": 256,
            "timeout": 1.0,
            "base_env": {"FIXTURE_MODE": mode},
        }
        values.update(changes)
        return hermes_supervisor.HermesKanbanClient(
            str(executable), self.BOARD, **values
        )

    def test_exact_argv_and_valid_existing_promoted_card(self) -> None:
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                "id": "task-1", "title": argv[3], "status": "running",
                "body": argv[5], "assignee": "builder", "existing": True,
            }), "")
        projection = self.projection("spaces ' \" ; $()\nnext")
        caller_env = {"FIXTURE": "kept", "HERMES_KANBAN_BOARD": "wrong-board"}
        parent_board = os.environ.get("HERMES_KANBAN_BOARD")
        client = hermes_supervisor.HermesKanbanClient(
            "/fixture/hermes", self.BOARD, runner=runner, base_env=caller_env
        )
        card = client.create(projection)
        self.assertEqual(card.id, "task-1")
        self.assertTrue(card.existing)
        self.assertEqual(calls[0][0], [
            "/fixture/hermes", "kanban", "create", projection.title, "--body", projection.body,
            "--triage", "--idempotency-key", projection.idempotency_key,
            "--created-by", "supervisor-capture", "--json",
        ])
        self.assertNotIn("--assignee", calls[0][0])
        self.assertFalse(calls[0][1].get("shell", False))
        self.assertEqual(calls[0][1]["env"]["HERMES_KANBAN_BOARD"], self.BOARD)
        self.assertEqual(calls[0][1]["env"]["FIXTURE"], "kept")
        self.assertIsNot(calls[0][1]["env"], caller_env)
        self.assertEqual(caller_env["HERMES_KANBAN_BOARD"], "wrong-board")
        self.assertEqual(os.environ.get("HERMES_KANBAN_BOARD"), parent_board)
        calls[0][1]["env"]["LEAK_FROM_FIRST_CALL"] = "bad"
        client.create(projection)
        self.assertNotIn("LEAK_FROM_FIRST_CALL", calls[1][1]["env"])
        self.assertIsNot(calls[0][1]["env"], calls[1][1]["env"])

    def test_board_is_required_and_invalid_board_slugs_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            hermes_supervisor.HermesKanbanClient("fake")  # type: ignore[call-arg]
        invalid = (
            None, True, "", "a" * 65, "UPPER", "has space", "../escape",
            "slash/name", "back\\slash", "nul\x00slug", "line\nfeed", "日本語",
            "-leading", "trailing-", "two--dash",
        )
        for board in invalid:
            with self.subTest(board=board):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.HermesKanbanClient(
                        "fake", board, runner=lambda *a, **k: None  # type: ignore[arg-type]
                    )

    def test_production_runner_rejects_substantially_oversized_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = self.production_fixture(directory)
            cases = (
                ("large-stdout", {"FIXTURE_MODE": "large-stdout"}),
                ("large-stderr-zero", {"FIXTURE_MODE": "large-stderr"}),
                ("large-stderr-nonzero", {
                    "FIXTURE_MODE": "large-stderr", "EXIT_NONZERO": "1",
                }),
            )
            for name, environment in cases:
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                        hermes_supervisor.CaptureError, "output.*limit"
                    ) as caught:
                        hermes_supervisor.HermesKanbanClient(
                            str(executable), self.BOARD, output_limit=256,
                            base_env=environment,
                        ).create(self.projection())
                    self.assertLess(len(str(caught.exception)), 100)
                    self.assertNotIn("xxx", str(caught.exception))

    def test_production_runner_enforces_exact_output_boundaries_for_both_streams(self) -> None:
        valid = json.dumps(
            {"id":"task-1", "title":"capture", "status":"triage",
             "body":None, "assignee":None}, separators=(",", ":")
        ).encode()
        with tempfile.TemporaryDirectory() as directory:
            executable = self.production_fixture(directory)
            for stream in ("stdout", "stderr"):
                with self.subTest(stream=stream, boundary="exact"):
                    env = {"FIXTURE_MODE": "valid"}
                    if stream == "stderr":
                        env["STDERR_SIZE"] = str(len(valid))
                    card = hermes_supervisor.HermesKanbanClient(
                        str(executable), self.BOARD, output_limit=len(valid), base_env=env
                    ).create(self.projection())
                    self.assertEqual(card.id, "task-1")
                with self.subTest(stream=stream, boundary="limit-plus-one"):
                    env = {"FIXTURE_MODE": "valid"}
                    if stream == "stdout":
                        env["STDOUT_PAD"] = "1"
                    else:
                        env["STDERR_SIZE"] = str(len(valid) + 1)
                    with self.assertRaisesRegex(hermes_supervisor.CaptureError, "output.*limit"):
                        hermes_supervisor.HermesKanbanClient(
                            str(executable), self.BOARD,
                            output_limit=len(valid), base_env=env,
                        ).create(self.projection())

    def test_production_runner_invalid_utf8_and_timeout_fail_closed_concisely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = self.production_fixture(directory)
            for mode in ("invalid-stdout", "invalid-stderr"):
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(
                        hermes_supervisor.CaptureError, "invalid.*output"
                    ) as caught:
                        self.production_client(executable, mode).create(self.projection())
                    self.assertNotIn("\\xff", str(caught.exception))
            with self.assertRaisesRegex(hermes_supervisor.CaptureError, "TimeoutExpired") as caught:
                self.production_client(executable, "sleep", timeout=0.05).create(self.projection())
            self.assertLess(len(str(caught.exception)), 100)

    def test_production_clients_share_bounded_runner_with_pinned_env(self) -> None:
        observed = {}
        valid = json.dumps({
            "id":"task-1", "title":"capture", "status":"triage",
            "body":None, "assignee":None,
        })

        def run(argv, **kwargs):
            observed.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, valid, "")

        with mock.patch.object(
            hermes_supervisor, "_bounded_subprocess_run", side_effect=run
        ) as bounded:
            card = hermes_supervisor.HermesKanbanClient(
                "fake", self.BOARD, base_env={"FIXTURE": "yes"}
            ).create(self.projection())
        self.assertEqual(card.id, "task-1")
        bounded.assert_called_once()
        self.assertEqual(observed["environment"]["HERMES_KANBAN_BOARD"], self.BOARD)
        self.assertEqual(observed["environment"]["FIXTURE"], "yes")
        self.assertEqual(observed["timeout"], 30.0)
        self.assertEqual(observed["output_limit"], 65536)

    def test_constructor_rejects_invalid_timeout_and_output_limit(self) -> None:
        for timeout in (True, 0, -1, float("inf"), float("nan"), "1", None):
            with self.subTest(timeout=timeout):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.HermesKanbanClient(
                        "fake", self.BOARD, timeout=timeout  # type: ignore[arg-type]
                    )
        for limit in (True, 0, -1, 1.0, "1", None):
            with self.subTest(limit=limit):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.HermesKanbanClient(
                        "fake", self.BOARD, output_limit=limit  # type: ignore[arg-type]
                    )

    def test_rejects_surrogate_object_keys_at_top_level_and_nested(self) -> None:
        valid = {
            "id": "task-1", "title": "capture", "status": "triage",
            "body": None, "assignee": None,
        }
        cases = (
            dict(valid, **{"\ud800": 1}),
            dict(valid, extra={"\ud800": 1}),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                runner = lambda argv, **kwargs: subprocess.CompletedProcess(  # noqa: E731
                    argv, 0, json.dumps(payload), ""
                )
                with self.assertRaisesRegex(hermes_supervisor.CaptureError, "Unicode"):
                    hermes_supervisor.HermesKanbanClient(
                        "fake", self.BOARD, runner=runner
                    ).create(self.projection())

        with self.assertRaisesRegex(hermes_supervisor.CaptureError, "object key"):
            hermes_supervisor._json_depth({1: "value"})

    def test_task_status_is_exact_installed_enum_and_archived_is_unusable(self) -> None:
        valid = {
            "id": "task-1", "title": "capture", "body": None, "assignee": None,
        }
        accepted = (
            "triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done",
        )
        for status in accepted:
            with self.subTest(status=status, accepted=True):
                runner = lambda argv, **kwargs: subprocess.CompletedProcess(  # noqa: E731
                    argv, 0, json.dumps(dict(valid, status=status)), ""
                )
                card = hermes_supervisor.HermesKanbanClient(
                    "fake", self.BOARD, runner=runner
                ).create(self.projection())
                self.assertEqual(card.status, status)

        for status in ("archived", "unknown", "TRIAGE", " triage", "triage ", ""):
            with self.subTest(status=status, accepted=False):
                runner = lambda argv, **kwargs: subprocess.CompletedProcess(  # noqa: E731
                    argv, 0, json.dumps(dict(valid, status=status)), ""
                )
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.HermesKanbanClient(
                        "fake", self.BOARD, runner=runner
                    ).create(self.projection())

    def test_fail_closed_for_runner_and_json_failures(self) -> None:
        valid = {"id":"t", "title":"x", "status":"triage", "body":None, "assignee":None}
        cases = (
            ("nonzero", lambda a, **k: subprocess.CompletedProcess(a, 2, "secret full output", "bad")),
            ("malformed", lambda a, **k: subprocess.CompletedProcess(a, 0, "{", "")),
            ("trailing", lambda a, **k: subprocess.CompletedProcess(a, 0, json.dumps(valid)+"{}", "")),
            ("duplicate", lambda a, **k: subprocess.CompletedProcess(a, 0, '{"id":"a","id":"b","title":"x","status":"triage","body":null,"assignee":null}', "")),
            ("nan", lambda a, **k: subprocess.CompletedProcess(a, 0, '{"id":"a","title":"x","status":NaN,"body":null,"assignee":null}', "")),
            ("surrogate", lambda a, **k: subprocess.CompletedProcess(a, 0, '{"id":"\\ud800","title":"x","status":"triage","body":null,"assignee":null}', "")),
            ("missing-body", lambda a, **k: subprocess.CompletedProcess(a, 0, '{"id":"a","title":"x","status":"triage","assignee":null}', "")),
            ("oversized", lambda a, **k: subprocess.CompletedProcess(a, 0, " " * 70000, "")),
            ("oversized-stderr", lambda a, **k: subprocess.CompletedProcess(a, 0, json.dumps(valid), "x" * 70000)),
            ("deep", lambda a, **k: subprocess.CompletedProcess(a, 0, "[" * 40 + "0" + "]" * 40, "")),
            ("archived", lambda a, **k: subprocess.CompletedProcess(a, 0, json.dumps(dict(valid, status="archived")), "")),
            ("timeout", lambda a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a, 1))),
            ("os", lambda a, **k: (_ for _ in ()).throw(OSError("private path"))),
        )
        for name, runner in cases:
            with self.subTest(name=name):
                with self.assertRaises(hermes_supervisor.CaptureError) as caught:
                    hermes_supervisor.HermesKanbanClient("fake", self.BOARD, runner=runner).create(self.projection())
                self.assertNotIn("secret full output", str(caught.exception))


class PendingBacklogTests(unittest.TestCase):
    def test_reads_exact_pending_in_order_without_live_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, _ = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", [
                    ("s1", "cli", "x", 1, None), ("s2", "cli", "x", 0, None),
                ])
                connection.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", [
                    (2, "s2", "user", "two", 2, 0, 0),
                    (1, "s1", "user", "one", 1, 0, 1),
                ])
            rows = hermes_supervisor.read_pending_messages(state_db, (2, 1))
        self.assertEqual([row.id for row in rows], [1, 2])
        self.assertEqual([row.content for row in rows], ["one", "two"])

    def test_missing_wrong_role_and_malformed_pending_fail_closed(self) -> None:
        for kind in ("missing", "role", "malformed", "session"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                state_db, _ = ChangeDetectionTests.make_databases(directory)
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    if kind != "session":
                        connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", ("s", "cli", "x", 0, None))
                    if kind != "missing":
                        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", (
                            1, "s", "assistant" if kind == "role" else "user",
                            None if kind == "malformed" else "content", 1, 1, 0,
                        ))
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor.read_pending_messages(state_db, (1,))

    def test_pending_snapshot_rolls_back_and_closes_on_success_and_failure(self) -> None:
        original = hermes_supervisor._open_readonly
        for malformed in (False, True):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as directory:
                state_db, _ = ChangeDetectionTests.make_databases(directory)
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", ("s", "cli", "x", 0, None))
                    connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        1, "s", "assistant" if malformed else "user", "content", 1, 1, 0,
                    ))
                class Spy:
                    def __init__(self, connection):
                        self.connection = connection; self.closed = False; self.in_transaction_at_close = None
                    def execute(self, sql, parameters=()): return self.connection.execute(sql, parameters)
                    @property
                    def in_transaction(self): return self.connection.in_transaction
                    def rollback(self): return self.connection.rollback()
                    def close(self):
                        self.in_transaction_at_close = self.connection.in_transaction
                        self.closed = True; self.connection.close()
                spy = Spy(original(state_db))
                with mock.patch.object(hermes_supervisor, "_open_readonly", return_value=spy):
                    if malformed:
                        with self.assertRaises(hermes_supervisor.DetectionError):
                            hermes_supervisor.read_pending_messages(state_db, (1,))
                    else:
                        hermes_supervisor.read_pending_messages(state_db, (1,))
                self.assertTrue(spy.closed)
                self.assertFalse(spy.in_transaction_at_close)


class CaptureServiceTests(unittest.TestCase):
    class Client:
        def __init__(self, fail_on: int | None = None):
            self.calls = []
            self.fail_on = fail_on
        def create(self, projection):
            self.calls.append(projection)
            if self.fail_on == len(self.calls):
                raise hermes_supervisor.CaptureError("injected create failure")
            return hermes_supervisor.CreatedCardRef(
                f"task-{projection.source_message_id}", projection.title, "triage", False
            )

    def fixture(self, directory: str, messages=(), events=()):
        state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
        with closing(sqlite3.connect(state_db)) as connection, connection:
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", ("s", "cli", "x", 0, None))
            connection.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (identifier, "s", role, content, float(identifier), 1, 0)
                for identifier, role, content in messages
            ])
        with closing(sqlite3.connect(kanban_db)) as connection, connection:
            connection.executemany("INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)", [
                (identifier, "task", None, kind, "{}", identifier)
                for identifier, kind in events
            ])
        return state_db, kanban_db

    def test_running_and_paused_capture_then_second_run_is_noop(self) -> None:
        for control in ("running", "paused"):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as directory:
                state_db, kanban_db = self.fixture(directory, [(1, "user", "intent"), (2, "assistant", "tail")])
                store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
                store.initialize()
                if control == "paused":
                    store.control("pause")
                client = self.Client()
                service = hermes_supervisor.CaptureService(client)
                first = service.run_once(store, state_db, kanban_db)
                second = service.run_once(store, state_db, kanban_db)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual([card.id for card in first.cards], ["task-1"])
                self.assertEqual(second.cards, ())
                self.assertEqual(second.state.last_message_id, 2)

    def test_frozen_observes_backlog_then_resume_projects_it_and_emergency_does_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, [(1, "user", "frozen intent")])
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize()
            store.control("freeze")
            client = self.Client()
            service = hermes_supervisor.CaptureService(client)
            observed = service.run_once(store, state_db, kanban_db)
            self.assertEqual(client.calls, [])
            self.assertEqual(observed.state.pending_message_ids, (1,))
            store.control("resume")
            captured = service.run_once(store, state_db, kanban_db)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(captured.state.pending_message_ids, ())
            store.control("emergency-stop")
            before = store.read()
            stopped = service.run_once(store, state_db, kanban_db)
            self.assertEqual(stopped.state, before)
            self.assertEqual(len(client.calls), 1)

    def test_create_failure_commits_earlier_only_and_preserves_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory, [(1, "user", "one"), (2, "user", "two")], [(1, "blocked")]
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize()
            client = self.Client(fail_on=2)
            with self.assertRaises(hermes_supervisor.CaptureError):
                hermes_supervisor.CaptureService(client).run_once(store, state_db, kanban_db)
            state = store.read()
            self.assertEqual(state.last_message_id, 1)
            self.assertEqual(state.last_event_id, 0)
            self.assertEqual(state.pending_event_ids, ())

    def test_events_advance_without_growing_legacy_pending_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, [], [(1, "blocked")])
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.write(replace(hermes_supervisor.initial_supervisor_state(), pending_event_ids=(), last_event_id=0))
            result = hermes_supervisor.CaptureService(self.Client()).run_once(store, state_db, kanban_db)
            self.assertEqual(result.state.pending_event_ids, ())
            self.assertEqual(result.state.last_event_id, 1)
            again = hermes_supervisor.CaptureService(self.Client()).run_once(store, state_db, kanban_db)
            self.assertEqual(again.state.pending_event_ids, ())

    def test_capture_drains_bounded_message_and_event_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            messages = [(i, "user", f"intent-{i}") for i in range(1, 131)]
            events = [(i, "blocked") for i in range(1, 514)]
            state_db, kanban_db = self.fixture(directory, messages, events)
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            client = self.Client(); service = hermes_supervisor.CaptureService(client)
            first = service.run_once(store, state_db, kanban_db)
            second = service.run_once(store, state_db, kanban_db)
            third = service.run_once(store, state_db, kanban_db)
            self.assertEqual([len(first.cards), len(second.cards), len(third.cards)], [64, 64, 2])
            self.assertEqual([first.state.last_message_id, second.state.last_message_id,
                              third.state.last_message_id], [64, 128, 130])
            self.assertEqual([first.state.last_event_id, second.state.last_event_id,
                              third.state.last_event_id], [256, 512, 513])
            self.assertEqual([call.source_message_id for call in client.calls], list(range(1, 131)))
            self.assertEqual(third.state.pending_event_ids, ())

    def test_capture_total_message_bytes_truncate_then_drain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chunk = "x" * 60_000
            state_db, kanban_db = self.fixture(
                directory, [(i, "user", chunk) for i in range(1, 11)]
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            client = self.Client(); service = hermes_supervisor.CaptureService(client)
            first = service.run_once(store, state_db, kanban_db)
            second = service.run_once(store, state_db, kanban_db)
            self.assertEqual((len(first.cards), first.state.last_message_id), (8, 8))
            self.assertEqual((len(second.cards), second.state.last_message_id), (2, 10))

    def test_frozen_capture_records_ids_without_reading_raw_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, [(1, "user", "secret")], [(1, "blocked")])
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze")
            original_open = hermes_supervisor._open_readonly
            def guarded_open(path):
                connection = original_open(path)
                denied = {("messages", "content"),
                          ("task_events", "payload"), ("task_events", "task_id"),
                          ("task_events", "run_id")}
                connection.set_authorizer(lambda action, table, column, db, trigger:
                    sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and (table, column) in denied
                    else sqlite3.SQLITE_OK)
                return connection
            with mock.patch.object(hermes_supervisor, "_open_readonly", side_effect=guarded_open):
                changes = hermes_supervisor.detect_capture_changes(
                    state_db, kanban_db, profile="default", last_message_id=0,
                    last_event_id=0, frozen=True, frozen_capacity=2,
                )
                result = hermes_supervisor.CaptureService(self.Client()).run_once(
                    store, state_db, kanban_db
                )
            self.assertEqual(changes.messages, (
                hermes_supervisor.MessageChange(1, "capture-redacted", "", 1.0, False),
            ))
            self.assertEqual(result.state.pending_message_ids, (1,))
            self.assertEqual(result.state.pending_event_ids, (1,))

    def test_frozen_archived_user_is_ignored_and_resume_does_not_wedge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("archived", "cli", "old", 1, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "archived", "user", "old intent", 1.0, 1, 0),
                )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze")
            client = self.Client(); service = hermes_supervisor.CaptureService(client)

            frozen = service.run_once(store, state_db, kanban_db)
            store.control("resume")
            resumed = service.run_once(store, state_db, kanban_db)

            self.assertEqual(frozen.state.last_message_id, 1)
            self.assertEqual(frozen.state.pending_message_ids, ())
            self.assertEqual(resumed.cards, ())
            self.assertEqual(resumed.state.last_message_id, 1)
            self.assertEqual(client.calls, [])

    def test_frozen_orphan_user_fails_closed_without_state_or_client_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "missing", "user", "orphan", 1.0, 1, 0),
                )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze")
            before = store.path.read_bytes(); client = self.Client()

            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.CaptureService(client).run_once(store, state_db, kanban_db)

            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(client.calls, [])

    def test_frozen_event_only_cycle_records_full_256_event_share(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory, events=[(i, "blocked") for i in range(1, 301)]
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze")
            client = self.Client()

            result = hermes_supervisor.CaptureService(client).run_once(
                store, state_db, kanban_db
            )

            self.assertEqual(len(result.state.pending_event_ids), 256)
            self.assertEqual(result.state.pending_event_ids, tuple(range(1, 257)))
            self.assertEqual(result.state.last_event_id, 256)
            self.assertEqual(client.calls, [])

    def test_frozen_event_cycles_stop_exactly_at_combined_pending_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory,
                events=[
                    (i, "blocked")
                    for i in range(1, hermes_supervisor._CAPTURE_PENDING_ID_CAP + 3)
                ],
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze")
            client = self.Client(); service = hermes_supervisor.CaptureService(client)

            for _ in range(8):
                result = service.run_once(store, state_db, kanban_db)
            before = store.path.read_bytes()
            stopped = service.run_once(store, state_db, kanban_db)

            self.assertEqual(len(result.state.pending_event_ids),
                             hermes_supervisor._CAPTURE_PENDING_ID_CAP)
            self.assertEqual(result.state.last_event_id,
                             hermes_supervisor._CAPTURE_PENDING_ID_CAP)
            self.assertLess(len(before), hermes_supervisor._STATE_JSON_MAX_BYTES)
            self.assertEqual(stopped.state, result.state)
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(client.calls, [])

    def test_frozen_mixed_capacity_allocates_events_after_messages_without_cursor_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory,
                messages=[(i, "user", f"intent-{i}") for i in range(1, 11)],
                events=[(i, "blocked") for i in range(1, 101)],
            )

            first = hermes_supervisor.detect_capture_changes(
                state_db, kanban_db, profile="default", last_message_id=0,
                last_event_id=0, frozen=True, frozen_capacity=100,
            )
            second = hermes_supervisor.detect_capture_changes(
                state_db, kanban_db, profile="default",
                last_message_id=first.proposed_message_id,
                last_event_id=first.proposed_event_id,
                frozen=True, frozen_capacity=100,
            )

            self.assertEqual([message.id for message in first.messages], list(range(1, 11)))
            self.assertEqual([event.id for event in first.events], list(range(1, 91)))
            self.assertEqual(first.proposed_event_id, 90)
            self.assertEqual([event.id for event in second.events], list(range(91, 101)))
            self.assertEqual(second.proposed_event_id, 100)

    def test_capture_limits_and_frozen_capacity_reject_hostile_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            cases = (
                ("message_limit", True), ("message_limit", -1),
                ("message_limit", hermes_supervisor._CAPTURE_MAX_MESSAGES + 1),
                ("event_limit", True), ("event_limit", -1),
                ("event_limit", hermes_supervisor._CAPTURE_MAX_EVENTS + 1),
                ("frozen_capacity", True), ("frozen_capacity", -1),
                ("frozen_capacity", hermes_supervisor._CAPTURE_PENDING_ID_CAP + 1),
            )
            for field, value in cases:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(hermes_supervisor.DetectionError):
                        hermes_supervisor.detect_capture_changes(
                            state_db, kanban_db, profile="default", last_message_id=0,
                            last_event_id=0, frozen=True, **{field: value},
                        )

    def test_oversized_capture_message_fails_before_raw_fetch_and_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory, [(1, "user", "x" * (hermes_supervisor._CAPTURE_CONTENT_MAX_BYTES + 1))]
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); before = store.path.read_bytes(); client = self.Client()
            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.CaptureService(client).run_once(store, state_db, kanban_db)
            self.assertEqual(client.calls, [])
            self.assertEqual(store.path.read_bytes(), before)

    def test_frozen_pending_cap_stops_without_cursor_or_state_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 's', 'user', '', ?, 1, 0)",
                    ((i, i) for i in range(1, hermes_supervisor._CAPTURE_PENDING_ID_CAP + 2)),
                )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.initialize(); store.control("freeze"); service = hermes_supervisor.CaptureService(self.Client())
            for _ in range(40):
                result = service.run_once(store, state_db, kanban_db)
                if len(result.state.pending_message_ids) == hermes_supervisor._CAPTURE_PENDING_ID_CAP:
                    break
            full = store.read(); before = store.path.read_bytes()
            stopped = service.run_once(store, state_db, kanban_db)
            self.assertEqual(len(full.pending_message_ids), hermes_supervisor._CAPTURE_PENDING_ID_CAP)
            self.assertLess(len(before), hermes_supervisor._STATE_JSON_MAX_BYTES)
            self.assertEqual(stopped.state, full)
            self.assertEqual(store.path.read_bytes(), before)

            store.control("resume")
            client = self.Client(); service = hermes_supervisor.CaptureService(client)
            first_resume = service.run_once(store, state_db, kanban_db)
            self.assertEqual(len(first_resume.cards), hermes_supervisor._CAPTURE_MAX_MESSAGES)
            self.assertEqual(len(first_resume.state.pending_message_ids),
                             hermes_supervisor._CAPTURE_PENDING_ID_CAP - hermes_supervisor._CAPTURE_MAX_MESSAGES)
            self.assertNotIn(2049, [call.source_message_id for call in client.calls])
            for _ in range(40):
                drained = service.run_once(store, state_db, kanban_db)
                if not drained.state.pending_message_ids and drained.state.last_message_id == 2049:
                    break
            self.assertEqual([call.source_message_id for call in client.calls], list(range(1, 2050)))
            self.assertEqual(store.read().pending_message_ids, ())

    def test_pending_messages_resume_in_ascending_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(
                directory, [(1, "user", "one"), (2, "user", "two")]
            )
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            store.write(replace(
                hermes_supervisor.initial_supervisor_state(), last_message_id=2,
                pending_message_ids=(2, 1),
            ))
            client = self.Client()
            result = hermes_supervisor.CaptureService(client).run_once(store, state_db, kanban_db)
            self.assertEqual([call.source_message_id for call in client.calls], [1, 2])
            self.assertEqual(result.state.pending_message_ids, ())

    def test_batch_cursor_sees_event_after_capture_clears_legacy_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, [], [(1, "blocked")])
            store = hermes_supervisor.StateStore(Path(directory) / "supervisor.json")
            state = store.initialize()
            store.write(replace(state, pending_event_ids=(1,), last_event_id=1))

            captured = hermes_supervisor.CaptureService(self.Client()).run_once(
                store, state_db, kanban_db
            )
            batch = hermes_supervisor.detect_batch_changes(
                state_db, kanban_db, profile="default", last_message_id=0, last_event_id=0
            )

            self.assertEqual(captured.state.pending_event_ids, ())
            self.assertEqual([event.id for event in batch.events], [1])


class CaptureFakeBinaryE2ETests(unittest.TestCase):
    def setup_fixture(self, directory: str, content: str):
        state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
        with closing(sqlite3.connect(state_db)) as connection, connection:
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", ("s", "cli", "x", 0, None))
            connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)", (1, "s", "user", content, 1, 1, 0))
        fake = Path(directory) / "hermes"
        fake.write_text(f"#!{sys.executable}\n" + """import json, os, sys
log = os.environ['FAKE_LOG']; mapping_path = os.environ['FAKE_MAP']
selector_path = os.environ['FAKE_SELECTOR']
board = os.environ['HERMES_KANBAN_BOARD']
try:
    with open(selector_path, encoding='utf-8') as stream: selector = stream.read()
except FileNotFoundError:
    selector = 'current-board'
with open(log, 'a', encoding='utf-8') as stream:
    stream.write(json.dumps({'argv': sys.argv[1:], 'board': board, 'selector': selector}, ensure_ascii=True) + '\\n')
with open(selector_path, 'w', encoding='utf-8') as stream:
    stream.write('switched-board')
args = sys.argv[1:]
if args[:2] != ['kanban', 'create'] or '--triage' not in args or '--json' not in args:
    raise SystemExit(2)
key = args[args.index('--idempotency-key') + 1]
title = args[2]; body = args[args.index('--body') + 1]
try:
    with open(mapping_path, encoding='utf-8') as stream: boards = json.load(stream)
except FileNotFoundError: boards = {}
mapping = boards.setdefault(board, {})
existing = key in mapping
if not existing:
    mapping[key] = {'id': board + '-fixture-' + str(len(mapping) + 1), 'title': title, 'status': 'triage', 'body': body, 'assignee': None}
    with open(mapping_path, 'w', encoding='utf-8') as stream: json.dump(boards, stream, ensure_ascii=True)
task = dict(mapping[key]); task['existing'] = existing
print(json.dumps(task, ensure_ascii=True))
""", encoding="utf-8")
        fake.chmod(0o700)
        return state_db, kanban_db, fake, Path(directory) / "argv.jsonl", Path(directory) / "cards.json"

    def test_multi_message_cycle_stays_on_pinned_board_with_argv_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "shell-was-run"
            content = f"spaces ' \" ; $(touch {marker})\nnext"
            state_db, kanban_db, fake, log, mapping = self.setup_fixture(directory, content)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (2, "s", "user", "second intent", 2, 1, 0),
                )
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            selector = Path(directory) / "current-selector"
            base_env = {
                "FAKE_LOG": str(log), "FAKE_MAP": str(mapping),
                "FAKE_SELECTOR": str(selector),
            }
            service = hermes_supervisor.CaptureService(
                hermes_supervisor.HermesKanbanClient(
                    str(fake), "supervisor-test", base_env=base_env
                )
            )
            first = service.run_once(store, state_db, kanban_db)
            second = service.run_once(store, state_db, kanban_db)
            invocations = [json.loads(line) for line in log.read_text().splitlines()]
            boards = json.loads(mapping.read_text())
            self.assertEqual(len(invocations), 2)
            self.assertEqual([call["board"] for call in invocations], ["supervisor-test"] * 2)
            self.assertEqual([call["selector"] for call in invocations], [
                "current-board", "switched-board",
            ])
            self.assertEqual(len(boards["supervisor-test"]), 2)
            self.assertNotIn("switched-board", boards)
            self.assertEqual(len(first.cards), 2)
            self.assertEqual(second.cards, ())
            first_argv = invocations[0]["argv"]
            self.assertIn(content, first_argv[first_argv.index("--body") + 1])
            self.assertFalse(marker.exists())
            self.assertNotIn("--assignee", first_argv)
            self.assertEqual(base_env.get("HERMES_KANBAN_BOARD"), None)

    def test_state_write_crash_retries_same_key_and_fake_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, fake, log, mapping = self.setup_fixture(directory, "crash window")
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            store.initialize()
            selector = Path(directory) / "current-selector"
            service = hermes_supervisor.CaptureService(
                hermes_supervisor.HermesKanbanClient(
                    str(fake), "supervisor-test", base_env={
                        "FAKE_LOG": str(log), "FAKE_MAP": str(mapping),
                        "FAKE_SELECTOR": str(selector),
                    },
                )
            )
            with mock.patch.object(store, "_write_unlocked", side_effect=OSError("injected before replace")):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    service.run_once(store, state_db, kanban_db)
            retried = service.run_once(store, state_db, kanban_db)
            invocations = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(invocations), 2)
            first_argv, second_argv = invocations[0]["argv"], invocations[1]["argv"]
            first_key = first_argv[first_argv.index("--idempotency-key") + 1]
            second_key = second_argv[second_argv.index("--idempotency-key") + 1]
            self.assertEqual(first_key, second_key)
            self.assertEqual([call["board"] for call in invocations], ["supervisor-test"] * 2)
            self.assertEqual([call["selector"] for call in invocations], [
                "current-board", "switched-board",
            ])
            boards = json.loads(mapping.read_text())
            self.assertEqual(len(boards["supervisor-test"]), 1)
            self.assertNotIn("switched-board", boards)
            self.assertTrue(retried.cards[0].existing)
            only_card = next(iter(boards["supervisor-test"].values()))
            self.assertEqual(retried.cards[0].id, only_card["id"])


class Stage0GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY)
        self.now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

    def test_manually_constructed_schema1_state_is_rejected_by_gate(self) -> None:
        state = replace(hermes_supervisor.initial_supervisor_state(), schema_version=1)
        with self.assertRaises(hermes_supervisor.GateError):
            hermes_supervisor.decide_gate(
                self.policy, state, hermes_supervisor.GateRequest("supervisor_run"), self.now
            )

    def test_supervisor_run_reserves_exactly_one_slot_and_models_are_frozen(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 11, 4, 1),
        )
        request = hermes_supervisor.GateRequest("supervisor_run")

        decision = hermes_supervisor.decide_gate(self.policy, state, request, self.now)

        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_code, "supervisor_run_allowed")
        self.assertEqual(
            decision.effective_budget,
            hermes_supervisor.DailyBudget("2026-07-22", 12, 4, 1),
        )
        self.assertIsNone(decision.next_primary_goal_id)
        self.assertEqual(state.daily_budget.supervisor_runs, 11)
        for value in (request, decision):
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    value.kind = "dispatch_child"  # type: ignore[attr-defined,misc]

    def test_bootstrap_accepts_one_primary_and_schedules_unrelated_goal(self) -> None:
        initial = hermes_supervisor.initial_supervisor_state()
        accepted = hermes_supervisor.decide_gate(
            self.policy,
            initial,
            hermes_supervisor.GateRequest("activate_primary_goal", goal_id="goal-a"),
            self.now,
        )
        same = hermes_supervisor.decide_gate(
            self.policy,
            replace(initial, last_accepted_primary_goal_id="goal-a"),
            hermes_supervisor.GateRequest("activate_primary_goal", goal_id="goal-a"),
            self.now,
        )
        unrelated = hermes_supervisor.decide_gate(
            self.policy,
            replace(initial, last_accepted_primary_goal_id="goal-a"),
            hermes_supervisor.GateRequest("activate_primary_goal", goal_id="goal-b"),
            self.now,
        )

        self.assertEqual((accepted.action, accepted.reason_code), ("allow", "primary_goal_accepted"))
        self.assertEqual((same.action, same.reason_code), ("allow", "primary_goal_reused"))
        self.assertEqual(accepted.next_primary_goal_id, "goal-a")
        self.assertEqual(same.next_primary_goal_id, "goal-a")
        self.assertEqual(
            (unrelated.action, unrelated.reason_code, unrelated.next_primary_goal_id),
            ("schedule", "bootstrap_primary_goal_limit", "goal-a"),
        )
        self.assertEqual(
            unrelated.effective_budget,
            hermes_supervisor.DailyBudget("2026-07-22", 0, 0, 0),
        )

    def test_safety_and_data_loss_goals_preempt_with_data_loss_precedence(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="normal",
        )
        cases = (
            ({"safety_critical": True}, "safety_primary_goal_preemption"),
            ({"data_loss_risk": True}, "data_loss_primary_goal_preemption"),
            (
                {"safety_critical": True, "data_loss_risk": True},
                "data_loss_primary_goal_preemption",
            ),
        )
        for flags, reason in cases:
            with self.subTest(flags=flags):
                decision = hermes_supervisor.decide_gate(
                    self.policy,
                    state,
                    hermes_supervisor.GateRequest(
                        "activate_primary_goal", goal_id="urgent", **flags
                    ),
                    self.now,
                )
                self.assertEqual(
                    (decision.action, decision.reason_code, decision.next_primary_goal_id),
                    ("allow", reason, "urgent"),
                )

    def test_third_child_worker_and_exact_paid_cap_are_reserved(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
            daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 3, 5, 1),
        )
        decision = hermes_supervisor.decide_gate(
            self.policy,
            state,
            hermes_supervisor.GateRequest(
                "dispatch_child",
                goal_id="goal",
                active_worker_count=2,
                paid_worker_usd=1,
            ),
            self.now,
        )

        self.assertEqual(
            (decision.action, decision.reason_code), ("allow", "dispatch_allowed")
        )
        self.assertEqual(
            decision.effective_budget,
            hermes_supervisor.DailyBudget("2026-07-22", 3, 6, 2),
        )
        self.assertEqual(decision.next_primary_goal_id, "goal")
        self.assertEqual(
            state.daily_budget,
            hermes_supervisor.DailyBudget("2026-07-22", 3, 5, 1),
        )

    def test_running_safe_card_continues_without_consuming_exhausted_budget(self) -> None:
        budget = hermes_supervisor.DailyBudget("2026-07-22", 12, 6, 2)
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            daily_budget=budget,
            last_accepted_primary_goal_id="goal",
        )
        decision = hermes_supervisor.decide_gate(
            self.policy,
            state,
            hermes_supervisor.GateRequest(
                "continue_running", goal_id="goal", active_worker_count=3, paid_worker_usd=2
            ),
            self.now,
        )

        self.assertEqual(
            (decision.action, decision.reason_code),
            ("allow", "running_work_continues"),
        )
        self.assertEqual(decision.effective_budget, budget)
        self.assertEqual(decision.next_primary_goal_id, "goal")

    def test_running_work_continues_across_tokyo_date_rollover_without_reservation(self) -> None:
        old_budget = hermes_supervisor.DailyBudget("2026-07-22", 12, 6, 2)
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            control_state="running",
            daily_budget=old_budget,
            last_accepted_primary_goal_id="goal",
        )

        decision = hermes_supervisor.decide_gate(
            self.policy,
            state,
            hermes_supervisor.GateRequest(
                "continue_running", goal_id="goal", active_worker_count=3, paid_worker_usd=2
            ),
            datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            (decision.action, decision.reason_code),
            ("allow", "running_work_continues"),
        )
        self.assertEqual(
            decision.effective_budget,
            hermes_supervisor.DailyBudget("2026-07-23", 0, 0, 0),
        )
        self.assertEqual(decision.next_primary_goal_id, "goal")
        self.assertEqual(state.daily_budget, old_budget)
        self.assertEqual(state.last_accepted_primary_goal_id, "goal")

    def test_tokyo_midnight_resets_old_budget_but_future_date_fails_closed(self) -> None:
        exhausted = replace(
            hermes_supervisor.initial_supervisor_state(),
            daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 12, 6, 2),
        )
        before = hermes_supervisor.decide_gate(
            self.policy,
            exhausted,
            hermes_supervisor.GateRequest("supervisor_run"),
            datetime(2026, 7, 22, 14, 59, tzinfo=timezone.utc),
        )
        after = hermes_supervisor.decide_gate(
            self.policy,
            exhausted,
            hermes_supervisor.GateRequest("supervisor_run"),
            datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc),
        )
        future_state = replace(
            exhausted,
            daily_budget=hermes_supervisor.DailyBudget("2026-07-24", 1, 2, 1),
        )
        rollback = hermes_supervisor.decide_gate(
            self.policy,
            future_state,
            hermes_supervisor.GateRequest("supervisor_run"),
            datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual((before.action, before.reason_code), ("schedule", "supervisor_daily_limit"))
        self.assertEqual(after.effective_budget, hermes_supervisor.DailyBudget("2026-07-23", 1, 0, 0))
        self.assertEqual((after.action, after.reason_code), ("allow", "supervisor_run_allowed"))
        self.assertEqual((rollback.action, rollback.reason_code), ("needs_human", "budget_clock_rollback"))
        self.assertEqual(rollback.effective_budget, future_state.daily_budget)

    def test_malformed_requests_policy_state_and_naive_time_are_rejected(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
        )
        malformed_requests = (
            hermes_supervisor.GateRequest("unknown"),
            hermes_supervisor.GateRequest(True),
            hermes_supervisor.GateRequest("dispatch_child", goal_id=None),
            hermes_supervisor.GateRequest("dispatch_child", goal_id=""),
            hermes_supervisor.GateRequest("dispatch_child", goal_id=7),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", active_worker_count=True),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", active_worker_count=-1),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", active_worker_count=1.0),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", paid_worker_usd=True),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", paid_worker_usd=-1),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", paid_worker_usd=0.5),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal", paid_worker_usd=float("inf")),
            hermes_supervisor.GateRequest("supervisor_run", safety_critical=1),
            hermes_supervisor.GateRequest("supervisor_run", data_loss_risk="yes"),
        )
        for request in malformed_requests:
            with self.subTest(request=request):
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(self.policy, state, request, self.now)

        bad_policies = (
            replace(self.policy, stage=replace(self.policy.stage, name="production")),
            replace(self.policy, stage=replace(self.policy.stage, active_goal_limit=2)),
            replace(
                self.policy,
                scheduling=replace(self.policy.scheduling, worker_concurrency=0),
            ),
            replace(
                self.policy,
                scheduling=replace(self.policy.scheduling, daily_dispatch_limit=True),
            ),
            replace(
                self.policy,
                scheduling=replace(self.policy.scheduling, worker_concurrency=3.0),
            ),
            replace(
                self.policy,
                budget=replace(self.policy.budget, paid_worker_soft_limit_usd=-1),
            ),
            replace(self.policy, briefing=replace(self.policy.briefing, timezone="bad/zone")),
        )
        for policy in bad_policies:
            with self.subTest(policy=policy):
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(
                        policy, state, hermes_supervisor.GateRequest("supervisor_run"), self.now
                    )

        bad_states = (
            replace(state, mode="unsafe"),
            replace(state, control_state="unknown"),
            replace(state, daily_budget=hermes_supervisor.DailyBudget("bad", 0, 0, 0)),
            replace(state, daily_budget=hermes_supervisor.DailyBudget(None, True, 0, 0)),
            replace(state, last_accepted_primary_goal_id=""),
        )
        for bad_state in bad_states:
            with self.subTest(state=bad_state):
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(
                        self.policy,
                        bad_state,
                        hermes_supervisor.GateRequest("supervisor_run"),
                        self.now,
                    )
        with self.assertRaises(hermes_supervisor.GateError):
            hermes_supervisor.decide_gate(
                self.policy,
                state,
                hermes_supervisor.GateRequest("supervisor_run"),
                datetime(2026, 7, 22, 12, 0),
            )

    def test_now_timezone_failure_is_concise_gate_error_with_cause(self) -> None:
        failure = RuntimeError("hostile timezone")

        class RaisingTimezone(tzinfo):
            def utcoffset(self, value):
                raise failure

        with self.assertRaises(hermes_supervisor.GateError) as caught:
            hermes_supervisor.decide_gate(
                self.policy,
                hermes_supervisor.initial_supervisor_state(),
                hermes_supervisor.GateRequest("supervisor_run"),
                datetime(2026, 7, 22, 12, 0, tzinfo=RaisingTimezone()),
            )

        self.assertEqual(str(caught.exception), "now: invalid timezone value")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertNotIn("Traceback", str(caught.exception))

    def test_now_timezone_failure_during_normalization_is_gate_error(self) -> None:
        failure = RuntimeError("hostile timezone retry")

        class StatefulTimezone(tzinfo):
            calls = 0

            def utcoffset(self, value):
                self.calls += 1
                if self.calls > 1:
                    raise failure
                return timedelta(0)

        with self.assertRaises(hermes_supervisor.GateError) as caught:
            hermes_supervisor.decide_gate(
                self.policy,
                hermes_supervisor.initial_supervisor_state(),
                hermes_supervisor.GateRequest("supervisor_run"),
                datetime(2026, 7, 22, 12, 0, tzinfo=StatefulTimezone()),
            )

        self.assertEqual(str(caught.exception), "now: invalid timezone value")
        self.assertIs(caught.exception.__cause__, failure)

    def test_gate_revalidates_exact_nested_policy_models_and_all_fields(self) -> None:
        state = hermes_supervisor.initial_supervisor_state()
        request = hermes_supervisor.GateRequest("supervisor_run")

        class PolicySubclass(hermes_supervisor.Policy):
            pass

        subclass_policy = PolicySubclass(
            self.policy.stage,
            self.policy.scheduling,
            self.policy.budget,
            self.policy.capture,
            self.policy.permissions,
            self.policy.briefing,
            self.policy.retention,
            self.policy.models,
        )
        for malformed in (object(), subclass_policy):
            with self.subTest(contract="policy-model", kind=type(malformed).__name__):
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(
                        malformed, state, request, self.now  # type: ignore[arg-type]
                    )

        for field in (
            "stage", "scheduling", "budget", "capture", "permissions", "briefing",
            "retention", "models",
        ):
            with self.subTest(contract="nested-model", field=field):
                malformed = replace(self.policy, **{field: None})
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(malformed, state, request, self.now)

        malformed_fields = (
            ("stage-name-type", replace(
                self.policy, stage=replace(self.policy.stage, name=True)
            )),
            ("active-goal-bool", replace(
                self.policy, stage=replace(self.policy.stage, active_goal_limit=True)
            )),
            ("active-goal-float", replace(
                self.policy, stage=replace(self.policy.stage, active_goal_limit=1.0)
            )),
            *( (
                f"scheduling-positive-{field}",
                replace(
                    self.policy,
                    scheduling=replace(self.policy.scheduling, **{field: 0}),
                ),
            ) for field in (
                "worker_concurrency", "daily_dispatch_limit", "daily_supervisor_limit",
                "task_runtime_seconds", "watcher_interval_seconds", "batch_cooldown_seconds",
            ) ),
            *( (
                f"scheduling-nonnegative-{field}",
                replace(
                    self.policy,
                    scheduling=replace(self.policy.scheduling, **{field: -1}),
                ),
            ) for field in (
                "normal_retry_limit", "replan_limit", "model_escalation_limit",
            ) ),
            ("budget-bool", replace(
                self.policy,
                budget=replace(self.policy.budget, paid_worker_soft_limit_usd=True),
            )),
            ("capture-type", replace(
                self.policy, capture=replace(self.policy.capture, source_profile=True)
            )),
            ("capture-value", replace(
                self.policy, capture=replace(self.policy.capture, source_profile="worker")
            )),
            ("permissions-list", replace(
                self.policy,
                permissions=hermes_supervisor.PermissionsPolicy(
                    ["05-Private/"]  # type: ignore[arg-type]
                ),
            )),
            ("permissions-missing-private", replace(
                self.policy,
                permissions=hermes_supervisor.PermissionsPolicy(("other/",)),
            )),
            ("permissions-empty-path", replace(
                self.policy,
                permissions=hermes_supervisor.PermissionsPolicy(("05-Private/", "")),
            )),
            ("permissions-surrogate", replace(
                self.policy,
                permissions=hermes_supervisor.PermissionsPolicy(("05-Private/", "\ud800")),
            )),
            ("briefing-time-bool", replace(
                self.policy, briefing=replace(self.policy.briefing, time=True)
            )),
            ("briefing-time-format", replace(
                self.policy, briefing=replace(self.policy.briefing, time="9:00")
            )),
            ("briefing-timezone-bool", replace(
                self.policy, briefing=replace(self.policy.briefing, timezone=True)
            )),
            ("briefing-timezone-value", replace(
                self.policy, briefing=replace(self.policy.briefing, timezone="bad/zone")
            )),
            ("retention-bool", replace(
                self.policy, retention=replace(self.policy.retention, event_days=True)
            )),
            ("retention-zero", replace(
                self.policy, retention=replace(self.policy.retention, event_days=0)
            )),
            ("models-supervisor", replace(
                self.policy, models=replace(self.policy.models, supervisor=True)
            )),
            ("models-verifier", replace(
                self.policy, models=replace(self.policy.models, verifier="other")
            )),
            ("models-worker", replace(
                self.policy, models=replace(self.policy.models, worker="other")
            )),
        )
        for name, malformed in malformed_fields:
            with self.subTest(contract="field", name=name):
                with self.assertRaises(hermes_supervisor.GateError):
                    hermes_supervisor.decide_gate(malformed, state, request, self.now)

        valid = hermes_supervisor.decide_gate(self.policy, state, request, self.now)
        self.assertEqual((valid.action, valid.reason_code), ("allow", "supervisor_run_allowed"))

    def test_non_running_controls_block_new_dispatch_and_continuation(self) -> None:
        base = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
        )
        controls = (
            ("paused", "schedule", "control_paused"),
            ("frozen", "schedule", "control_frozen"),
            ("emergency_stopped", "needs_human", "emergency_stop_active"),
        )
        for control, action, reason in controls:
            for kind in ("dispatch_child", "continue_running"):
                with self.subTest(control=control, kind=kind):
                    decision = hermes_supervisor.decide_gate(
                        self.policy,
                        replace(base, control_state=control),
                        hermes_supervisor.GateRequest(kind, goal_id="goal"),
                        self.now,
                    )
                    self.assertEqual((decision.action, decision.reason_code), (action, reason))
                    self.assertEqual(decision.next_primary_goal_id, "goal")

    def test_dispatch_gate_order_limits_and_emergency_budget_escalation(self) -> None:
        base = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
            daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 6, 2),
        )
        cases = (
            (
                base,
                hermes_supervisor.GateRequest(
                    "dispatch_child",
                    goal_id="other",
                    active_worker_count=3,
                    paid_worker_usd=1,
                    safety_critical=True,
                    data_loss_risk=True,
                ),
                "schedule",
                "bootstrap_primary_goal_limit",
            ),
            (
                base,
                hermes_supervisor.GateRequest(
                    "dispatch_child", goal_id="goal", active_worker_count=3, paid_worker_usd=1
                ),
                "schedule",
                "worker_concurrency_limit",
            ),
            (
                base,
                hermes_supervisor.GateRequest("dispatch_child", goal_id="goal"),
                "schedule",
                "daily_dispatch_limit",
            ),
            (
                replace(base, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 5, 2)),
                hermes_supervisor.GateRequest(
                    "dispatch_child", goal_id="goal", paid_worker_usd=1
                ),
                "schedule",
                "paid_worker_soft_limit",
            ),
            (
                base,
                hermes_supervisor.GateRequest(
                    "dispatch_child",
                    goal_id="goal",
                    active_worker_count=3,
                    safety_critical=True,
                ),
                "needs_human",
                "safety_budget_override_required",
            ),
            (
                base,
                hermes_supervisor.GateRequest(
                    "dispatch_child", goal_id="goal", data_loss_risk=True
                ),
                "needs_human",
                "data_loss_budget_override_required",
            ),
            (
                replace(base, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 5, 2)),
                hermes_supervisor.GateRequest(
                    "dispatch_child",
                    goal_id="goal",
                    paid_worker_usd=1,
                    safety_critical=True,
                    data_loss_risk=True,
                ),
                "needs_human",
                "data_loss_budget_override_required",
            ),
        )
        for state, request, action, reason in cases:
            with self.subTest(reason=reason):
                decision = hermes_supervisor.decide_gate(
                    self.policy, state, request, self.now
                )
                self.assertEqual((decision.action, decision.reason_code), (action, reason))
                self.assertEqual(decision.effective_budget, state.daily_budget)
                self.assertEqual(decision.next_primary_goal_id, "goal")

        no_primary = hermes_supervisor.decide_gate(
            self.policy,
            hermes_supervisor.initial_supervisor_state(),
            hermes_supervisor.GateRequest("dispatch_child", goal_id="goal"),
            self.now,
        )
        self.assertEqual(
            (no_primary.action, no_primary.reason_code),
            ("schedule", "primary_goal_required"),
        )

    def test_exact_daily_limits_and_zero_cost_worker_boundaries(self) -> None:
        primary = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
        )
        twelfth = hermes_supervisor.decide_gate(
            self.policy,
            replace(primary, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 11, 0, 0)),
            hermes_supervisor.GateRequest("supervisor_run"),
            self.now,
        )
        thirteenth = hermes_supervisor.decide_gate(
            self.policy,
            replace(primary, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 12, 0, 0)),
            hermes_supervisor.GateRequest("supervisor_run"),
            self.now,
        )
        sixth = hermes_supervisor.decide_gate(
            self.policy,
            replace(primary, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 5, 2)),
            hermes_supervisor.GateRequest(
                "dispatch_child", goal_id="goal", active_worker_count=2, paid_worker_usd=0
            ),
            self.now,
        )
        fourth_worker = hermes_supervisor.decide_gate(
            self.policy,
            replace(primary, daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 0, 0)),
            hermes_supervisor.GateRequest(
                "dispatch_child", goal_id="goal", active_worker_count=3
            ),
            self.now,
        )

        self.assertEqual((twelfth.action, twelfth.effective_budget.supervisor_runs), ("allow", 12))
        self.assertEqual((thirteenth.action, thirteenth.reason_code), ("schedule", "supervisor_daily_limit"))
        self.assertEqual((sixth.action, sixth.reason_code), ("allow", "dispatch_allowed"))
        self.assertEqual((sixth.effective_budget.dispatches, sixth.effective_budget.paid_worker_usd), (6, 2))
        self.assertEqual(
            (fourth_worker.action, fourth_worker.reason_code),
            ("schedule", "worker_concurrency_limit"),
        )

    def test_supervisor_limit_requires_emergency_budget_override_with_data_loss_precedence(self) -> None:
        budget = hermes_supervisor.DailyBudget("2026-07-22", 12, 4, 1)
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            daily_budget=budget,
            last_accepted_primary_goal_id="goal",
        )
        cases = (
            ({}, "schedule", "supervisor_daily_limit"),
            ({"safety_critical": True}, "needs_human", "safety_budget_override_required"),
            ({"data_loss_risk": True}, "needs_human", "data_loss_budget_override_required"),
            (
                {"safety_critical": True, "data_loss_risk": True},
                "needs_human",
                "data_loss_budget_override_required",
            ),
        )

        for flags, action, reason in cases:
            with self.subTest(flags=flags):
                decision = hermes_supervisor.decide_gate(
                    self.policy,
                    state,
                    hermes_supervisor.GateRequest("supervisor_run", **flags),
                    self.now,
                )
                self.assertEqual((decision.action, decision.reason_code), (action, reason))
                self.assertEqual(decision.effective_budget, budget)
                self.assertEqual(decision.next_primary_goal_id, "goal")

    def test_gate_decision_report_is_minimal_deterministic_and_json_serializable(self) -> None:
        decision = hermes_supervisor.GateDecision(
            "needs_human",
            "data_loss_budget_override_required",
            hermes_supervisor.DailyBudget("2026-07-22", 12, 6, 2),
            "goal",
        )
        expected = {
            "action": "needs_human",
            "reason_code": "data_loss_budget_override_required",
            "effective_budget": {
                "date": "2026-07-22",
                "supervisor_runs": 12,
                "dispatches": 6,
                "paid_worker_usd": 2,
            },
            "next_primary_goal_id": "goal",
        }

        first = hermes_supervisor.gate_decision_report(decision)
        second = hermes_supervisor.gate_decision_report(decision)

        self.assertEqual(first, expected)
        self.assertEqual(first, second)
        self.assertEqual(
            set(first),
            {"action", "reason_code", "effective_budget", "next_primary_goal_id"},
        )
        self.assertEqual(
            set(first["effective_budget"]),
            {"date", "supervisor_runs", "dispatches", "paid_worker_usd"},
        )
        encoded = json.dumps(first, sort_keys=True)
        self.assertEqual(json.loads(encoded), expected)
        for forbidden in ("content", "explanation", "rationale", "trace", "chain_of_thought"):
            self.assertNotIn(forbidden, encoded)

        malformed = replace(
            decision,
            effective_budget=replace(decision.effective_budget, dispatches=True),
        )
        with self.assertRaises(hermes_supervisor.GateError):
            hermes_supervisor.gate_decision_report(malformed)

    def test_gate_is_deterministic_for_aware_non_utc_time_and_none_budget_date(self) -> None:
        state = replace(
            hermes_supervisor.initial_supervisor_state(),
            last_accepted_primary_goal_id="goal",
            daily_budget=hermes_supervisor.DailyBudget(None, 0, 0, 0),
        )
        request = hermes_supervisor.GateRequest(
            "dispatch_child", goal_id="goal", active_worker_count=2, paid_worker_usd=1
        )
        now = datetime(2026, 7, 22, 8, 0, tzinfo=timezone(timedelta(hours=-4)))

        first = hermes_supervisor.decide_gate(self.policy, state, request, now)
        second = hermes_supervisor.decide_gate(self.policy, state, request, now)

        self.assertEqual(first, second)
        self.assertEqual(
            first.effective_budget,
            hermes_supervisor.DailyBudget("2026-07-22", 0, 1, 1),
        )
        self.assertIsNone(state.daily_budget.date)


class SupervisorBatchServiceTests(unittest.TestCase):
    class Client:
        def __init__(self, *, fail: bool = False):
            self.projections = []
            self.fail = fail

        def create_supervisor_batch(self, projection):
            self.projections.append(projection)
            if self.fail:
                raise hermes_supervisor.CaptureError("fake failure")
            return hermes_supervisor.SupervisorBatchAck(
                hermes_supervisor.CreatedCardRef(
                    "batch-card", projection.title, "todo", len(self.projections) > 1
                ),
                projection.proposed_message_id,
                projection.proposed_event_id,
                projection.message_ids,
                projection.event_ids,
            )

    def fixture(self, directory: str):
        state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
        store = hermes_supervisor.StateStore(Path(directory) / "supervisor-state.json")
        state = store.initialize()
        return state_db, kanban_db, store, state

    @staticmethod
    def add_message(path: Path, identifier: int, content: str = "raw") -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO sessions VALUES (?, ?, ?, ?, ?)",
                ("session", "cli", "capture", 0, None),
            )
            connection.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                (identifier, "session", "user", content, identifier, 1, 0),
            )

    @staticmethod
    def add_event(path: Path, identifier: int, payload: dict[str, object]) -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, "source-task", None, "blocked", json.dumps(payload), identifier),
            )

    def test_batch_detector_never_reads_message_content_and_returns_redacted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, _, _ = self.fixture(directory)
            self.add_message(state_db, 1, "x" * (2 * 1024 * 1024))
            original_open = hermes_supervisor._open_readonly

            def guarded_open(path):
                connection = original_open(path)

                def authorizer(action, table, column, database, trigger):
                    if action == sqlite3.SQLITE_READ and table == "messages" and column == "content":
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                connection.set_authorizer(authorizer)
                return connection

            with mock.patch.object(hermes_supervisor, "_open_readonly", side_effect=guarded_open):
                changes = hermes_supervisor.detect_batch_changes(
                    state_db, kanban_db, profile="default",
                    last_message_id=0, last_event_id=0,
                )

            self.assertEqual(len(changes.messages), 1)
            self.assertEqual(changes.messages[0].session_id, "batch-redacted")
            self.assertEqual(changes.messages[0].content, "")

    def test_batch_malformed_user_metadata_fails_without_client_or_state_change(self) -> None:
        cases = (
            ("orphan-session", 1, None, 1, 0, None),
            ("active-text", "bad", 0, 1, 0, "session"),
            ("active-blob", sqlite3.Binary(b"1"), 0, 1, 0, "session"),
            ("active-two", 2, 0, 1, 0, "session"),
            ("archived-text", 1, "bad", 1, 0, "session"),
            ("archived-blob", 1, sqlite3.Binary(b"0"), 1, 0, "session"),
            ("archived-two", 1, 2, 1, 0, "session"),
            ("timestamp-text", 1, 0, "bad", 0, "session"),
            ("timestamp-blob", 1, 0, sqlite3.Binary(b"1"), 0, "session"),
            ("timestamp-infinite", 1, 0, float("inf"), 0, "session"),
            ("timestamp-negative-infinite", 1, 0, float("-inf"), 0, "session"),
            ("compacted-two", 1, 0, 1, 2, "session"),
            ("compacted-blob", 1, 0, 1, sqlite3.Binary(b"0"), "session"),
        )
        for name, active, archived, timestamp, compacted, session_id in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                state_db, kanban_db, store, state = self.fixture(directory)
                with closing(sqlite3.connect(state_db)) as connection, connection:
                    if session_id is not None:
                        connection.execute(
                            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                            (session_id, "cli", "capture", archived, None),
                        )
                    connection.execute(
                        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (1, session_id or "missing", "user", "secret", timestamp, active, compacted),
                    )
                before = store.path.read_bytes()
                client = self.Client()

                with self.assertRaisesRegex(
                    hermes_supervisor.DetectionError,
                    "state.db: invalid metadata for message 1",
                ):
                    hermes_supervisor.SupervisorBatchService(client).run_once(
                        store, state_db, kanban_db, load_policy(POLICY),
                        datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                    )

                self.assertEqual(client.projections, [])
                self.assertEqual(store.path.read_bytes(), before)
                self.assertEqual(store.read(), state)

    def test_batch_malformed_metadata_precedes_relevant_count_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            malformed_id = hermes_supervisor._BATCH_MAX_MESSAGES + 1
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("session", "cli", "capture", 0, None),
                )
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 'session', 'user', '', ?, 1, 0)",
                    ((identifier, identifier) for identifier in range(1, malformed_id)),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, 'session', 'user', '', ?, 1, 2)",
                    (malformed_id, malformed_id),
                )
            before = store.path.read_bytes()
            client = self.Client()

            with self.assertRaisesRegex(
                hermes_supervisor.DetectionError,
                f"state.db: invalid metadata for message {malformed_id}",
            ):
                hermes_supervisor.SupervisorBatchService(client).run_once(
                    store, state_db, kanban_db, load_policy(POLICY),
                    datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                )

            self.assertEqual(client.projections, [])
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(store.read(), state)

    def test_batch_valid_inactive_user_is_safely_cursor_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("session", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (1, 'session', 'user', '', 1, 0, 0)"
                )

            result = hermes_supervisor.SupervisorBatchService(self.Client()).run_once(
                store, state_db, kanban_db, load_policy(POLICY),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )

            self.assertEqual(result.action, "no_change")
            self.assertEqual(store.read().last_supervisor_message_id, 1)

    def test_batch_message_and_event_caps_fail_without_client_or_state_change(self) -> None:
        for source in ("messages", "events"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                state_db, kanban_db, store, _ = self.fixture(directory)
                if source == "messages":
                    with closing(sqlite3.connect(state_db)) as connection, connection:
                        connection.execute(
                            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                            ("session", "cli", "capture", 0, None),
                        )
                        connection.executemany(
                            "INSERT INTO messages VALUES (?, ?, 'user', '', ?, 1, 0)",
                            ((i, "session", i) for i in range(1, hermes_supervisor._BATCH_MAX_MESSAGES + 2)),
                        )
                else:
                    with closing(sqlite3.connect(kanban_db)) as connection, connection:
                        connection.executemany(
                            "INSERT INTO task_events VALUES (?, 't', NULL, 'blocked', '{}', ?)",
                            ((i, i) for i in range(1, hermes_supervisor._BATCH_MAX_EVENTS + 2)),
                        )
                before = store.path.read_bytes()
                client = self.Client()
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor.SupervisorBatchService(client).run_once(
                        store, state_db, kanban_db, load_policy(POLICY),
                        datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                    )
                self.assertEqual(client.projections, [])
                self.assertEqual(store.path.read_bytes(), before)

    def test_batch_event_byte_limits_fail_without_consumption(self) -> None:
        cases = (
            ("task", "t" * (hermes_supervisor._BATCH_TASK_ID_MAX_BYTES + 1), "{}"),
            ("payload", "t", '{"x":"' + "x" * hermes_supervisor._PAYLOAD_JSON_MAX_BYTES + '"}'),
            ("total", "t", '{"x":"' + "x" * 60_000 + '"}'),
        )
        for name, task_id, payload in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                state_db, kanban_db, store, _ = self.fixture(directory)
                with closing(sqlite3.connect(kanban_db)) as connection, connection:
                    rows = 5 if name == "total" else 1
                    connection.executemany(
                        "INSERT INTO task_events VALUES (?, ?, NULL, 'blocked', ?, ?)",
                        ((i, task_id, payload, i) for i in range(1, rows + 1)),
                    )
                before = store.path.read_bytes()
                client = self.Client()
                with self.assertRaises(hermes_supervisor.DetectionError):
                    hermes_supervisor.SupervisorBatchService(client).run_once(
                        store, state_db, kanban_db, load_policy(POLICY),
                        datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                    )
                self.assertEqual(client.projections, [])
                self.assertEqual(store.path.read_bytes(), before)

    def test_duplicate_data_loss_event_never_bypasses_gate_or_changes_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            with closing(sqlite3.connect(kanban_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 't', NULL, 'blocked', ?, 1)",
                    ('{"data_loss_risk":true,"data_loss_risk":false}',),
                )
            before = store.path.read_bytes()
            client = self.Client()
            with self.assertRaises(hermes_supervisor.DetectionError):
                hermes_supervisor.SupervisorBatchService(client).run_once(
                    store, state_db, kanban_db, load_policy(POLICY),
                    datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                )
            self.assertEqual(client.projections, [])
            self.assertEqual(store.path.read_bytes(), before)

    def test_no_changes_has_no_client_call_and_no_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            client = self.Client()
            result = hermes_supervisor.SupervisorBatchService(client).run_once(
                store, state_db, kanban_db, load_policy(POLICY),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            self.assertEqual(result.action, "no_change")
            self.assertEqual(result.reason, "no_changes")
            self.assertEqual(client.projections, [])
            self.assertIsNone(hermes_supervisor.supervisor_batch_report(result))

    def test_irrelevant_highwater_is_persisted_only_to_supervisor_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, before = self.fixture(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("session", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (4, "session", "assistant", "ignored", 4, 1, 0),
                )
            result = hermes_supervisor.SupervisorBatchService(self.Client()).run_once(
                store, state_db, kanban_db, load_policy(POLICY),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            self.assertEqual(result.action, "no_change")
            after = store.read()
            self.assertEqual(after.last_supervisor_message_id, 4)
            self.assertEqual(after.last_message_id, before.last_message_id)

    def test_cooldown_accumulates_then_enqueues_one_exact_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            epoch = int(now.timestamp())
            store.write(replace(state, last_supervisor_enqueued_at=epoch - 60))
            self.add_message(state_db, 1, "first secret")
            client = self.Client()
            service = hermes_supervisor.SupervisorBatchService(client)
            accumulating = service.run_once(
                store, state_db, kanban_db, load_policy(POLICY), now
            )
            self.assertEqual(accumulating.action, "accumulating")
            self.assertEqual(store.read().last_supervisor_message_id, 0)
            self.add_message(state_db, 2, "second secret")
            enqueued = service.run_once(
                store, state_db, kanban_db, load_policy(POLICY), now + timedelta(minutes=30)
            )
            self.assertEqual(enqueued.action, "enqueued")
            self.assertEqual(len(client.projections), 1)
            self.assertEqual(client.projections[0].message_ids, (1, 2))
            self.assertEqual(store.read().last_supervisor_message_id, 2)
            self.assertEqual(store.read().daily_budget.supervisor_runs, 1)

    def test_emergency_bypasses_cooldown_but_not_control_or_daily_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            epoch = int(now.timestamp())
            self.add_event(kanban_db, 1, {"data_loss_risk": True})
            policy = load_policy(POLICY)
            state = replace(
                state, last_supervisor_enqueued_at=epoch,
                daily_budget=hermes_supervisor.DailyBudget(
                    "2026-07-22", policy.scheduling.daily_supervisor_limit, 0, 0
                ),
            )
            store.write(state)
            client = self.Client()
            result = hermes_supervisor.SupervisorBatchService(client).run_once(
                store, state_db, kanban_db, policy, now
            )
            self.assertEqual(result.action, "needs_human")
            self.assertEqual(result.reason, "data_loss_budget_override_required")
            self.assertEqual(client.projections, [])
            store.write(replace(store.read(), control_state="paused",
                                daily_budget=hermes_supervisor.DailyBudget("2026-07-22", 0, 0, 0)))
            paused = hermes_supervisor.SupervisorBatchService(client).run_once(
                store, state_db, kanban_db, load_policy(POLICY), now
            )
            self.assertEqual(paused.action, "enqueued")
            self.assertEqual(paused.reason, "supervisor_batch_enqueued")
            self.assertEqual(len(client.projections), 1)
            self.assertEqual(paused.state.control_state, "paused")

    def test_create_failure_retains_inputs_and_state_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            self.add_message(state_db, 1)
            before = store.path.read_bytes()
            with self.assertRaises(hermes_supervisor.CaptureError):
                hermes_supervisor.SupervisorBatchService(self.Client(fail=True)).run_once(
                    store, state_db, kanban_db, load_policy(POLICY),
                    datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                )
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(store.read().last_supervisor_message_id, 0)

    def test_state_write_crash_retries_same_key_and_counts_budget_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            self.add_message(state_db, 1)
            client = self.Client()
            service = hermes_supervisor.SupervisorBatchService(client)
            real_write = store._write_unlocked

            def fail_final(state):
                if state.last_supervisor_message_id == 1:
                    raise OSError("fake pre-replace crash")
                return real_write(state)

            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            with mock.patch.object(store, "_write_unlocked", side_effect=fail_final):
                with self.assertRaises(hermes_supervisor.BatchError):
                    service.run_once(store, state_db, kanban_db, load_policy(POLICY), now)
            self.assertEqual(store.read().last_supervisor_message_id, 0)
            retried = service.run_once(store, state_db, kanban_db, load_policy(POLICY), now)
            self.assertEqual(retried.action, "enqueued")
            self.assertEqual(len(client.projections), 2)
            self.assertEqual(
                client.projections[0].idempotency_key,
                client.projections[1].idempotency_key,
            )
            self.assertEqual(store.read().daily_budget.supervisor_runs, 1)

    def test_crash_retry_accepts_existing_prefix_without_consuming_new_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            self.add_message(state_db, 1, "first")
            stored_responses = {}

            def runner(argv, **kwargs):
                key = argv[argv.index("--idempotency-key") + 1]
                existing = key in stored_responses
                if not existing:
                    stored_responses[key] = {
                        "id": f"batch-card-{len(stored_responses) + 1}",
                        "title": argv[3], "body": argv[5],
                        "assignee": "supervisor", "status": "todo", "existing": False,
                    }
                response = {**stored_responses[key], "existing": existing}
                return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

            client = hermes_supervisor.HermesKanbanClient(
                "/fake/hermes", "fixture", runner=runner
            )
            service = hermes_supervisor.SupervisorBatchService(client)
            real_write = store._write_unlocked

            def fail_final(state):
                if state.last_supervisor_message_id == 1:
                    raise OSError("fake pre-replace crash")
                return real_write(state)

            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            with mock.patch.object(store, "_write_unlocked", side_effect=fail_final):
                with self.assertRaises(hermes_supervisor.BatchError):
                    service.run_once(store, state_db, kanban_db, load_policy(POLICY), now)
            self.add_message(state_db, 2, "second")

            retried = service.run_once(store, state_db, kanban_db, load_policy(POLICY), now)

            self.assertEqual(retried.action, "enqueued")
            self.assertEqual(retried.message_ids, (1,))
            self.assertEqual(retried.ack.acknowledged_message_id, 1)
            self.assertEqual(store.read().last_supervisor_message_id, 1)
            self.assertEqual(store.read().daily_budget.supervisor_runs, 1)
            report = hermes_supervisor.supervisor_batch_report(retried)
            self.assertEqual(report["message_ids"], [1])
            next_result = service.run_once(
                store, state_db, kanban_db, load_policy(POLICY), now + timedelta(minutes=30)
            )
            self.assertEqual(next_result.message_ids, (2,))

    def test_report_uses_reason_code_and_result_ids_for_scheduled_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            self.add_message(state_db, 1)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            store.write(replace(state, last_supervisor_enqueued_at=int(now.timestamp()) + 1))

            result = hermes_supervisor.SupervisorBatchService(self.Client()).run_once(
                store, state_db, kanban_db, load_policy(POLICY), now
            )
            report = hermes_supervisor.supervisor_batch_report(result)

            self.assertEqual(result.message_ids, (1,))
            self.assertEqual(report["reason_code"], "batch_clock_rollback")
            self.assertNotIn("reason", report)
            self.assertEqual(report["message_ids"], [1])

    def test_exact_cooldown_boundary_and_tokyo_reset_allow_one_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            self.add_message(state_db, 1)
            policy = load_policy(POLICY)
            now = datetime(2026, 7, 22, 15, tzinfo=timezone.utc)
            epoch = int(now.timestamp())
            store.write(replace(
                state,
                last_supervisor_enqueued_at=epoch - policy.scheduling.batch_cooldown_seconds,
                daily_budget=hermes_supervisor.DailyBudget(
                    "2026-07-22", policy.scheduling.daily_supervisor_limit, 0, 0
                ),
            ))
            result = hermes_supervisor.SupervisorBatchService(self.Client()).run_once(
                store, state_db, kanban_db, policy, now
            )
            self.assertEqual(result.action, "enqueued")
            self.assertEqual(store.read().daily_budget.date, "2026-07-23")
            self.assertEqual(store.read().daily_budget.supervisor_runs, 1)

    def test_future_enqueue_clock_and_busy_lock_fail_closed_without_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, state = self.fixture(directory)
            self.add_message(state_db, 1)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            store.write(replace(state, last_supervisor_enqueued_at=int(now.timestamp()) + 1))
            client = self.Client()
            result = hermes_supervisor.SupervisorBatchService(client).run_once(
                store, state_db, kanban_db, load_policy(POLICY), now
            )
            self.assertEqual((result.action, result.reason),
                             ("scheduled", "batch_clock_rollback"))
            self.assertEqual(store.read().last_supervisor_message_id, 0)
            with hermes_supervisor.StateLock(store.lock_path):
                with self.assertRaises(hermes_supervisor.StateBusyError):
                    hermes_supervisor.SupervisorBatchService(client).run_once(
                        store, state_db, kanban_db, load_policy(POLICY), now
                    )
            self.assertEqual(client.projections, [])

    def test_malformed_new_ack_prefix_does_not_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            self.add_message(state_db, 1)
            self.add_message(state_db, 2)
            before = store.path.read_bytes()

            class MalformedClient:
                def create_supervisor_batch(self, projection):
                    return hermes_supervisor.SupervisorBatchAck(
                        hermes_supervisor.CreatedCardRef(
                            "card", "Supervisor batch m1-1 e1-0", "todo", False
                        ),
                        1, 0, (1,), (),
                    )

            with self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.SupervisorBatchService(MalformedClient()).run_once(
                    store, state_db, kanban_db, load_policy(POLICY),
                    datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                )
            self.assertEqual(store.path.read_bytes(), before)

    def test_report_rejects_hostile_result_inconsistencies_before_returning_none(self) -> None:
        state = hermes_supervisor.initial_supervisor_state()
        no_change = hermes_supervisor.SupervisorBatchResult("no_change", "no_changes", state)
        schedule_gate = hermes_supervisor.GateDecision(
            "schedule", "control_paused", state.daily_budget, None
        )
        human_gate = hermes_supervisor.GateDecision(
            "needs_human", "emergency_stop_active", state.daily_budget, None
        )
        scheduled = hermes_supervisor.SupervisorBatchResult(
            "scheduled", "control_paused", state, gate=schedule_gate, message_ids=(1,)
        )
        needs_human = hermes_supervisor.SupervisorBatchResult(
            "needs_human", "emergency_stop_active", state,
            gate=human_gate, event_ids=(1,),
        )
        invalid_simple = (
            replace(no_change, action="unknown"),
            replace(no_change, reason_code="Not Stable"),
            replace(no_change, message_ids=(1,)),
            replace(no_change, gate=schedule_gate),
            hermes_supervisor.SupervisorBatchResult(
                "accumulating", "batch_cooldown_active", state, message_ids=(2, 1)
            ),
            hermes_supervisor.SupervisorBatchResult(
                "accumulating", "wrong", state, message_ids=(1,)
            ),
            hermes_supervisor.SupervisorBatchResult(
                "scheduled", "batch_clock_rollback", state,
                gate=schedule_gate, message_ids=(1,),
            ),
            hermes_supervisor.SupervisorBatchResult(
                "scheduled", "batch_clock_rollback", state, message_ids=(True,)
            ),
            replace(scheduled, reason_code="different_reason"),
            replace(scheduled, gate=human_gate),
            replace(scheduled, state=replace(
                state, daily_budget=hermes_supervisor.DailyBudget(None, 1, 0, 0)
            )),
            replace(needs_human, reason_code="different_reason"),
            replace(needs_human, gate=schedule_gate),
        )
        for result in invalid_simple:
            with self.subTest(result=result), self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.supervisor_batch_report(result)

        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db, store, _ = self.fixture(directory)
            self.add_message(state_db, 1)
            valid = hermes_supervisor.SupervisorBatchService(self.Client()).run_once(
                store, state_db, kanban_db, load_policy(POLICY),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            self.assertEqual(hermes_supervisor.supervisor_batch_report(valid)["message_ids"], [1])
            malformed_projection = replace(valid.projection, body=valid.projection.body + " ")
            hostile = (
                replace(valid, reason_code="wrong"),
                replace(valid, message_ids=(2,)),
                replace(valid, ack=replace(valid.ack, message_ids=())),
                replace(valid, ack=replace(
                    valid.ack, card=replace(valid.ack.card, id="")
                )),
                replace(valid, state=replace(valid.state, last_supervisor_message_id=0)),
                replace(valid, gate=replace(valid.gate, reason_code="dispatch_allowed")),
                replace(valid, projection=malformed_projection),
            )
            for result in hostile:
                with self.subTest(result=result), self.assertRaises(hermes_supervisor.BatchError):
                    hermes_supervisor.supervisor_batch_report(result)


class WatchCycleTests(unittest.TestCase):
    class Client:
        def __init__(self, *, fail_batch: bool = False):
            self.capture_calls = []
            self.batch_calls = []
            self.fail_batch = fail_batch

        def create(self, projection):
            self.capture_calls.append(projection)
            return hermes_supervisor.CreatedCardRef(
                f"capture-{projection.source_message_id}", projection.title, "triage", False
            )

        def create_supervisor_batch(self, projection):
            self.batch_calls.append(projection)
            if self.fail_batch:
                raise hermes_supervisor.BatchError("injected batch failure")
            return hermes_supervisor.SupervisorBatchAck(
                hermes_supervisor.CreatedCardRef("batch-1", projection.title, "todo", False),
                projection.proposed_message_id, projection.proposed_event_id,
                projection.message_ids, projection.event_ids,
            )

    @staticmethod
    def fixture(directory: str, *, message: bool = False):
        state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
        if message:
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    ("session-secret", "cli", "capture", 0, None),
                )
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1, "session-secret", "user", "RAW PRIVATE INTENT", 1, 1, 0),
                )
        return state_db, kanban_db

    def test_one_cycle_uses_shared_store_and_returns_safe_frozen_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, message=True)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            client = self.Client()
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), client,
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            report = hermes_supervisor.watch_cycle_report(result)

        self.assertEqual(len(client.capture_calls), 1)
        self.assertEqual(len(client.batch_calls), 1)
        self.assertEqual(result.capture.state.last_message_id, 1)
        self.assertEqual(result.batch.state.last_supervisor_message_id, 1)
        self.assertEqual(report["capture"], {"card_count": 1, "card_ids": ["capture-1"]})
        self.assertEqual(report["batch"]["card"]["id"], "batch-1")
        self.assertNotIn("RAW PRIVATE INTENT", json.dumps(report))
        self.assertNotIn("session-secret", json.dumps(report))
        with self.assertRaises(FrozenInstanceError):
            result.mode_changed = True

    def test_missing_state_defaults_shadow_and_no_change_has_no_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), self.Client(),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            self.assertEqual(store.read().mode, "shadow")
            self.assertIsNone(hermes_supervisor.watch_cycle_report(result))

    def test_explicit_mode_is_persisted_and_reported_without_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), self.Client(),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc), mode="limited",
            )
            report = hermes_supervisor.watch_cycle_report(result)
            self.assertEqual(store.read().mode, "limited")
            self.assertEqual(report, {"mode_changed": True, "mode": "limited"})

            again = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), self.Client(),
                datetime(2026, 7, 22, 12, 1, tzinfo=timezone.utc), mode="limited",
            )
            self.assertIsNone(hermes_supervisor.watch_cycle_report(again))

    def test_capture_commit_survives_batch_failure_and_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory, message=True)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            client = self.Client(fail_batch=True)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            with self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.run_watch_cycle(
                    store, state_db, kanban_db, load_policy(POLICY), client, now
                )
            self.assertEqual(store.read().last_message_id, 1)
            self.assertEqual(store.read().last_supervisor_message_id, 0)
            client.fail_batch = False
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), client, now
            )

        self.assertEqual(len(client.capture_calls), 1)
        self.assertEqual(len(client.batch_calls), 2)
        self.assertEqual(result.capture.cards, ())
        self.assertEqual(result.batch.action, "enqueued")

    def test_cycle_and_report_reject_hostile_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = self.fixture(directory)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            valid = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), self.Client(),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
            )
            for kwargs in (
                {"store": object()}, {"profile": 1}, {"mode": "unsafe"},
                {"now": datetime(2026, 7, 22, 12)},
            ):
                call = {
                    "store": store, "state_db": state_db, "kanban_db": kanban_db,
                    "policy": load_policy(POLICY), "client": self.Client(),
                    "now": datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
                    "profile": "default", "mode": None,
                }
                call.update(kwargs)
                with self.assertRaises((hermes_supervisor.StateError, hermes_supervisor.CaptureError,
                                        hermes_supervisor.BatchError)):
                    hermes_supervisor.run_watch_cycle(**call)
            with self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.watch_cycle_report(replace(valid, mode_changed=1))


class GarbageCollectionTests(unittest.TestCase):
    OLD = ".state.json.tmp.123.0123456789abcdef"

    def test_missing_root_is_noop_and_dry_run_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            result = hermes_supervisor.collect_stale_state_temps(
                root, 30, now=4_000_000, dry_run=True
            )
            self.assertEqual(result, hermes_supervisor.GCResult((), ()))
            self.assertFalse(root.exists())

    def test_exact_old_regular_candidate_dry_run_is_deterministic_and_nonmutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / self.OLD
            second = root / ".state.json.tmp.9.aaaaaaaaaaaaaaaa"
            old.write_text("old", encoding="utf-8")
            second.write_text("old2", encoding="utf-8")
            cutoff = 4_000_000 - 30 * 86400
            os.utime(old, (cutoff, cutoff))
            os.utime(second, (cutoff - 1, cutoff - 1))
            result = hermes_supervisor.collect_stale_state_temps(
                root, 30, now=4_000_000, dry_run=True
            )

            self.assertEqual(result.candidates, tuple(sorted((second.name, old.name))))
            self.assertEqual(result.deleted, ())
            self.assertTrue(old.exists())
            self.assertTrue(second.exists())
            self.assertFalse((root / "state.json.lock").exists())

    def test_real_gc_deletes_only_exact_old_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cutoff = 4_000_000 - 30 * 86400
            candidate = root / self.OLD
            recent = root / ".state.json.tmp.124.fedcba9876543210"
            nonmatching = root / ".state.json.tmp.123.0123456789ABCDE"
            target = root / "target"
            symlink = root / ".state.json.tmp.125.aaaaaaaaaaaaaaaa"
            directory_candidate = root / ".state.json.tmp.126.bbbbbbbbbbbbbbbb"
            candidate.write_text("delete", encoding="utf-8")
            recent.write_text("keep", encoding="utf-8")
            nonmatching.write_text("keep", encoding="utf-8")
            target.write_text("keep", encoding="utf-8")
            symlink.symlink_to(target)
            directory_candidate.mkdir()
            for path in (candidate, nonmatching, target, symlink, directory_candidate):
                os.utime(path, (cutoff - 1, cutoff - 1), follow_symlinks=False)
            os.utime(recent, (cutoff + 1, cutoff + 1))

            result = hermes_supervisor.collect_stale_state_temps(
                root, 30, now=4_000_000, dry_run=False
            )

            self.assertEqual(result, hermes_supervisor.GCResult((candidate.name,), (candidate.name,)))
            self.assertFalse(candidate.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(nonmatching.exists())
            self.assertTrue(symlink.is_symlink())
            self.assertTrue(directory_candidate.is_dir())
            self.assertTrue((root / "state.json.lock").is_file())

    def test_root_symlink_and_busy_lock_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            linked = Path(directory) / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(hermes_supervisor.GCError):
                hermes_supervisor.collect_stale_state_temps(
                    linked, 30, now=4_000_000, dry_run=True
                )
            with hermes_supervisor.StateLock(real / "state.json.lock"):
                with self.assertRaises(hermes_supervisor.StateBusyError):
                    hermes_supervisor.collect_stale_state_temps(
                        real, 30, now=4_000_000, dry_run=False
                    )

    def test_older_than_and_hostile_inputs_fail_closed(self) -> None:
        for value in ("0d", "-1d", "30", " 30d", "30D", "01d", "999999999999999999999d"):
            with self.subTest(value=value), self.assertRaises(hermes_supervisor.GCError):
                hermes_supervisor.parse_older_than(value)
        self.assertEqual(hermes_supervisor.parse_older_than("30d"), 30)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kwargs in (
                {"root": Path("relative")}, {"root": str(root)}, {"days": True},
                {"now": float("nan")}, {"dry_run": 1},
            ):
                call = {"root": root, "days": 30, "now": 4_000_000, "dry_run": True}
                call.update(kwargs)
                with self.assertRaises(hermes_supervisor.GCError):
                    hermes_supervisor.collect_stale_state_temps(**call)

    def test_cli_empty_stdout_then_lists_safe_exact_basename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = subprocess.run(
                [sys.executable, str(CLI), "gc", "--older-than", "30d",
                 "--state-root", str(root), "--dry-run"],
                capture_output=True, text=True, check=False,
            )
            candidate = root / self.OLD
            candidate.write_text("old", encoding="utf-8")
            os.utime(candidate, (1, 1))
            listed = subprocess.run(
                [sys.executable, str(CLI), "gc", "--older-than", "30d",
                 "--state-root", str(root), "--dry-run"],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(empty.stdout, "")
        self.assertEqual(json.loads(listed.stdout), {"candidates": [self.OLD], "deleted": []})


class HomeManagerModuleContractTests(unittest.TestCase):
    def test_supervisor_module_is_opt_in_and_defines_safe_timers(self) -> None:
        module_path = REPO_ROOT / "home" / "modules" / "ai" / "hermes-supervisor.nix"
        text = module_path.read_text(encoding="utf-8")
        for fragment in (
            "services.hermes-supervisor", "default = false", "default = \"supervisor\"",
            "OnCalendar = \"*:0/10\"", "OnCalendar = \"*-*-* 03:15:00\"",
            "Persistent = true", "RandomizedDelaySec = \"15m\"", "UMask = \"0077\"",
            "OnFailure = [ \"hermes-failure-notify@%N.service\" ]",
            "StateDirectory = \"hermes-supervisor\"", "RuntimeDirectory = \"hermes-supervisor\"",
            "TimeoutStartSec = \"9m\"", "KillMode = \"control-group\"",
            "--older-than 30d", "--state-root", "--board",
            "lib.optional cfg.enable \"timers.target\"",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        self.assertNotIn("network-online.target", text)
        self.assertNotIn("kanban gc", text)
        self.assertNotIn("enable = true", text)

    def test_briefing_uses_hermes_venv_and_tokyo_2100_opt_in_timer(self) -> None:
        module_path = REPO_ROOT / "home" / "modules" / "ai" / "hermes-supervisor.nix"
        text = module_path.read_text(encoding="utf-8")
        for fragment in (
            "hermes-supervisor-briefing", "briefingCommand", " brief ",
            "hermesPkg.passthru.hermesVenv", "OnCalendar = \"*-*-* 21:00:00 Asia/Tokyo\"",
            "Persistent = true", "AccuracySec = \"1m\"", "--discord-target",
            "--webui-url", "--prompt", "StateDirectoryMode = \"0700\"",
            "RuntimeDirectoryMode = \"0700\"",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        self.assertIn("--prompt ${./hermes-supervisor/prompts/briefing.md}", text)
        self.assertNotIn(
            "--prompt ${config.xdg.configHome}/hermes-supervisor/prompts/briefing.md",
            text,
        )
        self.assertNotIn("hermes cron", text)

    def test_home_imports_module_without_enabling_it(self) -> None:
        home = (REPO_ROOT / "home" / "home.nix").read_text(encoding="utf-8")
        self.assertIn("./modules/ai/hermes-supervisor.nix", home)
        self.assertNotIn("services.hermes-supervisor.enable", home)


class SupervisorBatchPlannerAndClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(POLICY)
        self.state = replace(
            hermes_supervisor.initial_supervisor_state(),
            mode="limited",
            last_supervisor_message_id=4,
            last_supervisor_event_id=8,
        )
        self.changes = hermes_supervisor.ChangeSet(
            messages=(
                hermes_supervisor.MessageChange(7, "secret-session", "RAW SECRET", 1.0, False),
                hermes_supervisor.MessageChange(6, "other", "another raw", 2.0, False),
            ),
            events=(
                hermes_supervisor.EventChange(
                    10, "task-a", 3, "blocked", "blocked", "builder",
                    {"private": "PAYLOAD SECRET", "safety_critical": True},
                ),
            ),
            proposed_message_id=7,
            proposed_event_id=10,
        )

    def test_projection_is_deterministic_safe_and_enforces_limited_contract(self) -> None:
        first = hermes_supervisor.plan_supervisor_batch(self.changes, self.state, self.policy)
        later = hermes_supervisor.plan_supervisor_batch(
            replace(self.changes, proposed_message_id=99), self.state, self.policy
        )
        body = json.loads(first.body)
        self.assertEqual(first.message_ids, (6, 7))
        self.assertEqual(first.event_ids, (10,))
        self.assertTrue(first.emergency)
        self.assertTrue(first.safety_critical)
        self.assertFalse(first.data_loss_risk)
        self.assertEqual(first.idempotency_key, later.idempotency_key)
        self.assertEqual(first.title, "Supervisor batch m5-7 e9-10")
        self.assertLessEqual(len(first.body.encode()), 65536)
        self.assertNotIn("RAW SECRET", first.body)
        self.assertNotIn("secret-session", first.body)
        self.assertNotIn("PAYLOAD SECRET", first.body)
        self.assertEqual(body["message_ids"], [6, 7])
        self.assertEqual(body["contract"]["allowed_temperatures"], ["research", "build"])
        self.assertEqual(
            body["contract"]["allowed_workspaces"],
            ["scratch", "project_bound_worktree"],
        )
        self.assertTrue(body["contract"]["child_dispatch"])
        self.assertFalse(body["contract"]["real_apply"])
        self.assertIn("does not implement", body["instruction"])

    def test_shadow_contract_and_malformed_emergency_flags_fail_closed(self) -> None:
        projection = hermes_supervisor.plan_supervisor_batch(
            self.changes, replace(self.state, mode="shadow"), self.policy
        )
        contract = json.loads(projection.body)["contract"]
        self.assertEqual(contract["allowed_temperatures"], [])
        self.assertEqual(contract["allowed_workspaces"], [])
        self.assertFalse(contract["child_dispatch"])
        malformed = replace(
            self.changes,
            events=(replace(self.changes.events[0], payload={"emergency": 1}),),
        )
        with self.assertRaises(hermes_supervisor.BatchError):
            hermes_supervisor.plan_supervisor_batch(malformed, self.state, self.policy)

    def test_planner_rejects_invalid_event_metadata_and_wraps_integer_encoding(self) -> None:
        event = self.changes.events[0]
        invalid_events = (
            replace(event, run_id=True),
            replace(event, run_id=-1),
            replace(event, task_id=""),
            replace(event, kind=""),
            replace(event, classification=""),
            replace(event, actor_profile=""),
            replace(event, task_id="\ud800"),
            replace(event, run_id=10 ** 5000),
        )
        for index, invalid in enumerate(invalid_events):
            with self.subTest(index=index), self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.plan_supervisor_batch(
                    replace(self.changes, events=(invalid,)), self.state, self.policy
                )

    def test_client_uses_exact_public_argv_and_strict_matching_response(self) -> None:
        projection = hermes_supervisor.plan_supervisor_batch(self.changes, self.state, self.policy)
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            response = {
                "id": "task-1", "title": projection.title, "body": projection.body,
                "assignee": "supervisor", "status": "todo", "existing": True,
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

        client = hermes_supervisor.HermesKanbanClient(
            "/fake/hermes", "fixture", runner=runner, base_env={"SAFE": "1"}
        )
        card = client.create_supervisor_batch(projection)
        self.assertTrue(card.existing)
        self.assertEqual(calls[0][0], [
            "/fake/hermes", "kanban", "create", projection.title,
            "--body", projection.body, "--assignee", "supervisor",
            "--workspace", "scratch", "--idempotency-key", projection.idempotency_key,
            "--max-runtime", "30m", "--created-by", "supervisor-watcher",
            "--skill", "kanban-orchestrator", "--skill", "personal-project-management",
            "--max-retries", "2", "--json",
        ])
        self.assertIs(calls[0][1]["stdin"], subprocess.DEVNULL)
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["env"]["HERMES_KANBAN_BOARD"], "fixture")

    def test_batch_client_rejects_mismatched_or_archived_response(self) -> None:
        projection = hermes_supervisor.plan_supervisor_batch(self.changes, self.state, self.policy)
        for mutation in (
            {"title": "hostile"}, {"body": "hostile"}, {"assignee": "builder"},
            {"status": "archived"}, {"existing": 1},
        ):
            with self.subTest(mutation=mutation):
                response = {
                    "id": "task-1", "title": projection.title, "body": projection.body,
                    "assignee": "supervisor", "status": "todo", "existing": False,
                    **mutation,
                }

                def runner(argv, **kwargs):
                    return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

                client = hermes_supervisor.HermesKanbanClient(
                    "/fake/hermes", "fixture", runner=runner
                )
                with self.assertRaises(hermes_supervisor.BatchError):
                    client.create_supervisor_batch(projection)

    def test_existing_prefix_ack_is_exact_and_rejects_lossy_or_hostile_bodies(self) -> None:
        projection = hermes_supervisor.plan_supervisor_batch(self.changes, self.state, self.policy)
        prefix = json.loads(projection.body)
        prefix["source_cursors"]["message"]["end"] = 6
        prefix["source_cursors"]["event"]["end"] = 8
        prefix["message_ids"] = [6]
        prefix["event_ids"] = []
        prefix["events"] = []
        prefix_body = json.dumps(prefix, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

        def call(body, title="Supervisor batch m5-6 e9-8"):
            response = {
                "id": "task-1", "title": title, "body": body,
                "assignee": "supervisor", "status": "todo", "existing": True,
            }
            client = hermes_supervisor.HermesKanbanClient(
                "/fake/hermes", "fixture",
                runner=lambda argv, **kwargs: subprocess.CompletedProcess(
                    argv, 0, json.dumps(response), ""
                ),
            )
            return client.create_supervisor_batch(projection)

        ack = call(prefix_body)
        self.assertIs(type(ack), hermes_supervisor.SupervisorBatchAck)
        self.assertEqual((ack.acknowledged_message_id, ack.acknowledged_event_id), (6, 8))
        self.assertEqual((ack.message_ids, ack.event_ids), ((6,), ()))

        hostile = []
        for mutate in (
            lambda value: value["message_ids"].clear(),
            lambda value: value.__setitem__("batch_key", "wrong"),
            lambda value: value.__setitem__("mode", "shadow"),
            lambda value: value["source_cursors"]["message"].__setitem__("start", 5),
            lambda value: value["source_cursors"]["message"].__setitem__("end", 8),
        ):
            value = json.loads(prefix_body)
            mutate(value)
            hostile.append(json.dumps(
                value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ))
        deep = 0
        for _ in range(40):
            deep = [deep]
        hostile.extend((
            json.dumps(prefix, ensure_ascii=True, sort_keys=True),
            prefix_body.replace('{"batch_key"', '{"schema":"duplicate","batch_key"', 1),
            json.dumps({"nested": deep, **prefix}, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")),
            "{" + '"padding":"' + ("x" * 66000) + '",' + prefix_body[1:],
        ))
        for body in hostile:
            with self.subTest(body_length=len(body)), self.assertRaises(
                hermes_supervisor.BatchError
            ):
                call(body)

        future = json.loads(projection.body)
        future["source_cursors"]["message"]["end"] = 8
        future_body = json.dumps(
            future, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        with self.assertRaises(hermes_supervisor.BatchError):
            call(future_body, "Supervisor batch m5-8 e9-10")

    def test_oversized_body_fails_closed_without_omitting_ids(self) -> None:
        events = tuple(
            hermes_supervisor.EventChange(
                identifier, "task-" + ("x" * 200), None, "blocked", "blocked", None, {}
            )
            for identifier in range(9, 600)
        )
        changes = replace(
            self.changes, messages=(), events=events,
            proposed_message_id=4, proposed_event_id=599,
        )
        with self.assertRaisesRegex(hermes_supervisor.BatchError, "64KiB"):
            hermes_supervisor.plan_supervisor_batch(changes, self.state, self.policy)


class PolicyCliTests(unittest.TestCase):
    def run_cli_bytes(self, contents: bytes) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_bytes(contents)
            return subprocess.run(
                [sys.executable, str(CLI), "validate-policy", "--policy", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_invalid_utf8_has_concise_error_without_traceback(self) -> None:
        result = self.run_cli_bytes(b"{\xff}")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid policy:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_wrong_root_json_types_have_concise_policy_errors(self) -> None:
        for value in ("policy", [], None, False):
            with self.subTest(value=value):
                result = self.run_cli_bytes(json.dumps(value).encode())
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid policy: policy: expected object", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_invalid_policy_has_concise_error_without_traceback(self) -> None:
        data = json.loads(POLICY.read_text(encoding="utf-8"))
        permissions = data["permissions"]
        if not isinstance(permissions, dict):
            self.fail("permissions is not an object")
        permissions["denied_paths"] = []
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CLI), "validate-policy", "--policy", str(invalid)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid policy:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_repository_policy_validates_with_safe_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "validate-policy", "--policy", str(POLICY)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "stage=bootstrap active_goals=1\n")
        self.assertEqual(result.stderr, "")


class RolePromptContractTests(unittest.TestCase):
    PROMPT_DIR = REPO_ROOT / "home" / "modules" / "ai" / "hermes-supervisor" / "prompts"

    def test_repository_role_prompts_satisfy_distinct_contracts(self) -> None:
        sources = hermes_supervisor.validate_prompt_sources(self.PROMPT_DIR)
        self.assertEqual(tuple(source.role for source in sources), (
            "supervisor", "researcher", "builder", "verifier",
        ))
        texts = {source.role: source.text.casefold() for source in sources}
        for source in sources:
            with self.subTest(versioned_role=source.role):
                self.assertTrue(
                    source.text.startswith("Prompt-Version: hermes-supervisor-role/v1\n")
                )
                self.assertEqual(source.version, "hermes-supervisor-role/v1")
                self.assertEqual(
                    source.digest,
                    hashlib.sha256(source.text.encode("utf-8", "strict")).hexdigest(),
                )
        for role, text in texts.items():
            with self.subTest(role=role):
                for heading in ("role", "read/write boundary", "forbidden", "completion contract"):
                    self.assertIn(heading, text)
                self.assertIn("05-private/", text)
                self.assertIn("read", text)
                self.assertIn("write", text)
                self.assertIn("list", text)
                self.assertIn("search", text)
                self.assertIn("no exceptions", text)
                self.assertIn("tools enforce", text)
                self.assertNotIn("chain-of-thought", text)
        self.assertIn("does not implement", texts["supervisor"])
        self.assertIn("self-approve", texts["supervisor"])
        self.assertIn("reason code", texts["supervisor"])
        self.assertIn("strictly read-only", texts["researcher"])
        self.assertIn("recommendation", texts["researcher"])
        self.assertIn("disposable", texts["builder"])
        self.assertIn("verify the assigned path", texts["builder"])
        self.assertIn("never claim completion without evidence", texts["builder"])
        self.assertIn("independent", texts["verifier"])
        self.assertIn("pass/fail/blocked", texts["verifier"])
        self.assertIn("does not self-fix", texts["verifier"])

    def test_prompt_source_loader_fails_closed_for_unsafe_or_malformed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for role in ("supervisor", "researcher", "builder", "verifier"):
                (root / f"{role}.md").write_bytes(
                    (self.PROMPT_DIR / f"{role}.md").read_bytes()
                )
            (root / "builder.md").unlink()
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "missing"):
                hermes_supervisor.validate_prompt_sources(root)
            (root / "builder.md").write_bytes((self.PROMPT_DIR / "builder.md").read_bytes())
            (root / "verifier.md").unlink()
            (root / "verifier.md").symlink_to(root / "builder.md")
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "regular"):
                hermes_supervisor.validate_prompt_sources(root)
            (root / "verifier.md").unlink()
            (root / "verifier.md").write_bytes(b"\xff")
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "UTF-8"):
                hermes_supervisor.validate_prompt_sources(root)
            (root / "verifier.md").write_bytes(b"x" * 20000)
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "size"):
                hermes_supervisor.validate_prompt_sources(root)
            (root / "verifier.md").write_bytes((self.PROMPT_DIR / "verifier.md").read_bytes())
            supervisor = (root / "supervisor.md").read_text(encoding="utf-8")
            (root / "supervisor.md").write_text(
                supervisor.replace("reason code", "reason"), encoding="utf-8"
            )
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "contract"):
                hermes_supervisor.validate_prompt_sources(root)

    def test_prompt_source_loader_rejects_appended_contradiction_and_digest_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for role in hermes_supervisor._BOOTSTRAP_ROLES:
                (root / f"{role}.md").write_bytes(
                    (self.PROMPT_DIR / f"{role}.md").read_bytes()
                )
            with (root / "researcher.md").open("a", encoding="utf-8") as stream:
                stream.write("\nContradiction: reading 05-Private/ is allowed.\n")
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "digest"):
                hermes_supervisor.validate_prompt_sources(root)

    def test_prompt_source_loader_rejects_intermediate_symlink_and_dotdot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approved = root / "approved"
            approved.mkdir()
            for role in hermes_supervisor._BOOTSTRAP_ROLES:
                (approved / f"{role}.md").write_bytes(
                    (self.PROMPT_DIR / f"{role}.md").read_bytes()
                )
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(root, target_is_directory=True)

            final_link = root / "final-link"
            final_link.symlink_to(approved, target_is_directory=True)
            with self.assertRaisesRegex(
                hermes_supervisor.ProfileBootstrapError, "directory"
            ):
                hermes_supervisor.validate_prompt_sources(final_link)
            with self.assertRaisesRegex(
                hermes_supervisor.ProfileBootstrapError, "directory"
            ):
                hermes_supervisor.validate_prompt_sources(linked_parent / "approved")
            with mock.patch.object(hermes_supervisor.os, "open") as opened:
                for rejected in (
                    root / "child" / ".." / "approved",
                    root / "05-PRIVATE" / "approved",
                ):
                    with self.subTest(rejected=rejected), self.assertRaisesRegex(
                        hermes_supervisor.ProfileBootstrapError, "invalid prompt directory"
                    ):
                        hermes_supervisor.validate_prompt_sources(rejected)
                opened.assert_not_called()

    def test_prompt_source_loader_uses_nofollow_fd_reads_and_closes_fds_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for role in hermes_supervisor._BOOTSTRAP_ROLES:
                (root / f"{role}.md").write_bytes(
                    (self.PROMPT_DIR / f"{role}.md").read_bytes()
                )
            real_open = os.open
            real_close = os.close
            opened: list[tuple[int, int, int | None]] = []
            closed: list[int] = []

            def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
                fd = real_open(path, flags, mode, dir_fd=dir_fd)
                opened.append((fd, flags, dir_fd))
                return fd

            def tracked_close(fd):
                closed.append(fd)
                return real_close(fd)

            with mock.patch.object(hermes_supervisor.os, "open", side_effect=tracked_open), \
                    mock.patch.object(hermes_supervisor.os, "close", side_effect=tracked_close), \
                    mock.patch.object(
                        hermes_supervisor.os, "read", side_effect=OSError("injected read failure")
                    ):
                with self.assertRaisesRegex(
                    hermes_supervisor.ProfileBootstrapError, "read failed"
                ):
                    hermes_supervisor.validate_prompt_sources(root)

            self.assertGreaterEqual(len(opened), 2)
            self.assertTrue(all(flags & os.O_NOFOLLOW for _, flags, _ in opened))
            self.assertEqual(opened[0][2], None)
            self.assertEqual(opened[0][1] & os.O_DIRECTORY, os.O_DIRECTORY)
            self.assertTrue(all(
                item[2] in {opened_fd for opened_fd, _, _ in opened}
                for item in opened[1:]
            ))
            self.assertCountEqual([item[0] for item in opened], closed)

    def test_prompt_source_loader_closes_fds_when_intermediate_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "opened" / "blocked"
            target.parent.mkdir()
            real_open = os.open
            real_close = os.close
            opened: list[int] = []
            closed: list[int] = []

            def fail_intermediate(path, flags, mode=0o777, *, dir_fd=None):
                if path == "blocked":
                    raise OSError("injected intermediate failure")
                fd = real_open(path, flags, mode, dir_fd=dir_fd)
                opened.append(fd)
                return fd

            def tracked_close(fd):
                closed.append(fd)
                return real_close(fd)

            with mock.patch.object(
                hermes_supervisor.os, "open", side_effect=fail_intermediate
            ), mock.patch.object(
                hermes_supervisor.os, "close", side_effect=tracked_close
            ):
                with self.assertRaisesRegex(
                    hermes_supervisor.ProfileBootstrapError, "directory"
                ):
                    hermes_supervisor.validate_prompt_sources(target)

            self.assertGreater(len(opened), 1)
            self.assertCountEqual(opened, closed)


class ProfileListAndPlannerTests(unittest.TestCase):
    LISTING = """Profile Model Gateway Alias Distribution
------- ----- ------- ----- ------------
◆default model-a off yes local
 discord-safe model-b on yes local
h-chat model-c off yes local
"""

    def test_parser_accepts_live_shape_markers_hyphens_and_safe_sgr(self) -> None:
        parsed = hermes_supervisor.parse_profile_list(
            "\x1b[1mProfile Model Gateway Alias Distribution\x1b[0m\n"
            "------- ----- ------- ----- ------------\n"
            "◆ default model-a off yes local\n"
            "discord-safe model-b on yes local\n"
        )
        self.assertEqual(parsed.profiles, ("default", "discord-safe"))
        self.assertEqual(parsed.active_profile, "default")
        attached = hermes_supervisor.parse_profile_list(self.LISTING)
        self.assertEqual(attached.profiles, ("default", "discord-safe", "h-chat"))
        self.assertEqual(attached.active_profile, "default")
        live_spacing = hermes_supervisor.parse_profile_list(
            "\n" + self.LISTING + "\n"
        )
        self.assertEqual(live_spacing, attached)
        with self.assertRaises(FrozenInstanceError):
            attached.profiles = ()  # type: ignore[misc]

    def test_parser_fails_closed_for_malformed_or_ambiguous_output(self) -> None:
        cases = {
            "missing-default": self.LISTING.replace("default", "other"),
            "bad-header": self.LISTING.replace("Gateway", "Gate"),
            "no-separator": self.LISTING.replace("------- ----- ------- ----- ------------\n", ""),
            "truncated-row": self.LISTING + "broken only-two\n",
            "duplicate": self.LISTING + "default x x x x\n",
            "bad-token": self.LISTING + "Upper x x x x\n",
            "double-active": self.LISTING + "◆other x x x x\n",
            "escape": self.LISTING + "\x1b[2J",
            "backspace-ignored-column": self.LISTING.replace("model-a", "model\b-a"),
            "tab": self.LISTING.replace("model-a", "model\t-a"),
            "carriage-return": self.LISTING.replace("model-a", "model\r-a"),
            "c1": self.LISTING.replace("model-a", "model\x85-a"),
            "bidi": self.LISTING.replace("model-a", "model\u202e-a"),
            "zero-width": self.LISTING.replace("model-a", "model\u200b-a"),
            "unicode-line-separator": self.LISTING.replace("model-a off", "model-a\u2028off"),
            "nonbreaking-space": self.LISTING.replace("model-a off", "model-a\u00a0off"),
            "surrogate": self.LISTING + "\ud800",
            "oversize": self.LISTING + "x" * 70000,
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
                    hermes_supervisor.parse_profile_list(text)

    def test_planner_has_exact_order_argv_descriptions_and_idempotent_skips(self) -> None:
        sources = hermes_supervisor.validate_prompt_sources(RolePromptContractTests.PROMPT_DIR)
        profiles = hermes_supervisor.parse_profile_list(self.LISTING)
        first = hermes_supervisor.plan_profile_bootstrap(
            profiles, sources, executable="/tmp/hostile hermes;$(x)"
        )
        second = hermes_supervisor.plan_profile_bootstrap(
            profiles, sources, executable="/tmp/hostile hermes;$(x)"
        )
        self.assertEqual(first, second)
        self.assertEqual(tuple(operation.profile for operation in first), (
            "supervisor", "researcher", "builder", "verifier",
        ))
        self.assertTrue(all(operation.status == "create" for operation in first))
        for operation in first:
            self.assertEqual(operation.argv, (
                "/tmp/hostile hermes;$(x)", "profile", "create", operation.profile,
                "--clone-from", "default", "--description", operation.description,
            ))
            self.assertEqual(
                operation.prompt_source,
                f"home/modules/ai/hermes-supervisor/prompts/{operation.profile}.md",
            )
            self.assertNotIn("--no-alias", operation.argv)
        existing = hermes_supervisor.parse_profile_list(
            self.LISTING + "supervisor x x x x\nverifier x x x x\n"
        )
        operations = hermes_supervisor.plan_profile_bootstrap(existing, sources, executable="hermes")
        self.assertEqual([item.status for item in operations], [
            "skip_existing", "create", "create", "skip_existing",
        ])
        self.assertIsNone(operations[0].argv)
        self.assertIsNone(operations[3].argv)

    def test_planner_rejects_invalid_source_set_and_executable(self) -> None:
        sources = hermes_supervisor.validate_prompt_sources(RolePromptContractTests.PROMPT_DIR)
        profiles = hermes_supervisor.parse_profile_list(self.LISTING)
        for invalid in ("", "bad\x00name", "bad\ud800"):
            with self.subTest(executable=invalid):
                with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
                    hermes_supervisor.plan_profile_bootstrap(profiles, sources, executable=invalid)
        with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
            hermes_supervisor.plan_profile_bootstrap(profiles, sources[:-1], executable="hermes")
        with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
            hermes_supervisor.plan_profile_bootstrap(
                profiles, tuple(reversed(sources)), executable="hermes"
            )

    def test_planner_rejects_forged_profile_lists_and_prompt_sources(self) -> None:
        sources = hermes_supervisor.validate_prompt_sources(RolePromptContractTests.PROMPT_DIR)
        profiles = hermes_supervisor.parse_profile_list(self.LISTING)
        invalid_profiles = (
            hermes_supervisor.ProfileList(["default"], None),  # type: ignore[arg-type]
            hermes_supervisor.ProfileList(("default", "default"), None),
            hermes_supervisor.ProfileList(("default", "Bad"), None),
            hermes_supervisor.ProfileList(("default",), "missing"),
            hermes_supervisor.ProfileList(("other",), None),
        )
        for forged in invalid_profiles:
            with self.subTest(profile_list=forged):
                with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
                    hermes_supervisor.plan_profile_bootstrap(forged, sources, executable="hermes")

        forged_sources = (
            tuple(replace(source, path=Path("/tmp") / source.path.name) for source in sources),
            (replace(sources[0], text=sources[0].text + "\nextra\n"), *sources[1:]),
            (replace(sources[0], digest="0" * 64), *sources[1:]),
            (replace(sources[0], version="hermes-supervisor-role/v999"), *sources[1:]),
        )
        for forged in forged_sources:
            with self.subTest(forged_source=forged[0]):
                with self.assertRaises(hermes_supervisor.ProfileBootstrapError):
                    hermes_supervisor.plan_profile_bootstrap(profiles, forged, executable="hermes")


class BoundedSubprocessRunnerTests(unittest.TestCase):
    def run_python(
        self, program: str, *, limit: int = 256, timeout: float = 1.0,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return hermes_supervisor._bounded_subprocess_run(
            [sys.executable, "-c", program],
            environment={} if environment is None else environment,
            timeout=timeout,
            output_limit=limit,
        )

    def test_exact_limit_and_dual_stream_output_are_drained_without_deadlock(self) -> None:
        exact = self.run_python(
            "import os; os.write(1,b'o'*256); os.write(2,b'e'*256)"
        )
        self.assertEqual(exact.stdout, "o" * 256)
        self.assertEqual(exact.stderr, "e" * 256)
        dual = self.run_python(
            "import os; os.write(1,b'o'*100000); os.write(2,b'e'*100000)",
            limit=100000,
        )
        self.assertEqual(len(dual.stdout), 100000)
        self.assertEqual(len(dual.stderr), 100000)

    def test_stdout_stderr_overflow_kills_child_before_lingering_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for fd in (1, 2):
                with self.subTest(fd=fd):
                    marker = Path(directory) / f"marker-{fd}"
                    program = (
                        "import os,time,pathlib,subprocess,sys; "
                        "subprocess.Popen([sys.executable,'-c',"
                        "\"import os,time,pathlib; time.sleep(1); "
                        "pathlib.Path(os.environ['MARKER']).write_text('descendant')\"]); "
                        f"os.write({fd},b'x'*257); time.sleep(1); "
                        "pathlib.Path(os.environ['MARKER']).write_text('parent')"
                    )
                    started = time.monotonic()
                    with self.assertRaises(hermes_supervisor._BoundedOutputError):
                        self.run_python(
                            program, environment={"MARKER": str(marker)}, timeout=2.0
                        )
                    self.assertLess(time.monotonic() - started, 0.8)
                    time.sleep(0.3)
                    self.assertFalse(marker.exists())

    def test_timeout_kills_child_and_invalid_utf8_fails_strictly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "timeout-marker"
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_python(
                    "import os,time,pathlib; time.sleep(1); "
                    "pathlib.Path(os.environ['MARKER']).write_text('lingered')",
                    timeout=0.05,
                    environment={"MARKER": str(marker)},
                )
            time.sleep(0.3)
            self.assertFalse(marker.exists())
        with self.assertRaises(UnicodeDecodeError):
            self.run_python("import os; os.write(1,b'\\xff')")

    def test_timeout_kills_descendant_holding_pipes_after_parent_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "descendant-marker"
            program = (
                "import subprocess,sys; "
                "subprocess.Popen([sys.executable,'-c',"
                "\"import os,time,pathlib; time.sleep(.4); "
                "pathlib.Path(os.environ['MARKER']).write_text('lingered')\"])"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_python(
                    program, timeout=0.05, environment={"MARKER": str(marker)}
                )
            time.sleep(0.5)
            self.assertFalse(marker.exists())

    def test_selector_construction_failure_kills_and_reaps_spawned_child(self) -> None:
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen[Any]] = []

        def launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        with mock.patch.object(subprocess, "Popen", side_effect=launch), mock.patch.object(
            hermes_supervisor.selectors, "DefaultSelector",
            side_effect=RuntimeError("selector setup failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "selector setup failed"):
                self.run_python("import time; time.sleep(60)")

        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].returncode)
        with self.assertRaises(ProcessLookupError):
            os.kill(spawned[0].pid, 0)

    def test_cleanup_failures_do_not_skip_pipe_closes_or_kill_and_reap(self) -> None:
        events: list[str] = []

        class Pipe:
            def __init__(self, name: str, *, fail: bool = False):
                self.name = name
                self.fail = fail

            def close(self) -> None:
                events.append(f"close-{self.name}")
                if self.fail:
                    raise OSError(f"close {self.name} failed")

        class Process:
            pid = 321
            returncode = None
            stdout = Pipe("stdout", fail=True)
            stderr = Pipe("stderr")

            def kill(self) -> None:
                events.append("kill")

            def wait(self, timeout=None) -> int:
                events.append("wait")
                self.returncode = -9
                return self.returncode

        class Selector:
            def register(self, *args) -> None:
                raise RuntimeError("registration failed")

            def close(self) -> None:
                events.append("close-selector")
                raise OSError("selector close failed")

        process = Process()
        with mock.patch.object(subprocess, "Popen", return_value=process), mock.patch.object(
            hermes_supervisor.selectors, "DefaultSelector", return_value=Selector()
        ), mock.patch.object(os, "getpgrp", return_value=999), mock.patch.object(
            os, "killpg", side_effect=lambda pid, sig: events.append("killpg")
        ):
            with self.assertRaisesRegex(RuntimeError, "registration failed"):
                self.run_python("pass")

        self.assertEqual(
            events, ["close-selector", "close-stdout", "close-stderr", "killpg", "wait"]
        )

    def test_invalid_utf8_kills_process_group_before_waiting(self) -> None:
        events: list[str] = []

        class Pipe:
            def __init__(self, fd: int):
                self.fd = fd

            def close(self) -> None:
                events.append(f"close-{self.fd}")

        class Process:
            pid = 654
            returncode = None
            stdout = Pipe(10)
            stderr = Pipe(11)

            def kill(self) -> None:
                events.append("kill")

            def wait(self, timeout=None) -> int:
                events.append("wait")
                self.returncode = -9
                return self.returncode

        class Selector:
            def __init__(self):
                self.registered = {}

            def register(self, pipe, _events, name) -> None:
                key = mock.Mock(fileobj=pipe, fd=pipe.fd, data=name)
                self.registered[pipe.fd] = key

            def get_map(self):
                return self.registered

            def select(self, _timeout):
                return [(key, None) for key in tuple(self.registered.values())]

            def unregister(self, pipe) -> None:
                self.registered.pop(pipe.fd)

            def close(self) -> None:
                events.append("close-selector")

        reads = {10: [b"\xff", b""], 11: [b""]}
        process = Process()

        def get_parent_group() -> int:
            events.append("getpgrp")
            return 987

        def launch(*args, **kwargs):
            events.append("popen")
            return process

        with mock.patch.object(os, "getpgrp", side_effect=get_parent_group), mock.patch.object(
            subprocess, "Popen", side_effect=launch
        ), mock.patch.object(
            hermes_supervisor.selectors, "DefaultSelector", side_effect=Selector
        ), mock.patch.object(
            os, "read", side_effect=lambda fd, size: reads[fd].pop(0)
        ), mock.patch.object(
            os, "killpg", side_effect=lambda pid, sig: events.append(f"killpg-{pid}")
        ):
            with self.assertRaises(UnicodeDecodeError):
                self.run_python("pass")

        self.assertLess(events.index("getpgrp"), events.index("popen"))
        self.assertLess(events.index("killpg-654"), events.index("wait"))

    def test_kill_and_reap_never_signals_reaped_or_captured_parent_group(self) -> None:
        events: list[str] = []

        class Process:
            def __init__(self, pid: int, returncode):
                self.pid = pid
                self.returncode = returncode

            def kill(self) -> None:
                events.append(f"kill-{self.pid}")

            def wait(self) -> int:
                events.append(f"wait-{self.pid}")
                if self.returncode is None:
                    self.returncode = -9
                return self.returncode

        reaped = Process(700, 0)
        parent_collision = Process(701, None)
        with mock.patch.object(os, "killpg") as killpg, mock.patch.object(
            os, "getpgrp", side_effect=AssertionError("must use captured parent group")
        ):
            hermes_supervisor._kill_and_reap(
                cast(subprocess.Popen[bytes], reaped), 999
            )
            hermes_supervisor._kill_and_reap(
                cast(subprocess.Popen[bytes], parent_collision), 701
            )

        killpg.assert_not_called()
        self.assertEqual(events, ["wait-700", "kill-701", "wait-701"])


class HermesProfileClientTests(unittest.TestCase):
    VALID = ProfileListAndPlannerTests.LISTING

    def test_injected_runner_receives_only_public_list_argv_and_copied_env(self) -> None:
        calls = []
        caller_env = {"FIXTURE": "yes"}
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, self.VALID, "")
        client = hermes_supervisor.HermesProfileClient(
            "/tmp/hermes with spaces", runner=runner, base_env=caller_env
        )
        profiles = client.list_profiles()
        self.assertIn("default", profiles.profiles)
        self.assertEqual(calls[0][0], ["/tmp/hermes with spaces", "profile", "list"])
        self.assertFalse(calls[0][1]["shell"])
        self.assertIs(calls[0][1]["stdin"], subprocess.DEVNULL)
        self.assertEqual(calls[0][1]["env"], caller_env)
        self.assertIsNot(calls[0][1]["env"], caller_env)
        self.assertFalse(hasattr(client, "create"))
        self.assertFalse(hasattr(client, "create_profile"))

    def test_injected_runner_failures_are_bounded_concise_and_do_not_leak(self) -> None:
        cases = (
            (subprocess.CompletedProcess([], 7, "secret stdout", "secret stderr"), "status 7"),
            (subprocess.CompletedProcess([], 0, "x" * 1000, ""), "limit"),
            (subprocess.CompletedProcess([], 0, self.VALID, "x" * 1000), "limit"),
            (subprocess.CompletedProcess([], 0, self.VALID + "\ud800", ""), "UTF-8"),
            (subprocess.CompletedProcess([], 0, self.VALID, "\ud800"), "UTF-8"),
        )
        for completed, message in cases:
            with self.subTest(message=message):
                client = hermes_supervisor.HermesProfileClient(
                    "fake", runner=lambda *a, value=completed, **k: value, output_limit=512
                )
                with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, message) as caught:
                    client.list_profiles()
                self.assertNotIn("secret", str(caught.exception))
                self.assertLess(len(str(caught.exception)), 120)

    def test_production_profile_client_uses_shared_bounded_runner(self) -> None:
        observed = {}

        def run(argv, **kwargs):
            observed.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, self.VALID, "")

        with mock.patch.object(
            hermes_supervisor, "_bounded_subprocess_run", side_effect=run
        ) as bounded:
            hermes_supervisor.HermesProfileClient(
                "fake", base_env={"A": "b"}, timeout=2, output_limit=512
            ).list_profiles()
        bounded.assert_called_once()
        self.assertEqual(observed["environment"], {"A": "b"})
        self.assertEqual(observed["timeout"], 2)
        self.assertEqual(observed["output_limit"], 512)

        timeout = subprocess.TimeoutExpired(["fake"], 1, output=b"secret")
        with mock.patch.object(
            hermes_supervisor, "_bounded_subprocess_run", side_effect=timeout
        ):
            with self.assertRaisesRegex(hermes_supervisor.ProfileBootstrapError, "timed out") as caught:
                hermes_supervisor.HermesProfileClient("fake").list_profiles()
            self.assertNotIn("secret", str(caught.exception))

    def test_real_subprocess_rejects_stream_limits_and_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "profile fixture"
            executable.write_text(
                f"#!{sys.executable}\n" +
                "import os, sys\n"
                "mode = os.environ['MODE']\n"
                "valid = os.environ['VALID'].encode()\n"
                "if mode == 'large-out': sys.stdout.buffer.write(b'x' * 2048)\n"
                "elif mode == 'large-err': sys.stdout.buffer.write(valid); sys.stderr.buffer.write(b'x' * 2048)\n"
                "elif mode == 'bad-out': sys.stdout.buffer.write(b'\\xff')\n"
                "elif mode == 'bad-err': sys.stdout.buffer.write(valid); sys.stderr.buffer.write(b'\\xff')\n",
                encoding="utf-8",
            )
            executable.chmod(0o700)
            for mode, message in (
                ("large-out", "limit"), ("large-err", "limit"),
                ("bad-out", "UTF-8"), ("bad-err", "UTF-8"),
            ):
                with self.subTest(mode=mode):
                    client = hermes_supervisor.HermesProfileClient(
                        str(executable), output_limit=512,
                        base_env={"MODE": mode, "VALID": self.VALID},
                    )
                    with self.assertRaisesRegex(
                        hermes_supervisor.ProfileBootstrapError, message
                    ):
                        client.list_profiles()


class BootstrapProfilesCliTests(unittest.TestCase):
    def make_fake(self, directory: str, listing: str) -> tuple[Path, Path]:
        executable = Path(directory) / "fake hermes"
        log = Path(directory) / "calls.jsonl"
        executable.write_text(
            f"#!{sys.executable}\n" +
            "import json, os, sys\n"
            "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "sys.stdout.write(os.environ['FAKE_LISTING'])\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        return executable, log

    def run_cli(
        self, executable: Path, log: Path, listing: str, *extra: str
    ) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ, FAKE_LOG=str(log), FAKE_LISTING=listing)
        return subprocess.run(
            [sys.executable, str(CLI), "bootstrap-profiles", *extra,
             "--hermes", str(executable)],
            capture_output=True, text=True, check=False, env=environment,
        )

    def test_mixed_dry_run_is_deterministic_and_invokes_list_only(self) -> None:
        listing = ProfileListAndPlannerTests.LISTING + "supervisor x x x x\nverifier x x x x\n"
        with tempfile.TemporaryDirectory() as directory:
            executable, log = self.make_fake(directory, listing)
            first = self.run_cli(executable, log, listing, "--dry-run")
            second = self.run_cli(executable, log, listing, "--dry-run")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(first.stderr, "")
            report = json.loads(first.stdout)
            self.assertEqual(set(report), {"dry_run", "source_profile", "operations"})
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["source_profile"], "default")
            self.assertEqual([item["profile"] for item in report["operations"]], [
                "supervisor", "researcher", "builder", "verifier",
            ])
            self.assertEqual([item["status"] for item in report["operations"]], [
                "skip_existing", "create", "create", "skip_existing",
            ])
            self.assertIsNone(report["operations"][0]["argv"])
            self.assertEqual(
                report["operations"][1]["argv"][:6],
                [str(executable), "profile", "create", "researcher", "--clone-from", "default"],
            )
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(calls, [["profile", "list"], ["profile", "list"]])

    def test_all_existing_skips_and_never_executes_create(self) -> None:
        listing = ProfileListAndPlannerTests.LISTING + "".join(
            f"{role} x x x x\n" for role in ("supervisor", "researcher", "builder", "verifier")
        )
        with tempfile.TemporaryDirectory() as directory:
            executable, log = self.make_fake(directory, listing)
            result = self.run_cli(executable, log, listing, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(all(item["status"] == "skip_existing" for item in report["operations"]))
            self.assertTrue(all(item["argv"] is None for item in report["operations"]))
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ['["profile", "list"]'])

    def test_without_dry_run_invokes_fake_zero_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable, log = self.make_fake(directory, ProfileListAndPlannerTests.LISTING)
            result = self.run_cli(
                executable, log, ProfileListAndPlannerTests.LISTING
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("--dry-run", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(log.exists())

    def test_noncanonical_prompt_dir_is_rejected_before_validation_or_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            noncanonical = Path(directory) / "prompts"
            noncanonical.mkdir()
            symlink = Path(directory) / "linked-prompts"
            symlink.symlink_to(
                hermes_supervisor._CANONICAL_PROMPT_DIR, target_is_directory=True
            )
            for rejected in (noncanonical, symlink):
                with self.subTest(rejected=rejected), mock.patch.object(sys, "argv", [
                    str(CLI), "bootstrap-profiles", "--dry-run",
                    "--prompt-dir", str(rejected), "--hermes", "fake",
                ]), mock.patch.object(
                    hermes_supervisor, "validate_prompt_sources"
                ) as validate, mock.patch.object(
                    hermes_supervisor.HermesProfileClient, "list_profiles"
                ) as list_profiles, mock.patch("sys.stderr"):
                    self.assertEqual(hermes_supervisor.main(), 2)
                validate.assert_not_called()
                list_profiles.assert_not_called()

        dotdot = hermes_supervisor._CANONICAL_PROMPT_DIR.parent / "x" / ".." / "prompts"
        with mock.patch.object(sys, "argv", [
            str(CLI), "bootstrap-profiles", "--dry-run", "--prompt-dir", str(dotdot),
        ]), mock.patch.object(
            hermes_supervisor, "validate_prompt_sources"
        ) as validate, mock.patch("sys.stderr"):
            self.assertEqual(hermes_supervisor.main(), 2)
        validate.assert_not_called()

    def test_malformed_fake_output_is_concise_and_stdout_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable, log = self.make_fake(directory, "malformed\n")
            result = self.run_cli(executable, log, "malformed\n", "--dry-run")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("bootstrap-profiles:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ['["profile", "list"]'])


class BriefingProjectionTests(unittest.TestCase):
    @staticmethod
    def make_kanban(path: Path) -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT,
                    status TEXT, created_by TEXT, completed_at TEXT, result TEXT,
                    current_run_id INTEGER, block_kind TEXT
                );
                CREATE TABLE task_events (
                    id INTEGER PRIMARY KEY, task_id TEXT, run_id INTEGER,
                    kind TEXT, payload TEXT, created_at TEXT
                );
                CREATE TABLE task_runs (
                    id INTEGER PRIMARY KEY, task_id TEXT, profile TEXT,
                    status TEXT, ended_at TEXT, outcome TEXT, summary TEXT,
                    metadata TEXT, error TEXT
                );
            """)

    def test_projection_is_bounded_redacted_supervisor_only_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("t1", "安全な完了", "RAW-BODY-SECRET", "supervisor", "done", "supervisor-watcher", "2026-07-22", json.dumps({"summary": "完了要約", "decision": {"key": "apply", "question": "適用しますか", "options": ["適用", "保留"], "recommendation": "保留", "dangerous": True, "importance": 9}}), 1, None),
                        ("t2", "適用確認", None, "supervisor", "review", "supervisor", None, json.dumps({"summary": "dry-run通過"}), None, None),
                        ("u1", "無関係", "OTHER-SECRET", None, "done", "user", "2026-07-22", json.dumps({"summary": "漏洩"}), None, None),
                    ],
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 't1', 1, 'completed', ?, '2026-07-22')",
                    (json.dumps({"summary": "変更完了", "human_action": {"text": "確認してください"}}),),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (2, 't2', NULL, 'reviewed', '{}', '2026-07-22')"
                )
                connection.execute(
                    "INSERT INTO task_runs VALUES (1, 't1', 'builder', 'done', '2026-07-22', 'success', '検証済み', '{}', 'RAW-LOG-SECRET')"
                )

            first = hermes_supervisor.prepare_briefing(db, root, "2026-07-22")
            second = hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

            if first is None or second is None:
                self.fail("expected composite briefing fixture")
            self.assertEqual(first.markdown, second.markdown)
            self.assertEqual(first.title, "Supervisor Console — 2026-07")
            self.assertEqual(first.decisions[0].id, "D1")
            self.assertIn("適用確認: dry-run通過（適用候補）", first.markdown)
            for heading in ("## changed outcomes", "## Decisions", "## anomalies", "## Human Actions"):
                self.assertIn(heading, first.markdown)
            for forbidden in ("RAW-BODY-SECRET", "RAW-LOG-SECRET", "OTHER-SECRET", "Worker-by-Worker", "builder"):
                self.assertNotIn(forbidden, first.markdown)
            self.assertTrue(first.artifact_path.exists())
            self.assertTrue(first.state_path.exists())
            self.assertEqual(first.artifact_path.stat().st_mode & 0o777, 0o600)
            persisted = json.loads(first.state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["decision_ids"], {"apply": "D1"})
            self.assertEqual(
                persisted["decision_targets"],
                {"apply": {"task_id": "t1", "event_id": 1}},
            )
            self.assertEqual(persisted["closed_decisions"], {})
            self.assertEqual(persisted["reply_cursor"], 0)
            self.assertEqual(persisted["cursor"], 0)
            self.assertEqual(persisted["pending"]["cursor"], 2)

    def test_projection_caps_each_human_readable_section_and_reports_omissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                for index in range(1, 257):
                    task_id = f"outcome-{index:03d}"
                    title = f"完了項目{index:03d}-abcdefghijklmnopqrstuvwxy"
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, NULL, NULL, 'done', "
                        "'supervisor', '2026-07-22', ?, NULL, NULL)",
                        (task_id, title, json.dumps({"summary": f"要約{index:03d}"})),
                    )
                    connection.execute(
                        "INSERT INTO task_events VALUES (?, ?, NULL, 'completed', '{}', '2026-07-22')",
                        (index, task_id),
                    )

            prepared = hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

            if prepared is None:
                self.fail("expected capped briefing")
            changed = prepared.markdown.split("## changed outcomes\n", 1)[1].split(
                "\n\n## Decisions", 1
            )[0]
            bullets = [line for line in changed.splitlines() if line.startswith("- ")]
            self.assertLessEqual(len(bullets), 21)
            self.assertIn("236件省略", changed)
            self.assertLessEqual(
                len(prepared.markdown.encode("utf-8")),
                hermes_supervisor._BRIEFING_ARTIFACT_MAX_BYTES,
            )

    def test_empty_briefing_day_is_noop_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)

            self.assertIsNone(
                hermes_supervisor.prepare_briefing(db, root, "2026-07-22")
            )
            self.assertFalse(root.exists())

    def test_month_rollover_carries_cursor_open_decisions_and_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            decision = {
                "key": "carry",
                "question": "継続判断?",
                "options": ["A", "B"],
                "recommendation": "B",
                "dangerous": False,
                "importance": 5,
            }
            state = hermes_supervisor._briefing_default_state("2026-07")
            state.update({
                "cursor": 300,
                "reply_cursor": 99,
                "next_decision": 8,
                "decision_ids": {"carry": "D7"},
                "open_decisions": {"carry": decision},
            })
            state_path = root / "briefings" / "state.json"
            hermes_supervisor._write_briefing_state(state_path, state, "2026-07")

            prepared = hermes_supervisor.prepare_briefing(db, root, "2026-08-01")

            self.assertIsNotNone(prepared)
            self.assertEqual(prepared.title, "Supervisor Console — 2026-08")
            self.assertEqual(prepared.decisions[0].id, "D7")
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["month"], "2026-08")
            self.assertEqual(persisted["cursor"], 300)
            self.assertEqual(persisted["reply_cursor"], 0)
            self.assertEqual(persisted["pending"]["cursor"], 300)

    def test_month_rollover_resumes_previous_pending_artifact_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            marker = "<!-- supervisor-briefing:2026-07-31:e9 -->"
            artifact = root / "briefings" / "2026-07" / "2026-07-31.md"
            hermes_supervisor._atomic_private_write(
                artifact, f"# July\n{marker}\n".encode("utf-8")
            )
            state = hermes_supervisor._briefing_default_state("2026-07")
            state["pending"] = {
                "date": "2026-07-31",
                "cursor": 9,
                "marker": marker,
                "artifact": "2026-07-31.md",
                "discord_status": "none",
                "session_done": False,
                "included_anomalies": [],
            }
            state_path = root / "briefings" / "state.json"
            hermes_supervisor._write_briefing_state(state_path, state, "2026-07")

            prepared = hermes_supervisor.prepare_briefing(db, root, "2026-08-01")

            if prepared is None:
                self.fail("expected previous pending briefing")
            self.assertEqual(prepared.title, "Supervisor Console — 2026-07")
            self.assertEqual(prepared.artifact_path, artifact)
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["month"], "2026-07")

    def test_projection_rejects_unbounded_fetched_columns_before_materializing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES ('t', 'title', NULL, NULL, ?, 'supervisor', NULL, '{}', NULL, NULL)",
                    ("x" * (1024 * 1024),),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 't', NULL, 'completed', '{}', '2026-07-22')"
                )

            with self.assertRaisesRegex(
                hermes_supervisor.BriefingError, "metadata"
            ):
                hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

    def test_projection_limits_decisions_and_marks_application_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                for index in range(1, 12):
                    task_id = f"decision-{index}"
                    result = json.dumps({
                        "decision": {
                            "key": f"key-{index}",
                            "question": f"判断{index}?",
                            "options": ["A", "B"],
                            "recommendation": "A",
                            "dangerous": False,
                            "importance": index,
                        }
                    })
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, NULL, NULL, 'pending', 'supervisor', NULL, ?, NULL, NULL)",
                        (task_id, f"Decision {index}", result),
                    )
                    connection.execute(
                        "INSERT INTO task_events VALUES (?, ?, NULL, 'decision_required', '{}', '2026-07-22')",
                        (index, task_id),
                    )
                connection.execute(
                    "INSERT INTO tasks VALUES ('review', '適用確認', NULL, NULL, 'review', 'supervisor', NULL, ?, NULL, NULL)",
                    (json.dumps({"summary": "dry-run通過"}),),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (12, 'review', NULL, 'reviewed', '{}', '2026-07-22')"
                )

            prepared = hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

            if prepared is None:
                self.fail("expected bounded briefing")
            self.assertEqual(len(prepared.decisions), 10)
            self.assertEqual(prepared.decisions[0].question, "判断11?")
            self.assertNotIn("判断1?", [item.question for item in prepared.decisions])
            self.assertIn("適用確認: dry-run通過（適用候補）", prepared.markdown)

    def test_event_retention_never_moves_briefing_cursor_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES ('t', 'title', NULL, NULL, 'done', 'user', NULL, '{}', NULL, NULL)"
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (50, 't', NULL, 'completed', '{}', '2026-07-01')"
                )
            state = hermes_supervisor._briefing_default_state("2026-07")
            state["cursor"] = 100
            state_path = root / "briefings" / "state.json"
            hermes_supervisor._write_briefing_state(state_path, state, "2026-07")

            self.assertIsNone(
                hermes_supervisor.prepare_briefing(db, root, "2026-07-22")
            )

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["cursor"], 100)

    def test_pin_action_append_is_idempotent_across_crash_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            artifact = Path(directory) / "brief.md"
            prepared = hermes_supervisor.PreparedBriefing(
                "Supervisor Console — 2026-07",
                f"# Console\n{marker}\n\n## Human Actions\n- なし\n",
                (), (), 1, marker, artifact, Path(directory) / "state.json",
            )

            once = hermes_supervisor._append_pin_action(prepared)
            twice = hermes_supervisor._append_pin_action(once)

            self.assertEqual(twice.markdown.count("- Pin Console:"), 1)

    def test_nightly_briefing_route_rejects_emergency_delivery(self) -> None:
        with self.assertRaisesRegex(hermes_supervisor.BriefingError, "route"):
            hermes_supervisor.run_briefing_cycle(
                Path("missing-kanban.db"),
                Path("missing-state"),
                "2026-07-22",
                object(),
                "prompt",
                "/fake/hermes",
                "discord",
                "https://ser7",
                route="emergency",
            )

    def test_briefing_without_decisions_never_calls_discord(self) -> None:
        class Store:
            def __init__(self):
                self.messages = []

            def get_session_by_title(self, title):
                return None

            def create_session(self, session_id, source, system_prompt=None):
                return session_id

            def set_session_title(self, session_id, title):
                return True

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return list(self.messages)

            def append_message(self, session_id, role, content):
                self.messages.append({"role": role, "content": content})
                return len(self.messages)

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES ('done', '完了', NULL, NULL, 'done', 'supervisor', NULL, ?, NULL, NULL)",
                    (json.dumps({"summary": "検証済み"}),),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 'done', NULL, 'completed', '{}', '2026-07-22')"
                )

            def runner(*args, **kwargs):
                self.fail("Discord runner must not be called without decisions")

            result = hermes_supervisor.run_briefing_cycle(
                db, root, "2026-07-22", Store(), "prompt", "/fake/hermes",
                "discord", "https://ser7", runner=runner,
            )

            if result is None:
                self.fail("expected delivered briefing")
            self.assertEqual(result["decision_count"], 0)

    def test_published_delivery_anomaly_is_consumed_after_session_delivery(self) -> None:
        class Store:
            def __init__(self):
                self.sessions = {}
                self.messages = {}

            def get_session_by_title(self, title):
                return next(
                    (item for item in self.sessions.values() if item["title"] == title),
                    None,
                )

            def create_session(self, session_id, source, system_prompt=None):
                self.sessions[session_id] = {"id": session_id, "title": None}
                self.messages[session_id] = []
                return session_id

            def set_session_title(self, session_id, title):
                self.sessions[session_id]["title"] = title
                return True

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return self.messages[session_id][offset:][:limit]

            def append_message(self, session_id, role, content):
                self.messages[session_id].append({"role": role, "content": content})
                return len(self.messages[session_id])

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            state = hermes_supervisor._briefing_default_state("2026-07")
            state["delivery_anomalies"] = ["discord_delivery_failed"]
            state_path = root / "briefings" / "state.json"
            hermes_supervisor._write_briefing_state(state_path, state, "2026-07")

            result = hermes_supervisor.run_briefing_cycle(
                db, root, "2026-07-22", Store(), "prompt", "/fake/hermes",
                "discord", "https://ser7",
            )

            self.assertIsNotNone(result)
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["delivery_anomalies"], [])
            self.assertIsNone(
                hermes_supervisor.prepare_briefing(db, root, "2026-07-23")
            )

    def test_consumed_anomaly_is_readded_when_discord_fails_again(self) -> None:
        class Store:
            def __init__(self):
                self.messages = []

            def get_session_by_title(self, title):
                return None

            def create_session(self, session_id, source, system_prompt=None):
                return session_id

            def set_session_title(self, session_id, title):
                return True

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return list(self.messages)

            def append_message(self, session_id, role, content):
                self.messages.append({"role": role, "content": content})
                return len(self.messages)

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            decision = json.dumps({"decision": {
                "key": "apply", "question": "適用?", "options": ["適用", "保留"],
                "recommendation": "保留", "dangerous": False, "importance": 1,
            }})
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES ('decision', '判断', NULL, NULL, 'pending', 'supervisor', NULL, ?, NULL, NULL)",
                    (decision,),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 'decision', NULL, 'decision_required', '{}', '2026-07-22')"
                )
            state = hermes_supervisor._briefing_default_state("2026-07")
            state["delivery_anomalies"] = ["discord_delivery_failed"]
            state_path = root / "briefings" / "state.json"
            hermes_supervisor._write_briefing_state(state_path, state, "2026-07")

            def runner(*args, **kwargs):
                return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="failed")

            with self.assertRaisesRegex(
                hermes_supervisor.BriefingError, "Discord delivery"
            ):
                hermes_supervisor.run_briefing_cycle(
                    db, root, "2026-07-22", Store(), "prompt", "/fake/hermes",
                    "discord", "https://ser7", runner=runner,
                )

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["delivery_anomalies"], ["discord_delivery_failed"])
            self.assertEqual(persisted["pending"]["discord_status"], "failed")

    def test_fake_session_and_discord_delivery_is_exactly_idempotent(self) -> None:
        class FakeSessionStore:
            def __init__(self):
                self.sessions = {}
                self.messages = {}
                self.appended = []

            def get_session_by_title(self, title):
                return next((value for value in self.sessions.values() if value["title"] == title), None)

            def create_session(self, session_id, source, system_prompt=None):
                self.sessions[session_id] = {"id": session_id, "source": source, "title": None, "system_prompt": system_prompt}
                self.messages[session_id] = []
                return session_id

            def set_session_title(self, session_id, title):
                self.sessions[session_id]["title"] = title
                return True

            def append_message(self, session_id, role, content):
                self.messages[session_id].append({"role": role, "content": content})
                self.appended.append((session_id, role, content))
                return len(self.messages[session_id])

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return self.messages[session_id][offset:][:limit]

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kanban.db"
            root = Path(directory) / "state"
            self.make_kanban(db)
            decision = {"decision": {"key": "deploy", "question": "適用しますか", "options": ["適用", "保留"], "recommendation": "保留", "dangerous": False, "importance": 8}, "summary": "完了"}
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO tasks VALUES ('t', '変更', 'SECRET-BODY', 'supervisor', 'done', 'supervisor', '2026-07-22', ?, NULL, NULL)",
                    (json.dumps(decision),),
                )
                connection.execute(
                    "INSERT INTO task_events VALUES (1, 't', NULL, 'completed', '{}', '2026-07-22')"
                )
            store = FakeSessionStore()
            discord_calls = []

            def runner(argv, **kwargs):
                state = json.loads((root / "briefings/state.json").read_text())
                self.assertEqual(state["pending"]["discord_status"], "attempted")
                self.assertTrue((root / "briefings/2026-07/2026-07-22.md").exists())
                discord_calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

            first = hermes_supervisor.run_briefing_cycle(
                db, root, "2026-07-22", store, "月次Console prompt", "/fake/hermes",
                "discord", "https://ser7", runner=runner,
            )
            second = hermes_supervisor.run_briefing_cycle(
                db, root, "2026-07-22", store, "月次Console prompt", "/fake/hermes",
                "discord", "https://ser7", runner=runner,
            )

            self.assertEqual(first, {"action": "delivered", "decision_count": 1, "session_id": "supervisor-console-2026-07"})
            self.assertIsNone(second)
            self.assertEqual(len(discord_calls), 1)
            argv = discord_calls[0][0]
            self.assertEqual(argv[:4], ["/fake/hermes", "send", "--to", "discord"])
            payload = json.loads(argv[4])
            self.assertEqual(payload, {"decision_count": 1, "most_important": {"id": "D1", "question": "適用しますか"}, "webui_url": "https://ser7"})
            self.assertEqual([role for _, role, _ in store.appended], ["system", "user", "assistant"])
            self.assertEqual(store.appended[0][2], "月次Console prompt")
            self.assertEqual(store.appended[1][2], hermes_supervisor.BRIEFING_MACHINE_SEED)
            self.assertIn("Pin Console", store.appended[2][2])
            self.assertEqual(store.appended[2][2].count("supervisor-briefing:"), 1)
            persisted = json.loads((root / "briefings/state.json").read_text())
            self.assertEqual(persisted["cursor"], 1)
            self.assertIsNone(persisted["pending"])

    def test_session_delivery_scans_bounded_pages_before_appending(self) -> None:
        class PagedStore:
            def __init__(self, marker: str):
                self.messages = [
                    {"role": "system", "content": "月次Console prompt"},
                    {"role": "user", "content": hermes_supervisor.BRIEFING_MACHINE_SEED},
                    *({"role": "user", "content": f"reply-{index}"} for index in range(297)),
                    {"role": "assistant", "content": f"brief {marker}"},
                ]
                self.appended = []
                self.read_calls = 0

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                self.read_calls += 1
                return self.messages[offset:][:limit]

            def append_message(self, session_id, role, content):
                self.appended.append((session_id, role, content))
                return len(self.messages) + len(self.appended)

        with tempfile.TemporaryDirectory() as directory:
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            artifact = Path(directory) / "2026-07-22.md"
            state = Path(directory) / "state.json"
            prepared = hermes_supervisor.PreparedBriefing(
                "Supervisor Console — 2026-07",
                f"# brief\n{marker}\n",
                (),
                (),
                1,
                marker,
                artifact,
                state,
            )
            store = PagedStore(marker)

            session_id = hermes_supervisor._deliver_session(
                store, prepared, "月次Console prompt", new_session=False
            )

            self.assertEqual(session_id, "supervisor-console-2026-07")
            self.assertEqual(store.appended, [])
            self.assertEqual(store.read_calls, 1)

    def test_existing_empty_session_recovers_prompt_before_seed(self) -> None:
        class EmptyStore:
            def __init__(self):
                self.appended = []

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return []

            def append_message(self, session_id, role, content):
                self.appended.append((role, content))
                return len(self.appended)

        with tempfile.TemporaryDirectory() as directory:
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            prepared = hermes_supervisor.PreparedBriefing(
                "Supervisor Console — 2026-07", f"# brief\n{marker}\n", (), (),
                1, marker, Path(directory) / "brief.md", Path(directory) / "state.json",
            )
            store = EmptyStore()

            hermes_supervisor._deliver_session(
                store, prepared, "月次Console prompt", new_session=False
            )

            self.assertEqual(
                [role for role, _ in store.appended], ["system", "user", "assistant"]
            )

    def test_installed_hermes_sessiondb_contract_when_available(self) -> None:
        try:
            from hermes_state import SessionDB
        except ImportError:
            self.skipTest("hermes_state is available only in the Hermes venv")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionDB(db_path=root / "state.db")
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            prepared = hermes_supervisor.PreparedBriefing(
                "Supervisor Console — 2026-07", f"# brief\n{marker}\n", (), (),
                1, marker, root / "brief.md", root / "brief-state.json",
            )

            first = hermes_supervisor._deliver_session(
                store, prepared, "prompt", new_session=True
            )
            second = hermes_supervisor._deliver_session(
                store, prepared, "prompt", new_session=False
            )

            self.assertEqual(first, second)
            session = store.get_session(first)
            if session is None:
                self.fail("expected installed Hermes session")
            self.assertEqual(session["title"], prepared.title)
            messages = store.get_messages(
                first, include_inactive=False, limit=16, offset=0
            )
            self.assertEqual(
                [message["role"] for message in messages],
                ["system", "user", "assistant"],
            )
            store.close()

    def test_session_capacity_is_checked_before_any_append(self) -> None:
        class FullStore:
            def __init__(self):
                self.messages = [{"role": "system", "content": "prompt"}] + [
                    {"role": "user", "content": f"history-{index}"}
                    for index in range(4095)
                ]
                self.appended = []

            def get_messages(self, session_id, include_inactive=False, limit=None, offset=0):
                return self.messages[offset:][:limit]

            def append_message(self, session_id, role, content):
                self.appended.append((role, content))
                return len(self.messages) + len(self.appended)

        with tempfile.TemporaryDirectory() as directory:
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            prepared = hermes_supervisor.PreparedBriefing(
                "Supervisor Console — 2026-07", f"# brief\n{marker}\n", (), (),
                1, marker, Path(directory) / "brief.md", Path(directory) / "state.json",
            )
            store = FullStore()

            with self.assertRaisesRegex(
                hermes_supervisor.BriefingError, "message limit"
            ):
                hermes_supervisor._deliver_session(
                    store, prepared, "prompt", new_session=False
                )

            self.assertEqual(store.appended, [])

    def test_pending_artifact_rejects_traversal_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "state"
            month_root = root / "briefings" / "2026-07"
            month_root.mkdir(parents=True)
            db = Path(directory) / "kanban.db"
            self.make_kanban(db)
            marker = "<!-- supervisor-briefing:2026-07-22:e1 -->"
            outside = root / "briefings" / "outside.md"
            outside.write_text(f"# outside\n{marker}\n", encoding="utf-8")
            outside.chmod(0o600)
            state = hermes_supervisor._briefing_default_state("2026-07")
            state["pending"] = {
                "date": "2026-07-22",
                "cursor": 1,
                "marker": marker,
                "artifact": "../outside.md",
                "discord_status": "none",
                "session_done": False,
                "included_anomalies": [],
            }
            state_path = root / "briefings" / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            state_path.chmod(0o600)

            with self.assertRaises(hermes_supervisor.BriefingError):
                hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

            state["pending"]["artifact"] = "2026-07-22.md"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            artifact_path = month_root / "2026-07-22.md"
            artifact_path.symlink_to(outside)

            with self.assertRaises(hermes_supervisor.BriefingError):
                hermes_supervisor.prepare_briefing(db, root, "2026-07-22")

    def test_private_persistence_rejects_symlinked_ancestor_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            (outside / "2026-07").mkdir(parents=True, mode=0o700)
            state_root = root / "state"
            state_root.mkdir(mode=0o700)
            (state_root / "briefings").symlink_to(outside, target_is_directory=True)
            target = state_root / "briefings" / "2026-07" / "artifact.md"

            with self.assertRaises(hermes_supervisor.BriefingError):
                hermes_supervisor._atomic_private_write(target, b"private\n")

            self.assertFalse((outside / "2026-07" / "artifact.md").exists())

    def test_machine_seed_is_the_only_capture_exclusion(self) -> None:
        class Client:
            def __init__(self):
                self.projections = []

            def create(self, projection):
                self.projections.append(projection)
                return hermes_supervisor.CreatedCardRef(str(len(self.projections)), projection.title, "triage")

        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = ChangeDetectionTests.make_databases(directory)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute("INSERT INTO sessions VALUES ('console', 'cli', 'capture', 0, NULL)")
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 'console', 'user', ?, ?, 1, 0)",
                    [(1, hermes_supervisor.BRIEFING_MACHINE_SEED, 1), (2, "D1 適用", 2)],
                )
            client = Client()
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")

            result = hermes_supervisor.CaptureService(client).run_once(store, state_db, kanban_db)

            self.assertEqual(len(client.projections), 1)
            self.assertIn("D1 適用", client.projections[0].body)
            self.assertEqual(result.state.last_message_id, 2)


class Task9ConsoleReplyTests(unittest.TestCase):
    MONTH = "2026-07"

    @staticmethod
    def make_console(path: Path, *, session_id: str = "supervisor-console-2026-07",
                     title: str = "Supervisor Console — 2026-07", source: str = "cli",
                     archived: object = 0) -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, source TEXT, title TEXT, archived, ended_at REAL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
                    timestamp REAL, active, compacted INTEGER,
                    reasoning TEXT, tool_calls TEXT
                );
            """)
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, NULL)",
                (session_id, source, title, archived),
            )

    @staticmethod
    def open_state(root: Path, *, dangerous: bool = False,
                   second: bool = False) -> Path:
        state = hermes_supervisor._briefing_default_state("2026-07")
        decisions = [
            ("safe", "D1", "task-1", 11, dangerous),
        ]
        if second:
            decisions.append(("other", "D2", "task-2", 12, False))
        for key, identifier, task_id, event_id, is_dangerous in decisions:
            state["decision_ids"][key] = identifier
            state["open_decisions"][key] = {
                "key": key, "question": "判断?", "options": ["A", "B"],
                "recommendation": "B", "dangerous": is_dangerous, "importance": 5,
            }
            state["decision_targets"][key] = {"task_id": task_id, "event_id": event_id}
        state["next_decision"] = len(decisions) + 1
        path = root / "briefings" / "state.json"
        hermes_supervisor._write_briefing_state(path, state, "2026-07")
        return path

    class Repository:
        def __init__(self, fail_task: str | None = None):
            self.confirmed: set[tuple[str, str]] = set()
            self.calls: list[tuple[str, str, str]] = []
            self.fail_task = fail_task

        def confirm_comment(self, task_id: str, body: str, marker: str) -> None:
            self.calls.append((task_id, body, marker))
            if (task_id, marker) in self.confirmed:
                return
            if task_id == self.fail_task:
                raise hermes_supervisor.BriefingError("comment_postcondition_unconfirmed")
            self.confirmed.add((task_id, marker))

    @staticmethod
    def shown(task_id: str = "task-1", owner: str = "supervisor",
              status: str = "review", comments: list[dict[str, object]] | None = None
              ) -> dict[str, object]:
        task = {
            "id": task_id, "title": "private", "body": "PRIVATE", "assignee": "supervisor",
            "status": status, "priority": 0, "tenant": None, "workspace_kind": "scratch",
            "workspace_path": None, "branch_name": None, "created_by": owner,
            "created_at": 1, "started_at": None, "completed_at": None, "result": None,
            "skills": [], "max_retries": 2, "session_id": None,
            "workflow_template_id": None, "current_step_key": None,
        }
        return {
            "task": task, "latest_summary": None, "parents": [], "children": [],
            "comments": comments or [], "events": [], "runs": [],
        }

    def test_repository_reads_exact_active_session_in_id_order_and_skips_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            self.make_console(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (3, "supervisor-console-2026-07", "user", "D1 B", 3, 1, 0, "SECRET", "SECRET"),
                        (1, "supervisor-console-2026-07", "user", hermes_supervisor.BRIEFING_MACHINE_SEED, 1, 1, 0, "SECRET", "SECRET"),
                        (2, "supervisor-console-2026-07", "assistant", "private", 2, 1, 0, "SECRET", "SECRET"),
                        (4, "supervisor-console-2026-07", "user", "inactive", 4, 0, 0, "SECRET", "SECRET"),
                    ],
                )
            self.assertEqual(
                hermes_supervisor._read_console_replies(db, self.MONTH, 0),
                [(1, hermes_supervisor.BRIEFING_MACHINE_SEED), (3, "D1 B")],
            )

    def test_repository_rejects_session_identity_schema_limits_and_bad_values(self) -> None:
        variants = (
            {"session_id": "other"}, {"title": "Supervisor Console — 2026-06"},
            {"source": "web"}, {"archived": 1},
        )
        missing = variants[0]
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            self.make_console(db, **missing)
            self.assertEqual(hermes_supervisor._read_console_replies(db, self.MONTH, 0), [])
        for variant in variants[1:]:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / "state.db"
                self.make_console(db, **variant)
                with self.assertRaises(hermes_supervisor.BriefingError):
                    hermes_supervisor._read_console_replies(db, self.MONTH, 0)
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "state.db"
            self.make_console(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executemany(
                    "INSERT INTO messages VALUES (?, 'supervisor-console-2026-07', 'user', 'D1 A', ?, 1, 0, NULL, NULL)",
                    [(index, index) for index in range(1, 258)],
                )
            with self.assertRaisesRegex(hermes_supervisor.BriefingError, "limit"):
                hermes_supervisor._read_console_replies(db, self.MONTH, 0)

    def test_safe_answer_comments_then_atomically_closes_and_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            root.mkdir(mode=0o700)
            db = Path(directory) / "state.db"
            self.make_console(db)
            state_path = self.open_state(root)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (7, 'supervisor-console-2026-07', 'user', 'D1 A', 7, 1, 0, NULL, NULL)"
                )
            repository = self.Repository()

            report = hermes_supervisor.run_briefing_reply_cycle(
                db, root, self.MONTH, repository
            )

            state = json.loads(state_path.read_text())
            self.assertEqual(report, {"closed": 1, "ignored": 0, "processed": 1})
            self.assertEqual(state["reply_cursor"], 7)
            self.assertEqual(state["open_decisions"], {})
            self.assertEqual(state["decision_targets"], {})
            closed = state["closed_decisions"]["safe"]
            self.assertEqual((closed["id"], closed["answer"], closed["reply_message_id"]),
                             ("D1", "A", 7))
            body = json.loads(repository.calls[0][1])
            self.assertEqual(set(body), {
                "schema_version", "decision_id", "decision_key", "selected_option",
                "origin_task_id", "origin_event_id", "reply_message_id", "marker",
            })
            self.assertEqual(body["origin_task_id"], "task-1")
            self.assertEqual(body["marker"], repository.calls[0][2])
            self.assertNotIn("D1 A", repository.calls[0][1])

    def test_new_month_request_with_old_pending_reads_and_writes_old_console_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            root.mkdir(mode=0o700)
            db = Path(directory) / "state.db"
            self.make_console(db)
            state_path = self.open_state(root)
            state = json.loads(state_path.read_text())
            state["pending"] = {
                "date": "2026-07-31", "cursor": 11,
                "marker": "<!-- supervisor-briefing:2026-07-31:e11 -->",
                "artifact": "2026-07-31.md", "discord_status": "none",
                "session_done": False, "included_anomalies": [],
            }
            hermes_supervisor._write_briefing_state(state_path, state, self.MONTH)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (7, 'supervisor-console-2026-07', 'user', 'D1 A', 7, 1, 0, NULL, NULL)"
                )
            repository = self.Repository()

            report = hermes_supervisor.run_briefing_reply_cycle(
                db, root, "2026-08", repository
            )

            persisted = json.loads(state_path.read_text())
            self.assertEqual(report, {"closed": 1, "ignored": 0, "processed": 1})
            self.assertEqual(persisted["month"], self.MONTH)
            self.assertEqual(persisted["reply_cursor"], 7)
            self.assertEqual(persisted["open_decisions"], {})
            self.assertEqual(len(repository.calls), 1)

    def test_dangerous_unresolved_and_invalid_replies_advance_without_comments(self) -> None:
        for content in ("残りは推奨", "D9 A", "malformed"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "private"
                root.mkdir(mode=0o700)
                db = Path(directory) / "state.db"
                self.make_console(db)
                state_path = self.open_state(root, dangerous=True)
                with closing(sqlite3.connect(db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO messages VALUES (9, 'supervisor-console-2026-07', 'user', ?, 9, 1, 0, NULL, NULL)",
                        (content,),
                    )
                repository = self.Repository()
                report = hermes_supervisor.run_briefing_reply_cycle(db, root, self.MONTH, repository)
                state = json.loads(state_path.read_text())
                self.assertEqual((report["closed"], report["ignored"]), (0, 1))
                self.assertEqual(state["reply_cursor"], 9)
                self.assertEqual(repository.calls, [])
                self.assertNotIn(content, json.dumps(report))

    def test_partial_multi_answer_and_state_write_crash_converge_without_duplicate_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            root.mkdir(mode=0o700)
            db = Path(directory) / "state.db"
            self.make_console(db)
            state_path = self.open_state(root, second=True)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (10, 'supervisor-console-2026-07', 'user', 'D1 A / D2 B', 10, 1, 0, NULL, NULL)"
                )
            repository = self.Repository(fail_task="task-2")
            with self.assertRaises(hermes_supervisor.BriefingError):
                hermes_supervisor.run_briefing_reply_cycle(db, root, self.MONTH, repository)
            self.assertEqual(json.loads(state_path.read_text())["reply_cursor"], 0)
            repository.fail_task = None
            hermes_supervisor.run_briefing_reply_cycle(db, root, self.MONTH, repository)
            first_task_calls = [call for call in repository.calls if call[0] == "task-1"]
            self.assertEqual(len(first_task_calls), 2)
            self.assertEqual(len({call[2] for call in first_task_calls}), 1)
            self.assertEqual(len(repository.confirmed), 2)

    def test_public_adapter_uses_explicit_board_show_comment_show_and_strict_owner(self) -> None:
        calls: list[list[str]] = []
        comments: list[dict[str, object]] = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if "comment" in argv:
                comments.append({"author": "supervisor-reply", "body": argv[-3], "created_at": 3})
                return subprocess.CompletedProcess(argv, 0, "commented\n", "")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.shown(comments=comments)), "")
        adapter = hermes_supervisor.HermesDecisionRepository(
            "/fake/hermes", "pinned-board", runner=runner, base_env={}
        )
        body = '{"marker":"supervisor-decision-reply:' + "a" * 64 + '"}'
        marker = "supervisor-decision-reply:" + "a" * 64

        adapter.confirm_comment("task-1", body, marker)

        self.assertEqual(calls, [
            ["/fake/hermes", "kanban", "--board", "pinned-board", "show", "task-1", "--json"],
            ["/fake/hermes", "kanban", "--board", "pinned-board", "comment", "task-1", body,
             "--author", "supervisor-reply"],
            ["/fake/hermes", "kanban", "--board", "pinned-board", "show", "task-1", "--json"],
        ])
        for owner, status in (
            ("user", "review"), ("supervisor-evil", "review"),
            ("supervisor", "bogus"), ("supervisor", "archived"),
        ):
            refused_calls: list[list[str]] = []
            refused = hermes_supervisor.HermesDecisionRepository(
                "/fake/hermes", "pinned-board",
                runner=lambda argv, owner=owner, status=status, **kwargs: (
                    refused_calls.append(argv)
                    or subprocess.CompletedProcess(
                        argv, 0, json.dumps(self.shown(owner=owner, status=status)), ""
                    )
                ), base_env={},
            )
            with self.subTest(owner=owner, status=status), self.assertRaises(
                hermes_supervisor.BriefingError
            ):
                refused.confirm_comment("task-1", body, marker)
            self.assertEqual(sum("comment" in call for call in refused_calls), 0)

        duplicate_calls: list[list[str]] = []
        duplicate = [
            {"author": "supervisor-reply", "body": body, "created_at": 3},
            {"author": "supervisor-reply", "body": body, "created_at": 4},
        ]
        duplicate_adapter = hermes_supervisor.HermesDecisionRepository(
            "/fake/hermes", "pinned-board",
            runner=lambda argv, **kwargs: (
                duplicate_calls.append(argv)
                or subprocess.CompletedProcess(
                    argv, 0, json.dumps(self.shown(comments=duplicate)), ""
                )
            ),
            base_env={},
        )
        with self.assertRaisesRegex(hermes_supervisor.BriefingError, "marker"):
            duplicate_adapter.confirm_comment("task-1", body, marker)
        self.assertEqual(sum("comment" in call for call in duplicate_calls), 0)

    def test_comment_timeout_reconciles_but_unconfirmed_ambiguity_fails_closed(self) -> None:
        marker = "supervisor-decision-reply:" + "b" * 64
        body = json.dumps({"marker": marker}, separators=(",", ":"))
        comments: list[dict[str, object]] = []
        def reconciled(argv, **kwargs):
            if "comment" in argv:
                comments.append({"author": "supervisor-reply", "body": body, "created_at": 2})
                raise subprocess.TimeoutExpired(argv, 1, output="PRIVATE")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.shown(comments=comments)), "")
        hermes_supervisor.HermesDecisionRepository(
            "/fake/hermes", "board", runner=reconciled, base_env={}
        ).confirm_comment("task-1", body, marker)

        calls = []
        def ambiguous(argv, **kwargs):
            calls.append(argv)
            if "comment" in argv:
                raise subprocess.TimeoutExpired(argv, 1, output="PRIVATE")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.shown()), "")
        with self.assertRaisesRegex(hermes_supervisor.BriefingError, "postcondition") as caught:
            hermes_supervisor.HermesDecisionRepository(
                "/fake/hermes", "board", runner=ambiguous, base_env={}
            ).confirm_comment("task-1", body, marker)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual(sum("comment" in call for call in calls), 1)

    def test_duplicate_marker_and_unknown_repository_fields_are_rejected_without_comment(self) -> None:
        marker = "supervisor-decision-reply:" + "d" * 64
        body = json.dumps({"marker": marker}, separators=(",", ":"))
        duplicate = {"author": "supervisor-reply", "body": body, "created_at": 1}
        for shown in (
            self.shown(comments=[duplicate, duplicate]),
            {**self.shown(), "unknown": True},
            {**self.shown(), "comments": [{**duplicate, "unknown": True}]},
        ):
            calls = []
            repository = hermes_supervisor.HermesDecisionRepository(
                "/fake/hermes", "board", base_env={},
                runner=lambda argv, shown=shown, **kwargs: (
                    calls.append(argv)
                    or subprocess.CompletedProcess(argv, 0, json.dumps(shown), "")
                ),
            )
            with self.subTest(shape=set(shown)), self.assertRaises(
                hermes_supervisor.BriefingError
            ):
                repository.confirm_comment("task-1", body, marker)
            self.assertFalse(any("comment" in call for call in calls))

    def test_state_write_crash_after_comment_converges_on_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            root.mkdir(mode=0o700)
            db = Path(directory) / "state.db"
            self.make_console(db)
            state_path = self.open_state(root)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (13, 'supervisor-console-2026-07', 'user', 'D1 A', 13, 1, 0, NULL, NULL)"
                )
            repository = self.Repository()
            real_write = hermes_supervisor._write_briefing_state
            with mock.patch.object(
                hermes_supervisor, "_write_briefing_state",
                side_effect=hermes_supervisor.BriefingError("simulated_state_write_crash"),
            ):
                with self.assertRaises(hermes_supervisor.BriefingError):
                    hermes_supervisor.run_briefing_reply_cycle(db, root, self.MONTH, repository)
            self.assertEqual(json.loads(state_path.read_text())["reply_cursor"], 0)
            real_write  # retain an explicit reference across the patched crash boundary
            hermes_supervisor.run_briefing_reply_cycle(db, root, self.MONTH, repository)
            self.assertEqual(json.loads(state_path.read_text())["reply_cursor"], 13)
            self.assertEqual(len(repository.confirmed), 1)

    def test_cli_is_sanitized_and_absent_state_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            db = Path(directory) / "state.db"
            self.make_console(db)
            argv = [
                "hermes-supervisor", "replies", "--state-db", str(db),
                "--state-root", str(root), "--board", "board", "--hermes", "/fake/hermes",
                "--month", self.MONTH,
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print") as printed:
                self.assertEqual(hermes_supervisor.main(), 0)
            printed.assert_not_called()

            root.mkdir(mode=0o700)
            self.open_state(root)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (8, 'supervisor-console-2026-07', 'user', 'malformed PRIVATE', 8, 1, 0, NULL, NULL)"
                )
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print") as printed:
                self.assertEqual(hermes_supervisor.main(), 0)
            payload = json.loads(printed.call_args.args[0])
            self.assertEqual(payload, {"closed": 0, "ignored": 1, "processed": 1})
            self.assertNotIn("PRIVATE", json.dumps(payload))

    def test_nix_runtime_cli_does_not_collide_with_supervisor_profile_alias(self) -> None:
        module = (REPO_ROOT / "home/modules/ai/hermes-supervisor.nix").read_text()
        self.assertIn('name = "hermes-supervisor-runtime";', module)
        self.assertIn("${supervisorCli}/bin/hermes-supervisor-runtime", module)
        self.assertNotIn("${supervisorCli}/bin/hermes-supervisor ", module)
        self.assertNotIn('RuntimeMaxSec = "9m";', module)
        self.assertIn('TimeoutStartSec = "9m";', module)

    def test_nix_wires_replies_before_watch_inside_one_flock_and_stays_opt_in(self) -> None:
        module = (REPO_ROOT / "home/modules/ai/hermes-supervisor.nix").read_text()
        cycle = module[module.index("watchCycleCommand ="):module.index("watchCommand =")]
        self.assertIn("set -euo pipefail", cycle)
        self.assertLess(cycle.index("set -euo pipefail"), cycle.index(" replies "))
        replies = module.index(" replies ")
        watch = module.index(" watch ", replies)
        flock = module.index("flock", watch)
        cycle_reference = module.index("${watchCycleCommand}", flock)
        self.assertLess(replies, watch)
        self.assertLess(flock, cycle_reference)
        for fragment in ("--state-db", "--state-root", "--board", "--hermes"):
            self.assertIn(fragment, module[replies:watch])
        self.assertNotIn("enable = true", module)

    def test_legacy_open_decision_without_source_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            root.mkdir(mode=0o700)
            state = hermes_supervisor._briefing_default_state(self.MONTH)
            state["schema_version"] = 1
            state["decision_ids"] = {"safe": "D1"}
            state["next_decision"] = 2
            state["open_decisions"] = {"safe": {
                "key": "safe", "question": "判断?", "options": ["A", "B"],
                "recommendation": "B", "dangerous": False, "importance": 5,
            }}
            for key in ("decision_targets", "closed_decisions", "reply_cursor"):
                del state[key]
            path = root / "briefings" / "state.json"
            hermes_supervisor._atomic_private_write(
                path,
                (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            )
            with self.assertRaisesRegex(hermes_supervisor.BriefingError, "re-projection"):
                hermes_supervisor._read_briefing_state(path, self.MONTH)

    def test_closed_old_event_is_not_reopened_and_cross_task_key_conflicts(self) -> None:
        for task_id, should_fail in (("task-1", False), ("task-other", True)):
            with self.subTest(task_id=task_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "private"
                root.mkdir(mode=0o700)
                db = Path(directory) / "kanban.db"
                BriefingProjectionTests.make_kanban(db)
                decision = {
                    "key": "safe", "question": "判断?", "options": ["A", "B"],
                    "recommendation": "B", "dangerous": False, "importance": 5,
                }
                with closing(sqlite3.connect(db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, 'title', NULL, NULL, 'review', 'supervisor', NULL, ?, NULL, NULL)",
                        (task_id, json.dumps({"decision": decision})),
                    )
                    connection.execute(
                        "INSERT INTO task_events VALUES (20, ?, NULL, 'decision_required', '{}', '2026-07-01')",
                        (task_id,),
                    )
                state = hermes_supervisor._briefing_default_state(self.MONTH)
                state["decision_ids"] = {"safe": "D1"}
                state["next_decision"] = 2
                state["closed_decisions"] = {"safe": {
                    "id": "D1", "answer": "A", "task_id": "task-1", "event_id": 11,
                    "reply_message_id": 7,
                    "marker": "supervisor-decision-reply:" + "c" * 64,
                }}
                path = root / "briefings" / "state.json"
                hermes_supervisor._write_briefing_state(path, state, self.MONTH)
                if should_fail:
                    with self.assertRaisesRegex(hermes_supervisor.BriefingError, "target"):
                        hermes_supervisor.prepare_briefing(db, root, "2026-07-22")
                else:
                    prepared = hermes_supervisor.prepare_briefing(db, root, "2026-07-22")
                    self.assertIsNotNone(prepared)
                    self.assertEqual(prepared.decisions, ())
                    persisted = json.loads(path.read_text())
                    self.assertEqual(persisted["open_decisions"], {})


class Task10SupervisorControlTests(unittest.TestCase):
    @staticmethod
    def task(identifier: str, owner: str) -> dict[str, object]:
        return {
            "id": identifier, "title": "private title", "body": "PRIVATE BODY",
            "assignee": "builder", "status": "running", "priority": 0,
            "tenant": None, "workspace_kind": "scratch", "workspace_path": None,
            "branch_name": None, "project_id": None, "created_by": owner,
            "created_at": 1, "started_at": 2, "completed_at": None,
            "result": None, "skills": [], "max_retries": 2,
            "session_id": None, "workflow_template_id": None,
            "current_step_key": None,
        }

    def test_exact_natural_language_mapping_and_rejection(self) -> None:
        running = hermes_supervisor.initial_supervisor_state()
        expected = {
            "一時停止": "pause", "凍結": "freeze", "緊急停止": "emergency-stop",
            "再開": "resume", "pause": "pause", "freeze": "freeze",
            "emergency stop": "emergency-stop", "emergency-stop": "emergency-stop",
            "resume": "resume",
        }
        for text, action in expected.items():
            with self.subTest(text=text):
                mapped = hermes_supervisor.map_control_request(text, running)
                self.assertEqual((mapped.action, mapped.needs_clarification), (action, False))
        ambiguous = hermes_supervisor.map_control_request("止めて", running)
        self.assertEqual(
            (ambiguous.action, ambiguous.needs_clarification, ambiguous.reason_code),
            (None, True, "control_level_required"),
        )
        emergency = replace(
            running, control_state="emergency_stopped", emergency_stop_requested_at=9
        )
        fail_closed = hermes_supervisor.map_control_request("止めて", emergency)
        self.assertEqual(fail_closed.action, "emergency-stop")
        self.assertEqual(fail_closed.reason_code, "active_emergency_fail_closed")
        for hostile in (None, True, "", "stop", "PAUSE", " pause", "pause\n",
                        "pause\x00", "pause\u202e", "x" * 65):
            with self.subTest(hostile=repr(hostile)), self.assertRaises(
                hermes_supervisor.ControlError
            ):
                hermes_supervisor.map_control_request(hostile, running)

    def test_pause_organizes_but_does_not_dispatch(self) -> None:
        policy = load_policy(POLICY)
        state = replace(hermes_supervisor.initial_supervisor_state(), control_state="paused")
        decision = hermes_supervisor.decide_gate(
            policy, state, hermes_supervisor.GateRequest("supervisor_run"),
            datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual((decision.action, decision.reason_code),
                         ("allow", "supervisor_run_allowed"))
        self.assertTrue(hermes_supervisor.card_formation_allowed(state))
        self.assertFalse(hermes_supervisor.dispatch_allowed(state))

    def test_audit_is_private_bounded_and_rejects_intermediate_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private"
            private.mkdir(mode=0o700)
            audit = hermes_supervisor.ControlAuditLog(private / "audit.jsonl")
            audit.append({"schema_version": 1, "kind": "checkpoint"})
            self.assertEqual(audit.read_records()[0]["kind"], "checkpoint")
            self.assertEqual(audit.path.stat().st_mode & 0o777, 0o600)
            linked = root / "linked"
            linked.symlink_to(private, target_is_directory=True)
            hostile = hermes_supervisor.ControlAuditLog(linked / "audit.jsonl")
            with self.assertRaises(hermes_supervisor.StateError):
                hostile.read_records()
            with self.assertRaises(hermes_supervisor.StateError):
                hostile.append({"schema_version": 1, "kind": "hostile"})

    def test_list_schema_managed_ownership_and_exact_board_argv(self) -> None:
        calls = []
        response = [
            self.task("managed-a", "supervisor"),
            self.task("managed-b", "supervisor-watcher"),
            self.task("spoofed", "supervisor-evil"),
            self.task("user-a", "user"),
            self.task("unsafe", "supervisor--bad"),
        ]
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")
        adapter = hermes_supervisor.HermesControlAdapter(
            "/fake/hermes", "fixture", runner=runner, base_env={"SAFE": "1"}
        )
        self.assertEqual(adapter.list_managed_running(), ("managed-a", "managed-b"))
        self.assertEqual(calls[0][0], [
            "/fake/hermes", "kanban", "--board", "fixture", "list",
            "--status", "running", "--json",
        ])
        valid = self.task("managed-a", "supervisor")
        for field, value in {
            "title": 1, "body": [], "assignee": True, "priority": False,
            "tenant": 1, "workspace_kind": None, "workspace_path": 1,
            "branch_name": [], "project_id": {}, "created_at": float("nan"),
            "started_at": "now", "completed_at": False, "result": "PRIVATE",
            "skills": [1], "max_retries": True, "session_id": 1,
            "workflow_template_id": [], "current_step_key": {},
        }.items():
            hostile = [{**valid, field: value}]
            malformed = hermes_supervisor.HermesControlAdapter(
                "/fake/hermes", "fixture",
                runner=lambda argv, **kwargs: subprocess.CompletedProcess(
                    argv, 0, json.dumps(hostile), ""
                ),
            )
            with self.subTest(field=field), self.assertRaises(
                hermes_supervisor.ControlError
            ):
                malformed.list_managed_running()

    def test_emergency_status_reconciliation_uses_explicit_bounded_board_reads(self) -> None:
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            status = argv[argv.index("--status") + 1]
            response = []
            if status == "ready":
                task = self.task("task-a", "supervisor-control")
                task["status"] = "ready"
                response = [task]
            return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")
        adapter = hermes_supervisor.HermesControlAdapter(
            "/fake/hermes", "fixture", runner=runner, base_env={}
        )
        self.assertEqual(adapter.emergency_task_status("task-a"), "ready")
        self.assertEqual(
            [argv[argv.index("--status") + 1] for argv in calls],
            ["running", "ready", "blocked", "triage"],
        )
        for argv in calls:
            self.assertEqual(argv[:5], [
                "/fake/hermes", "kanban", "--board", "fixture", "list",
            ])
            self.assertEqual(argv[-1], "--json")

    def test_emergency_exact_reclaim_block_and_external_calls_hold_no_state_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            calls = []
            outer = self
            class Adapter:
                def list_managed_running(self):
                    kinds = [record["kind"] for record in audit.read_records()]
                    outer.assertIn("emergency_enumeration_intent", kinds)
                    with hermes_supervisor.StateLock(store.lock_path):
                        pass
                    return ("task-a",)
                def reclaim_task(self, task_id):
                    with hermes_supervisor.StateLock(store.lock_path):
                        pass
                    calls.append(("reclaim", task_id))
                def block_task(self, task_id):
                    with hermes_supervisor.StateLock(store.lock_path):
                        pass
                    calls.append(("block", task_id))
            class Notifier:
                def send(self, summary):
                    with hermes_supervisor.StateLock(store.lock_path):
                        pass
            result = hermes_supervisor.execute_control(
                store, audit, Adapter(), Notifier(), "emergency-stop", now=123
            )
            self.assertEqual(calls, [("reclaim", "task-a"), ("block", "task-a")])
            self.assertEqual((result.succeeded, result.failed), (1, 0))
            self.assertEqual(store.read().emergency_stop_requested_at, 123)
            kinds = [record["kind"] for record in audit.read_records()]
            self.assertLess(kinds.index("emergency_reclaim_intent"),
                            kinds.index("emergency_reclaim_result"))
            self.assertLess(kinds.index("emergency_block_intent"),
                            kinds.index("emergency_block_result"))

        argv_calls = []
        adapter = hermes_supervisor.HermesControlAdapter(
            "/fake/hermes", "fixture",
            runner=lambda argv, **kwargs: (
                argv_calls.append(argv) or subprocess.CompletedProcess(argv, 0, "ok", "")
            ),
        )
        adapter.reclaim_task("task-a")
        adapter.block_task("task-a")
        self.assertEqual(argv_calls, [
            ["/fake/hermes", "kanban", "--board", "fixture", "reclaim", "task-a",
             "--reason", "supervisor_emergency_stop"],
            ["/fake/hermes", "kanban", "--board", "fixture", "block", "task-a",
             "supervisor_emergency_stop", "--kind", "transient"],
        ])

    def test_emergency_retries_block_after_reclaim_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def __init__(self):
                    self.calls = []
                    self.list_calls = 0
                    self.block_calls = 0
                def list_managed_running(self):
                    self.list_calls += 1
                    return ("task-a",) if self.list_calls == 1 else ()
                def reclaim_task(self, task_id):
                    self.calls.append(("reclaim", task_id))
                def block_task(self, task_id):
                    self.calls.append(("block", task_id))
                    self.block_calls += 1
                    if self.block_calls == 1:
                        raise hermes_supervisor.ControlError("fixture block failure")
            class Notifier:
                def send(self, summary): pass
            adapter = Adapter()
            with self.assertRaisesRegex(
                hermes_supervisor.ControlError,
                "one or more managed tasks could not be stopped",
            ):
                hermes_supervisor.execute_control(
                    store, audit, adapter, Notifier(), "emergency-stop", now=150
                )
            result = hermes_supervisor.execute_control(
                store, audit, adapter, Notifier(), "emergency-stop", now=151
            )
            self.assertEqual(result.failed, 0)
            self.assertEqual(adapter.calls, [
                ("reclaim", "task-a"),
                ("block", "task-a"),
                ("block", "task-a"),
            ])
            self.assertEqual(adapter.list_calls, 1)

    def test_emergency_reconciles_reclaim_success_before_missing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def __init__(self):
                    self.phase = "running"
                    self.reclaims = 0
                    self.blocks = 0
                    self.list_calls = 0
                def list_managed_running(self):
                    self.list_calls += 1
                    return ("task-a",)
                def reclaim_task(self, task_id):
                    self.reclaims += 1
                    if self.phase != "running":
                        raise hermes_supervisor.ControlError("not running")
                    self.phase = "ready"
                    raise KeyboardInterrupt("after reclaim before checkpoint")
                def block_task(self, task_id):
                    self.blocks += 1
                    self.phase = "blocked"
                def emergency_task_status(self, task_id):
                    return self.phase
            class Notifier:
                def send(self, summary): pass
            adapter = Adapter()
            with self.assertRaises(KeyboardInterrupt):
                hermes_supervisor.execute_control(
                    store, audit, adapter, Notifier(), "emergency-stop", now=160
                )
            result = hermes_supervisor.execute_control(
                store, audit, adapter, Notifier(), "emergency-stop", now=161
            )
            self.assertEqual((result.succeeded, result.failed), (1, 0))
            self.assertEqual((adapter.reclaims, adapter.blocks, adapter.list_calls), (2, 1, 1))

    def test_emergency_reconciles_block_success_before_missing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def __init__(self):
                    self.phase = "running"
                    self.blocks = 0
                def list_managed_running(self): return ("task-a",)
                def reclaim_task(self, task_id): self.phase = "ready"
                def block_task(self, task_id):
                    self.blocks += 1
                    if self.phase != "ready":
                        raise hermes_supervisor.ControlError("not blockable")
                    self.phase = "blocked"
                    raise KeyboardInterrupt("after block before checkpoint")
                def emergency_task_status(self, task_id): return self.phase
            class Notifier:
                def send(self, summary): pass
            adapter = Adapter()
            with self.assertRaises(KeyboardInterrupt):
                hermes_supervisor.execute_control(
                    store, audit, adapter, Notifier(), "emergency-stop", now=170
                )
            result = hermes_supervisor.execute_control(
                store, audit, adapter, Notifier(), "emergency-stop", now=171
            )
            self.assertEqual((result.succeeded, result.failed), (1, 0))
            self.assertEqual(adapter.blocks, 2)

    def test_alert_attempt_checkpoint_prevents_ambiguous_crash_resend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def list_managed_running(self): return ()
                def reclaim_task(self, task_id): raise AssertionError(task_id)
                def block_task(self, task_id): raise AssertionError(task_id)
            class Notifier:
                calls = 0
                def send(self, summary):
                    self.calls += 1
                    if self.calls == 1:
                        raise KeyboardInterrupt("ambiguous")
            notifier = Notifier()
            with self.assertRaises(KeyboardInterrupt):
                hermes_supervisor.execute_control(
                    store, audit, Adapter(), notifier, "emergency-stop", now=200
                )
            self.assertIn("emergency_alert_attempted",
                          [record["kind"] for record in audit.read_records()])
            retried = hermes_supervisor.execute_control(
                store, audit, Adapter(), notifier, "emergency-stop", now=201
            )
            self.assertEqual(retried.state.emergency_stop_requested_at, 200)
            self.assertEqual(notifier.calls, 1)

    def test_ntfy_failure_is_ambiguous_and_never_automatically_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def list_managed_running(self): return ()
                def reclaim_task(self, task_id): raise AssertionError(task_id)
                def block_task(self, task_id): raise AssertionError(task_id)
            class Notifier:
                def __init__(self): self.calls = 0
                def send(self, summary):
                    self.calls += 1
                    if self.calls == 1:
                        raise hermes_supervisor.ControlError("ambiguous fixture failure")
            notifier = Notifier()
            with self.assertRaisesRegex(hermes_supervisor.ControlError, "emergency alert failed"):
                hermes_supervisor.execute_control(
                    store, audit, Adapter(), notifier, "emergency-stop", now=250
                )
            result = hermes_supervisor.execute_control(
                store, audit, Adapter(), notifier, "emergency-stop", now=251
            )
            self.assertEqual(result.failed, 0)
            self.assertEqual(notifier.calls, 1)
            kinds = [record["kind"] for record in audit.read_records()]
            self.assertIn("emergency_alert_ambiguous", kinds)
            self.assertNotIn("emergency_alert_failed", kinds)

    def test_resume_crash_retry_is_idempotent_and_clears_only_after_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = hermes_supervisor.StateStore(root / "state.json")
            store.write(replace(
                hermes_supervisor.initial_supervisor_state(frozen=True),
                last_message_id=7, pending_message_ids=(7,),
            ))
            audit = hermes_supervisor.ControlAuditLog(root / "audit.jsonl")
            class Adapter:
                def __init__(self):
                    self.calls = []
                    self.visible_states = []
                def schedule_reevaluation(self, messages, events):
                    self.visible_states.append(store.read().control_state)
                    self.calls.append((messages, events))
                    if len(self.calls) == 1:
                        raise KeyboardInterrupt("after idempotent create")
                    return "resume-task"
            adapter = Adapter()
            with self.assertRaises(KeyboardInterrupt):
                hermes_supervisor.execute_control(
                    store, audit, adapter, None, "resume", now=300
                )
            self.assertEqual(store.read().pending_message_ids, (7,))
            result = hermes_supervisor.execute_control(
                store, audit, adapter, None, "resume", now=301
            )
            self.assertEqual(adapter.calls, [((7,), ()), ((7,), ())])
            self.assertEqual(adapter.visible_states, ["frozen", "frozen"])
            self.assertEqual(result.state.pending_message_ids, ())
            self.assertEqual(result.reevaluation_task_id, "resume-task")

    def test_transaction_lock_is_private_and_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transaction.lock"
            with hermes_supervisor.ControlTransactionLock(path):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(hermes_supervisor.StateBusyError):
                    with hermes_supervisor.ControlTransactionLock(path):
                        pass

    def test_cli_control_uses_transaction_and_non_emergency_has_no_notifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = replace(hermes_supervisor.initial_supervisor_state(), control_state="paused")
            result = hermes_supervisor.ControlExecutionResult("pause", state)
            argv = [
                "hermes-supervisor", "state", "control", "--state", str(root / "state"),
                "--audit", str(root / "audit"), "--board", "fixture",
                "--hermes", "/fake/hermes", "pause",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                hermes_supervisor, "execute_control", return_value=result
            ) as execute, mock.patch.object(
                hermes_supervisor, "NtfyEmergencyNotifier"
            ) as notifier, mock.patch("builtins.print") as printed:
                self.assertEqual(hermes_supervisor.main(), 0)
            notifier.assert_not_called()
            self.assertIsNone(execute.call_args.args[3])
            summary = json.loads(printed.call_args.args[0])
            self.assertEqual(summary["control_state"], "paused")
            for forbidden in ("body", "result", "path", "secret"):
                self.assertNotIn(forbidden, json.dumps(summary).casefold())

    def test_module_wrapper_and_prompt_control_contract(self) -> None:
        module = (REPO_ROOT / "home/modules/ai/hermes-supervisor.nix").read_text()
        for fragment in (
            "control.enable", "default = false", "controlCommand", "watch.lock",
            "--audit", "--board", "--hermes", "--ntfy-url", "--curl",
            "http://192.168.11.9:8080/nas-alerts",
        ):
            self.assertIn(fragment, module)
        control_module = module[module.index("controlCommand"):]
        self.assertNotIn("--conflict-exit-code 0", control_module)
        self.assertIn("--conflict-exit-code 75", control_module)
        self.assertIn("--state '${stateRoot}/state.json'", module)
        self.assertIn("--audit '${stateRoot}/control-audit.jsonl'", module)
        self.assertNotIn("hermes-supervisor-control.timer", module)
        prompt = (REPO_ROOT / "home/modules/ai/hermes-supervisor/prompts/supervisor.md").read_text()
        for fragment in (
            "一時停止", "pause", "凍結", "freeze", "緊急停止", "emergency stop",
            "再開", "resume", "止めて", "clarification", "tools enforce",
            "does not implement",
        ):
            self.assertIn(fragment, prompt)


class BriefingReplyParserTests(unittest.TestCase):
    def test_remaining_recommendations_never_auto_answer_dangerous_decisions(self) -> None:
        decisions = (
            hermes_supervisor.BriefingDecision("D1", "safe", "安全な選択?", ("A", "B"), "B", False, 4),
            hermes_supervisor.BriefingDecision("D2", "danger", "危険な選択?", ("適用", "中止"), "適用", True, 9),
        )

        parsed = hermes_supervisor.parse_briefing_reply(
            "D1 A / 残りは推奨", decisions
        )

        self.assertEqual(parsed.answers, {"D1": "A"})
        self.assertEqual(parsed.unresolved_dangerous, ("D2",))
        for invalid in ("D9 A", "D1 A / D1 B", "D1", "x" * 4097):
            with self.subTest(invalid=invalid[:20]):
                with self.assertRaises(hermes_supervisor.BriefingError):
                    hermes_supervisor.parse_briefing_reply(invalid, decisions)


class Task11AuditEcoRetentionTests(unittest.TestCase):
    def audit_record(self, **updates: Any) -> dict[str, Any]:
        record = {
            "schema_version": 2,
            "batch_id": "watch-100-7",
            "status": "completed",
            "invocation_at": 100.0,
            "failure_code": None,
            "started_at": 100.0,
            "finished_at": 107.0,
            "pre_operation": {
                "state_present": True, "mode": "shadow", "control_state": "running",
                "last_message_id": 0, "last_event_id": 0,
                "last_supervisor_message_id": 0, "last_supervisor_event_id": 0,
            },
            "input_message_ids": [1, 2],
            "input_event_ids": [7],
            "source_ids": ["event:7", "message:1", "message:2"],
            "capture_relations": [
                {"source_message_id": 1, "card_id": "capture-1", "relation_kind": "capture"}
            ],
            "primary_goal_id": "goal-a",
            "primary_card_id": "batch-a",
            "skipped_candidates": [
                {"card_id": "card-b", "reason_code": "lower_priority"}
            ],
            "risk": {"level": "low", "reason_code": "routine_batch"},
            "gate": {"decision": "allow", "reason_code": "supervisor_run_allowed"},
            "budget": {"supervisor_runs": 1, "strong_calls": 1, "cheap_calls": 0},
            "changed_plan_fields": ["primary_goal_id"],
            "confidence": 0.75,
            "unresolved_assumptions": ["owner_confirmation_pending"],
            "calls": [
                {
                    "attempt_id": "attempt-1", "result_id": "result-1",
                    "kind": "llm", "model_tier": "strong",
                    "retry": False, "escalation": False, "input_tokens": 10,
                    "output_tokens": 5, "total_tokens": 15,
                    "estimated_cost": {"amount": 0.25, "currency": "USD"},
                    "actual_cost": None,
                }
            ],
            "source_change_count": 3,
            "accepted_result_ids": ["result-1"],
            "human_corrections": 0,
            "review_duration_supplied_seconds": None,
            "review_reply_started_at": None,
            "review_reply_finished_at": None,
            "procedure_conversions": 1,
        }
        record.update(updates)
        return record

    def test_run_audit_is_strict_private_and_rejects_forbidden_or_unknown_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            audit = hermes_supervisor.RunAuditLog(root / "run-audit.jsonl")
            record = self.audit_record()
            audit.append(record)
            self.assertEqual(audit.read_records(), (record,))
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(audit.path.stat().st_mode & 0o777, 0o600)
            for hostile in (
                dict(record, raw_message="secret"),
                dict(record, reasoning="hidden"),
                dict(record, confidence=True),
                dict(record, confidence=float("nan")),
                dict(record, confidence=-0.1),
                dict(record, human_corrections=True),
            ):
                with self.subTest(keys=hostile.keys()), self.assertRaises(
                    hermes_supervisor.AuditError
                ):
                    audit.append(hostile)
            audit.path.write_text('{"schema_version":1,"schema_version":1}\n', encoding="ascii")
            os.chmod(audit.path, 0o600)
            with self.assertRaises(hermes_supervisor.AuditError):
                audit.read_records()

    def test_watch_writes_structured_idle_audit_without_client_or_llm_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            client = WatchCycleTests.Client()
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), client,
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc), audit=audit,
            )
            record = audit.read_records()[0]
        self.assertEqual(result.batch.action, "no_change")
        self.assertEqual(client.capture_calls, [])
        self.assertEqual(client.batch_calls, [])
        self.assertEqual(record["source_change_count"], 0)
        self.assertEqual(record["calls"], [])
        self.assertEqual(record["input_message_ids"], [])
        self.assertEqual(record["input_event_ids"], [])
        self.assertNotIn("reasoning", json.dumps(record))

    def test_watch_audit_ids_distinguish_new_input_inside_same_ten_minute_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory, message=True)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY),
                WatchCycleTests.Client(), now, audit=audit,
            )
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (2, "session-secret", "user", "SECOND PRIVATE INTENT", 2, 1, 0),
                )
            hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY),
                WatchCycleTests.Client(), now + timedelta(minutes=1), audit=audit,
            )
            records = audit.read_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["batch_id"] for record in records}), 2)
        self.assertEqual([record["input_message_ids"] for record in records], [[1], [2]])

    def test_watch_audit_ids_distinguish_idle_polls_inside_same_ten_minute_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            for _ in range(2):
                result = hermes_supervisor.run_watch_cycle(
                    store, state_db, kanban_db, load_policy(POLICY),
                    WatchCycleTests.Client(), now, audit=audit,
                )
                self.assertEqual(result.batch.action, "no_change")
            records = audit.read_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["batch_id"] for record in records}), 2)
        self.assertEqual([record["source_change_count"] for record in records], [0, 0])

    def test_watch_audit_id_allows_retry_after_failure_inside_same_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory, message=True)
            store = hermes_supervisor.StateStore(Path(directory) / "state.json")
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            client = WatchCycleTests.Client(fail_batch=True)
            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            with self.assertRaises(hermes_supervisor.BatchError):
                hermes_supervisor.run_watch_cycle(
                    store, state_db, kanban_db, load_policy(POLICY), client,
                    now, audit=audit,
                )
            client.fail_batch = False
            result = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), client,
                now, audit=audit,
            )
            records = audit.read_records()
        self.assertEqual(result.batch.action, "enqueued")
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["batch_id"] for record in records}), 2)
        self.assertEqual([record["status"] for record in records], ["failed", "completed"])

    def test_watch_audits_capture_correction_relation_without_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory, message=True)
            with closing(sqlite3.connect(state_db)) as connection, connection:
                connection.execute(
                    "UPDATE messages SET content = ? WHERE id = 1",
                    ("訂正: RAW PRIVATE INTENT",),
                )
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            hermes_supervisor.run_watch_cycle(
                hermes_supervisor.StateStore(Path(directory) / "state.json"),
                state_db, kanban_db, load_policy(POLICY), WatchCycleTests.Client(),
                datetime(2026, 7, 22, 12, tzinfo=timezone.utc), audit=audit,
            )
            record = audit.read_records()[0]
        self.assertEqual(record["capture_relations"], [{
            "source_message_id": 1,
            "card_id": "capture-1",
            "relation_kind": "correction_candidate",
        }])
        self.assertNotIn("RAW PRIVATE INTENT", json.dumps(record))
        self.assertEqual(record["human_corrections"], 1)

    def test_terminal_audit_accepts_explicit_human_metrics_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = hermes_supervisor.RunAuditLog(
                Path(directory) / "run-audit.jsonl"
            )
            audit.append(self.audit_record(procedure_conversions=0))
            argv = [
                "hermes-supervisor", "audit-annotate",
                "--audit", str(audit.path),
                "--batch-id", "watch-100-7",
                "--review-duration-seconds", "9",
                "--procedure-conversions", "2",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch(
                "builtins.print"
            ) as printed:
                self.assertEqual(hermes_supervisor.main(), 0)
            self.assertIn('"annotated":true', printed.call_args.args[0])
            updated = audit.read_records()[0]
            self.assertEqual(updated["review_duration_supplied_seconds"], 9.0)
            self.assertEqual(updated["procedure_conversions"], 2)
            conflicting_argv = [
                "hermes-supervisor", "audit-annotate",
                "--audit", str(audit.path),
                "--batch-id", "watch-100-7",
                "--review-duration-seconds", "10",
                "--procedure-conversions", "3",
            ]
            with mock.patch.object(sys, "argv", conflicting_argv), mock.patch(
                "builtins.print"
            ):
                self.assertEqual(hermes_supervisor.main(), 2)
            self.assertEqual(audit.read_records()[0], updated)
            report = hermes_supervisor.build_eco_report(audit.read_records())
            self.assertEqual(
                report["review_duration_chosen_seconds"],
                {"total": 9.0, "count": 1},
            )
            self.assertEqual(report["procedure_conversions"], 2)

    def test_run_audit_append_is_idempotent_and_conflicts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            record = self.audit_record()
            audit.append(record)
            audit.append(dict(record))
            self.assertEqual(audit.read_records(), (record,))
            with self.assertRaises(hermes_supervisor.AuditError):
                audit.append(dict(record, confidence=0.5))
            self.assertEqual(audit.read_records(), (record,))

    def test_distinct_audit_reservation_suffixes_max_length_ids_within_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            pending = self.audit_record(
                batch_id="a" * 128,
                status="pending", failure_code=None, finished_at=100.0,
                capture_relations=[], primary_card_id=None, calls=[],
                accepted_result_ids=[], human_corrections=0, procedure_conversions=0,
            )
            first = audit.append_distinct(pending)
            second = audit.append_distinct(pending)
            records = audit.read_records()
        self.assertEqual(first["batch_id"], "a" * 128)
        self.assertEqual(second["batch_id"], "a" * 125 + "-r1")
        self.assertEqual(len({record["batch_id"] for record in records}), 2)
        self.assertTrue(all(len(record["batch_id"]) <= 128 for record in records))

    def test_run_audit_lifecycle_replaces_pending_and_rejects_conflicting_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = hermes_supervisor.RunAuditLog(Path(directory) / "run-audit.jsonl")
            terminal = self.audit_record()
            pending = self.audit_record(
                status="pending", failure_code=None, finished_at=100.0,
                capture_relations=[], primary_card_id=None, calls=[],
                accepted_result_ids=[], human_corrections=0, procedure_conversions=0,
            )
            audit.append(pending)
            audit.append(terminal)
            audit.append(dict(terminal))
            self.assertEqual(audit.read_records(), (terminal,))
            with self.assertRaises(hermes_supervisor.AuditError):
                audit.append(dict(terminal, confidence=0.5))
            with self.assertRaises(hermes_supervisor.AuditError):
                audit.append(dict(terminal, status="failed", failure_code="watch_failed"))

    def test_watch_pending_survives_base_exception_and_retry_is_separate_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory, message=True)
            root = Path(directory)
            audit = hermes_supervisor.RunAuditLog(root / "run-audit.jsonl")

            class CrashClient(WatchCycleTests.Client):
                def create_supervisor_batch(self, projection):
                    raise KeyboardInterrupt("raw crash must not be stored")

            now = datetime(2026, 7, 22, 12, 4, tzinfo=timezone.utc)
            with self.assertRaises(KeyboardInterrupt):
                hermes_supervisor.run_watch_cycle(
                    hermes_supervisor.StateStore(root / "state.json"), state_db, kanban_db,
                    load_policy(POLICY), CrashClient(), now, audit=audit,
                )
            pending = audit.read_records()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["status"], "pending")
            self.assertNotIn("raw crash", json.dumps(pending))

            hermes_supervisor.run_watch_cycle(
                hermes_supervisor.StateStore(root / "state.json"), state_db, kanban_db,
                load_policy(POLICY), WatchCycleTests.Client(), now, audit=audit,
            )
            records = audit.read_records()
            self.assertEqual(len(records), 2)
            self.assertEqual([record["status"] for record in records], ["pending", "completed"])
            self.assertNotEqual(records[0]["batch_id"], records[1]["batch_id"])
            self.assertEqual(records[0], pending[0])

    def test_watch_caught_failure_finalizes_safe_code_and_ten_minute_buckets_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_db, kanban_db = WatchCycleTests.fixture(directory)
            root = Path(directory)
            audit = hermes_supervisor.RunAuditLog(root / "run-audit.jsonl")
            store = hermes_supervisor.StateStore(root / "state.json")
            with mock.patch.object(
                hermes_supervisor.CaptureService, "run_once",
                side_effect=hermes_supervisor.CaptureError("RAW PRIVATE FAILURE"),
            ):
                with self.assertRaises(hermes_supervisor.CaptureError):
                    hermes_supervisor.run_watch_cycle(
                        store, state_db, kanban_db, load_policy(POLICY),
                        WatchCycleTests.Client(),
                        datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc), audit=audit,
                    )
            failed = audit.read_records()[0]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failure_code"], "capture_failed")
            self.assertNotIn("RAW PRIVATE FAILURE", json.dumps(failed))

            before_retry = (
                store.path.read_bytes() if store.path.exists() else None
            )
            retry_client = WatchCycleTests.Client()
            retry = hermes_supervisor.run_watch_cycle(
                store, state_db, kanban_db, load_policy(POLICY), retry_client,
                datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc), audit=audit,
            )
            self.assertEqual(retry.batch.action, "no_change")
            self.assertEqual(retry_client.capture_calls, [])
            self.assertEqual(retry_client.batch_calls, [])
            self.assertIsNone(before_retry)
            retry_state = store.read()
            self.assertEqual(retry_state.mode, "shadow")
            self.assertEqual(retry_state.control_state, "running")
            self.assertEqual(
                (retry_state.last_message_id, retry_state.last_event_id), (0, 0)
            )
            retry_records = audit.read_records()
            self.assertEqual(len(retry_records), 2)
            self.assertEqual(retry_records[0], failed)
            self.assertEqual(
                [record["status"] for record in retry_records], ["failed", "completed"]
            )
            self.assertNotEqual(
                retry_records[0]["batch_id"], retry_records[1]["batch_id"]
            )

            second_audit = hermes_supervisor.RunAuditLog(root / "second-audit.jsonl")
            for minute in (0, 10):
                hermes_supervisor.run_watch_cycle(
                    store, state_db, kanban_db, load_policy(POLICY), WatchCycleTests.Client(),
                    datetime(2026, 7, 22, 13, minute, tzinfo=timezone.utc), audit=second_audit,
                )
            records = second_audit.read_records()
            self.assertEqual(len(records), 2)
            self.assertEqual(len({record["batch_id"] for record in records}), 2)

    def test_run_audit_cross_process_barrier_preserves_all_distinct_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "run-audit.jsonl"
            gate = root / "gate"
            scripts: list[subprocess.Popen[str]] = []
            for index in range(12):
                record = self.audit_record(batch_id=f"watch-concurrent-{index}")
                program = (
                    "import json,sys,time; from pathlib import Path; "
                    "sys.path.insert(0,sys.argv[1]); import hermes_supervisor as h; "
                    "gate=Path(sys.argv[3]); "
                    "exec('while not gate.exists():\\n time.sleep(.001)'); "
                    "h.RunAuditLog(Path(sys.argv[2])).append(json.loads(sys.argv[4]))"
                )
                scripts.append(subprocess.Popen(
                    [sys.executable, "-c", program, str(CLI.parent), str(audit_path),
                     str(gate), json.dumps(record, separators=(",", ":"))],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                ))
            gate.write_text("go", encoding="ascii")
            failures = []
            for process in scripts:
                stdout, stderr = process.communicate(timeout=15)
                if process.returncode != 0:
                    failures.append((process.returncode, stdout, stderr))
            self.assertEqual(failures, [])
            records = hermes_supervisor.RunAuditLog(audit_path).read_records()
            self.assertEqual(
                {record["batch_id"] for record in records},
                {f"watch-concurrent-{index}" for index in range(12)},
            )

    def test_run_audit_failed_replace_and_stale_temp_preserve_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = hermes_supervisor.RunAuditLog(root / "run-audit.jsonl")
            first = self.audit_record()
            audit.append(first)
            stale = root / ".run-audit.jsonl.tmp.1.stale"
            stale.write_bytes(b"partial")
            os.chmod(stale, 0o600)
            with mock.patch.object(
                hermes_supervisor.os, "replace", side_effect=OSError("injected")
            ), self.assertRaises(hermes_supervisor.AuditError):
                audit.append(dict(first, batch_id="watch-101-8"))
            self.assertEqual(audit.read_records(), (first,))
            self.assertEqual(stale.read_bytes(), b"partial")

    def test_eco_report_separates_review_evidence_and_exposes_ratio_operands(self) -> None:
        idle = self.audit_record(
            batch_id="watch-1-1", started_at=1.0, finished_at=3.0,
            input_message_ids=[], input_event_ids=[], source_ids=[], capture_relations=[],
            primary_goal_id=None, primary_card_id=None,
            skipped_candidates=[{"card_id": None, "reason_code": "no_changes"}],
            risk={"level": "none", "reason_code": "no_changes"},
            gate={"decision": "not_evaluated", "reason_code": "no_changes"},
            budget={"supervisor_runs": 0, "strong_calls": 0, "cheap_calls": 0},
            changed_plan_fields=[], confidence=0.0, unresolved_assumptions=[],
            calls=[], source_change_count=0, accepted_result_ids=[],
            review_duration_supplied_seconds=None,
            review_reply_started_at=None, review_reply_finished_at=None,
            procedure_conversions=0,
        )
        second = self.audit_record(
            batch_id="watch-2-2", input_message_ids=[1], input_event_ids=[7],
            source_ids=["event:7", "message:1"], calls=[
                {
                    "attempt_id": "attempt-retry", "result_id": "result-shared",
                    "kind": "llm", "model_tier": "cheap",
                    "retry": True, "escalation": True, "input_tokens": 4,
                    "output_tokens": 6, "total_tokens": 10,
                    "estimated_cost": {"amount": 0.1, "currency": "USD"},
                    "actual_cost": {"amount": 0.08, "currency": "USD"},
                },
                {
                    "attempt_id": "attempt-api", "result_id": "result-shared",
                    "kind": "api", "model_tier": "none",
                    "retry": False, "escalation": False, "input_tokens": 0,
                    "output_tokens": 0, "total_tokens": 0,
                    "estimated_cost": None, "actual_cost": None,
                },
            ], source_change_count=2, accepted_result_ids=["result-shared"],
            human_corrections=2, review_duration_supplied_seconds=9.0,
            review_reply_started_at=200.0, review_reply_finished_at=204.0,
            procedure_conversions=2,
        )
        expected = {
            "schema_version": 1, "batches": 2, "source_changes": 2,
            "idle_polls": 1, "idle_llm_calls": 0,
            "batches_per_source_change": {"numerator": 2, "denominator": 2, "value": 1.0},
            "strong_invocations": 0, "cheap_invocations": 1,
            "input_tokens": 4, "output_tokens": 6, "total_tokens": 10,
            "estimated_cost": {
                "amount": 0.1, "currency": "USD", "known_count": 1, "unknown_count": 1,
            },
            "actual_cost": {
                "amount": 0.08, "currency": "USD", "known_count": 1, "unknown_count": 1,
            },
            "accepted_results": 1,
            "tokens_per_accepted_result": {"numerator": 10, "denominator": 1, "value": 10.0},
            "estimated_cost_per_accepted_result": {
                "numerator": 0.1, "denominator": 1, "value": None,
            },
            "actual_cost_per_accepted_result": {
                "numerator": 0.08, "denominator": 1, "value": None,
            },
            "retries": 1, "escalations": 1, "human_corrections": 2,
            "review_duration_supplied_seconds": {"total": 9.0, "count": 1},
            "review_duration_fallback_seconds": {"total": None, "count": 0},
            "review_duration_chosen_seconds": {"total": 9.0, "count": 1},
            "procedure_conversions": 2,
        }
        self.assertEqual(hermes_supervisor.build_eco_report((second, idle)), expected)
        self.assertEqual(hermes_supervisor.build_eco_report((idle, second)), expected)
        zero = hermes_supervisor.build_eco_report((idle,))
        for key in (
            "batches_per_source_change", "tokens_per_accepted_result",
            "estimated_cost_per_accepted_result", "actual_cost_per_accepted_result",
        ):
            self.assertEqual(zero[key]["denominator"], 0)
            self.assertIsNone(zero[key]["value"])
        self.assertEqual(zero["review_duration_supplied_seconds"], {"total": None, "count": 0})
        self.assertEqual(zero["review_duration_fallback_seconds"], {"total": None, "count": 0})
        self.assertEqual(zero["review_duration_chosen_seconds"], {"total": None, "count": 0})

    def test_eco_report_deduplicates_sources_and_results_and_rejects_mixed_currency(self) -> None:
        first = self.audit_record()
        duplicate = self.audit_record(
            batch_id="watch-200-7", calls=[dict(first["calls"][0], attempt_id="attempt-2")]
        )
        report = hermes_supervisor.build_eco_report((first, duplicate))
        self.assertEqual(report["source_changes"], 3)
        self.assertEqual(report["accepted_results"], 1)
        self.assertEqual(report["actual_cost"], {
            "amount": None, "currency": None, "known_count": 0, "unknown_count": 2,
        })
        mixed = self.audit_record(
            batch_id="watch-300-7",
            calls=[dict(
                first["calls"][0], attempt_id="attempt-3",
                estimated_cost={"amount": 1.0, "currency": "EUR"},
            )],
        )
        with self.assertRaises(hermes_supervisor.AuditError):
            hermes_supervisor.build_eco_report((first, mixed))

    def test_review_evidence_rejects_negative_or_reversed_clocks(self) -> None:
        for updates in (
            {"review_duration_supplied_seconds": -1.0},
            {"review_reply_started_at": 10.0, "review_reply_finished_at": None},
            {"review_reply_started_at": 10.0, "review_reply_finished_at": 9.0},
        ):
            with self.subTest(updates=updates), self.assertRaises(hermes_supervisor.AuditError):
                hermes_supervisor.validate_run_audit_record(self.audit_record(**updates))

    @staticmethod
    def make_retention_db(path: Path) -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE tasks (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
                  status TEXT NOT NULL, priority INTEGER DEFAULT 0, created_by TEXT,
                  created_at INTEGER NOT NULL, started_at INTEGER, completed_at INTEGER,
                  workspace_kind TEXT NOT NULL DEFAULT 'scratch', workspace_path TEXT,
                  branch_name TEXT, claim_lock TEXT, claim_expires INTEGER, tenant TEXT,
                  result TEXT, idempotency_key TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0,
                  worker_pid INTEGER, last_failure_error TEXT, max_runtime_seconds INTEGER,
                  last_heartbeat_at INTEGER, current_run_id INTEGER, workflow_template_id TEXT,
                  current_step_key TEXT, skills TEXT, model_override TEXT, max_retries INTEGER,
                  goal_mode INTEGER NOT NULL DEFAULT 0, goal_max_turns INTEGER, session_id TEXT,
                  project_id TEXT, block_kind TEXT, block_recurrences INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO tasks (id,title,status,created_by,created_at,completed_at) VALUES
                  ('old-owned', 'old', 'done', 'supervisor-watcher', 1, 100),
                  ('new-owned', 'new', 'done', 'supervisor-watcher', 1, 3999999),
                  ('old-human', 'human', 'done', 'human', 1, 100),
                  ('old-running', 'running', 'running', 'supervisor-watcher', 1, 100);
                """
            )

    @staticmethod
    def write_artifact_manifest(path: Path, kind: str, *, created_at: float = 1.0) -> Path:
        manifest = path.with_name(path.name + ".supervisor-manifest.json")
        manifest.write_text(json.dumps({
            "schema_version": 1, "kind": kind, "name": path.name,
            "owner": "hermes-supervisor", "id": "fixture-artifact", "created_at": created_at,
        }, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
        os.chmod(manifest, 0o600)
        os.utime(manifest, (created_at, created_at))
        return manifest

    def test_retention_plan_and_apply_are_scoped_explicit_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "kanban.db"
            self.make_retention_db(database)
            logs = root / "logs"
            sandboxes = root / "sandboxes"
            logs.mkdir(mode=0o700)
            sandboxes.mkdir(mode=0o700)
            old_log = logs / "supervisor-run-a.log"
            kept_log = logs / "conversation.log"
            old_box = sandboxes / "supervisor-run-b"
            old_log.write_text("detail", encoding="utf-8")
            kept_log.write_text("preserve", encoding="utf-8")
            os.chmod(old_log, 0o600)
            os.chmod(kept_log, 0o600)
            old_box.mkdir(mode=0o700)
            detail = old_box / "detail.log"
            detail.write_text("detail", encoding="utf-8")
            os.chmod(detail, 0o600)
            cutoff = 4_000_000 - 30 * 86400
            for path in (old_log, old_box, detail):
                os.utime(path, (cutoff - 1, cutoff - 1))
            self.write_artifact_manifest(old_log, "detailed_logs", created_at=cutoff - 1)
            self.write_artifact_manifest(old_box, "sandboxes", created_at=cutoff - 1)
            plan = hermes_supervisor.plan_retention(
                database, "supervisor", {"detailed_logs": logs, "sandboxes": sandboxes},
                days=30, now=4_000_000,
            )
            calls: list[list[str]] = []

            def archive_runner(argv: list[str], **kwargs: Any) -> Any:
                calls.append(argv)
                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute(
                        "UPDATE tasks SET status='archived' WHERE id=?", (argv[-1],)
                    )
                return subprocess.CompletedProcess(argv, 0, "", "")

            adapter = hermes_supervisor.HermesRetentionClient(
                "/fake/hermes", "supervisor", runner=archive_runner,
            )
            dry = hermes_supervisor.apply_retention(plan, adapter, dry_run=True)
            self.assertEqual(dry.archived_ids, ())
            self.assertTrue(old_log.exists())
            self.assertEqual(calls, [])
            applied = hermes_supervisor.apply_retention(plan, adapter, dry_run=False)
            self.assertEqual(applied.archived_ids, ("old-owned",))
            self.assertEqual(
                calls, [["/fake/hermes", "kanban", "--board", "supervisor", "archive", "old-owned"]]
            )
            self.assertFalse(old_log.exists())
            self.assertFalse(old_box.exists())
            self.assertTrue(kept_log.exists())
            self.assertEqual(
                [candidate.kind for candidate in plan.artifacts],
                ["detailed_logs", "sandboxes"],
            )

    def test_retention_schema_matches_installed_projection_without_board_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "kanban.db"
            self.make_retention_db(database)
            plan = hermes_supervisor.plan_retention(
                database, "supervisor", {}, days=30, now=4_000_000
            )
            self.assertEqual(plan.archive_ids, ("old-owned",))
            with closing(sqlite3.connect(database)) as source:
                create_sql = source.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
                ).fetchone()[0]
            incompatible = Path(directory) / "incompatible.db"
            with closing(sqlite3.connect(incompatible)) as connection, connection:
                connection.execute(create_sql.replace("status TEXT NOT NULL", "status TEXT"))
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    incompatible, "supervisor", {}, days=30, now=4_000_000
                )
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("ALTER TABLE tasks ADD COLUMN surprise_secret TEXT")
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    database, "supervisor", {}, days=30, now=4_000_000
                )
        source = Path(hermes_supervisor.__file__).read_text(encoding="utf-8")
        self.assertIn("mode=ro", source)
        self.assertNotIn("WHERE board = ?", source)

    def test_archive_timeout_reconciles_archived_but_wrong_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "kanban.db"
            self.make_retention_db(database)
            plan = hermes_supervisor.plan_retention(
                database, "supervisor", {}, days=30, now=4_000_000
            )
            calls: list[list[str]] = []

            def ambiguous(argv: list[str], **kwargs: Any) -> Any:
                calls.append(argv)
                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute("UPDATE tasks SET status='archived' WHERE id='old-owned'")
                raise subprocess.TimeoutExpired(argv, 1)

            adapter = hermes_supervisor.HermesRetentionClient(
                "/fake/hermes", "supervisor", runner=ambiguous
            )
            result = hermes_supervisor.apply_retention(plan, adapter, dry_run=False)
            self.assertEqual(result.archived_ids, ("old-owned",))
            self.assertEqual(len(calls), 1)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "UPDATE tasks SET status='running', created_by='human' WHERE id='old-owned'"
                )
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.apply_retention(plan, adapter, dry_run=False)
            self.assertEqual(len(calls), 1)

    def test_retention_rejects_nested_hardlink_and_post_plan_tree_mutation_before_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "kanban.db"
            self.make_retention_db(database)
            cache = root / "cache"
            cache.mkdir(mode=0o700)
            candidate = cache / "supervisor-run-hardlink"
            candidate.mkdir(mode=0o700)
            victim = root / "victim"
            victim.write_text("keep", encoding="utf-8")
            os.chmod(victim, 0o600)
            os.link(victim, candidate / "nested")
            os.utime(candidate, (1, 1))
            hardlink_manifest = self.write_artifact_manifest(candidate, "cache")
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    database, "supervisor", {"cache": cache}, days=30, now=4_000_000
                )
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

            (candidate / "nested").unlink()
            candidate.rmdir()
            hardlink_manifest.unlink()
            first = cache / "supervisor-run-a"
            second = cache / "supervisor-run-b"
            for item in (first, second):
                item.mkdir(mode=0o700)
                child = item / "data"
                child.write_text("data", encoding="utf-8")
                os.chmod(child, 0o600)
                os.utime(child, (1, 1))
                os.utime(item, (1, 1))
                self.write_artifact_manifest(item, "cache")
            plan = hermes_supervisor.plan_retention(
                database, "supervisor", {"cache": cache}, days=30, now=4_000_000
            )
            os.chmod(second / "data", 0o400)
            adapter = hermes_supervisor.HermesRetentionClient(
                "/fake/hermes", "supervisor",
                runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
            )
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.apply_retention(plan, adapter, dry_run=False)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())

    def test_artifact_requires_provenance_and_all_descendants_old(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "kanban.db"
            self.make_retention_db(database)
            cache = root / "cache"
            cache.mkdir(mode=0o700)
            user_data = cache / "supervisor-user-data"
            user_data.write_text("keep", encoding="utf-8")
            os.chmod(user_data, 0o600)
            os.utime(user_data, (1, 1))
            young_tree = cache / "supervisor-young-child"
            young_tree.mkdir(mode=0o700)
            child = young_tree / "recent"
            child.write_text("keep", encoding="utf-8")
            os.chmod(child, 0o600)
            os.utime(young_tree, (1, 1))
            self.write_artifact_manifest(young_tree, "cache")
            plan = hermes_supervisor.plan_retention(
                database, "supervisor", {"cache": cache}, days=30, now=4_000_000
            )
            self.assertEqual(plan.artifacts, ())
            self.assertTrue(user_data.exists())
            self.assertTrue(child.exists())

    def test_retention_rejects_symlinks_outside_roots_and_hostile_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "kanban.db"
            self.make_retention_db(database)
            real = root / "real"
            real.mkdir(mode=0o700)
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    database, "supervisor", {"cache": linked}, days=30, now=4_000_000
                )
            hostile = root / "cache"
            hostile.mkdir(mode=0o700)
            (hostile / "supervisor-run-x").symlink_to(root / "outside")
            hostile_manifest = self.write_artifact_manifest(
                hostile / "supervisor-run-x", "cache"
            )
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    database, "supervisor", {"cache": hostile}, days=30, now=4_000_000
                )
            (hostile / "supervisor-run-x").unlink()
            hostile_manifest.unlink()
            nested = hostile / "supervisor-run-nested"
            nested.mkdir(mode=0o700)
            (nested / "escape").symlink_to(root / "outside")
            os.utime(nested, (1, 1))
            self.write_artifact_manifest(nested, "cache")
            with self.assertRaises(hermes_supervisor.RetentionError):
                hermes_supervisor.plan_retention(
                    database, "supervisor", {"cache": hostile}, days=30, now=4_000_000
                )
            for kwargs in ({"days": True}, {"now": float("inf")}, {"board": "../other"}):
                call = dict(
                    kanban_db=database, board="supervisor", artifact_roots={},
                    days=30, now=4_000_000,
                )
                call.update(kwargs)
                with self.assertRaises(hermes_supervisor.RetentionError):
                    hermes_supervisor.plan_retention(**call)

    def test_task11_cli_and_nix_contracts_wire_private_paths_without_global_gc(self) -> None:
        module = (REPO_ROOT / "home/modules/ai/hermes-supervisor.nix").read_text(encoding="utf-8")
        for fragment in (
            "--audit ${stateRoot}/run-audit.jsonl", "eco-report",
            "--kanban-db", "--artifact-root", "--board",
            "${stateRoot}/run-audit.jsonl", "--dry-run",
        ):
            self.assertIn(fragment, module)
        self.assertIn("kanbanDb =", module)
        self.assertIn('if cfg.board == "default" then', module)
        self.assertIn('/.hermes/kanban/boards/${cfg.board}/kanban.db', module)
        self.assertNotIn("hermes kanban gc", module)
        self.assertNotIn(" kanban gc ", module)
        self.assertNotIn("enable = true", module)
        self.assertIn("retention.apply.enable", module)
        self.assertIn("lib.optionalString (!cfg.retention.apply.enable) \"--dry-run\"", module)

    def test_gc_invalid_retention_arguments_do_not_delete_state_temps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / ".state.json.tmp.1.0123456789abcdef"
            stale.write_text("partial", encoding="ascii")
            os.utime(stale, (1, 1))
            argv = [
                "hermes-supervisor", "gc", "--older-than", "30d",
                "--state-root", str(root), "--kanban-db", str(root / "missing.db"),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                hermes_supervisor.time, "time", return_value=4_000_000,
            ), mock.patch("builtins.print"):
                self.assertEqual(hermes_supervisor.main(), 2)
            self.assertTrue(stale.exists())


if __name__ == "__main__":
    unittest.main()
