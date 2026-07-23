{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.hermes-supervisor;
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
  supervisorCli = pkgs.writeShellApplication {
    name = "hermes-supervisor-runtime";
    runtimeInputs = [
      hermesPkg
      pkgs.python3
      pkgs.sqlite
      pkgs.coreutils
      pkgs.util-linux
    ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${../../../tools/hermes_supervisor.py} "$@"
    '';
  };
  runtimePath = lib.makeBinPath [
    supervisorCli
    hermesPkg
    pkgs.python3
    pkgs.sqlite
    pkgs.coreutils
    pkgs.util-linux
  ];
  stateRoot = "${config.xdg.stateHome}/hermes-supervisor";
  runtimeRoot = "$XDG_RUNTIME_DIR/hermes-supervisor";
  kanbanDb =
    if cfg.board == "default" then
      "${config.home.homeDirectory}/.hermes/kanban.db"
    else
      "${config.home.homeDirectory}/.hermes/kanban/boards/${cfg.board}/kanban.db";
  watchCycleCommand = pkgs.writeShellScript "hermes-supervisor-watch-cycle" ''
    set -euo pipefail
    ${supervisorCli}/bin/hermes-supervisor-runtime replies \
      --state-db ${config.home.homeDirectory}/.hermes/state.db \
      --state-root ${stateRoot} \
      --board ${lib.escapeShellArg cfg.board} \
      --hermes ${hermesPkg}/bin/hermes
    exec ${supervisorCli}/bin/hermes-supervisor-runtime watch \
      --policy ${config.xdg.configHome}/hermes-supervisor/policy.json \
      --state ${stateRoot}/state.json \
      --audit ${stateRoot}/run-audit.jsonl \
      --state-db ${config.home.homeDirectory}/.hermes/state.db \
      --kanban-db ${kanbanDb} \
      --board ${lib.escapeShellArg cfg.board} \
      --hermes ${hermesPkg}/bin/hermes \
      --profile default
  '';
  watchCommand = pkgs.writeShellScript "hermes-supervisor-watch" ''
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${watchCycleCommand}
  '';
  gcCommand = pkgs.writeShellScript "hermes-supervisor-gc" ''
    ${pkgs.coreutils}/bin/install -d -m 0700 \
      ${stateRoot}/detailed-logs \
      ${stateRoot}/worktrees \
      ${stateRoot}/sandboxes \
      ${stateRoot}/cache
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${supervisorCli}/bin/hermes-supervisor-runtime gc \
      --older-than 30d \
      --state-root ${stateRoot} \
      --kanban-db ${kanbanDb} \
      --board ${lib.escapeShellArg cfg.board} \
      --hermes ${hermesPkg}/bin/hermes \
      --artifact-root detailed_logs=${stateRoot}/detailed-logs \
      --artifact-root worktrees=${stateRoot}/worktrees \
      --artifact-root sandboxes=${stateRoot}/sandboxes \
      --artifact-root cache=${stateRoot}/cache \
      ${lib.optionalString (!cfg.retention.apply.enable) "--dry-run"}
  '';
  ecoReportCommand = pkgs.writeShellApplication {
    name = "hermes-supervisor-eco-report";
    text = ''
      exec ${supervisorCli}/bin/hermes-supervisor-runtime eco-report \
        --audit ${stateRoot}/run-audit.jsonl
    '';
  };
  briefingCommand = pkgs.writeShellScript "hermes-supervisor-briefing" ''
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${hermesPkg.passthru.hermesVenv}/bin/python3 \
      ${../../../tools/hermes_supervisor.py} brief \
      --kanban-db ${kanbanDb} \
      --state-root ${stateRoot} \
      --hermes ${hermesPkg}/bin/hermes \
      --discord-target ${lib.escapeShellArg cfg.discordTarget} \
      --webui-url ${lib.escapeShellArg cfg.webuiUrl} \
      --prompt ${./hermes-supervisor/prompts/briefing.md}
  '';
  controlCommand = pkgs.writeShellApplication {
    name = "hermes-supervisor-control";
    runtimeInputs = [ pkgs.util-linux ];
    text = ''
      if [ "$#" -ne 1 ]; then
        echo "usage: hermes-supervisor-control pause|freeze|resume|emergency-stop" >&2
        exit 2
      fi
      action="$1"
      ${pkgs.coreutils}/bin/install -d -m 0700 "${runtimeRoot}"
      common_args=(
        --state '${stateRoot}/state.json'
        --audit '${stateRoot}/control-audit.jsonl'
        --board ${lib.escapeShellArg cfg.board}
        --hermes ${hermesPkg}/bin/hermes
      )
      case "$action" in
        pause|freeze|resume)
          exec ${pkgs.util-linux}/bin/flock \
            --nonblock --conflict-exit-code 75 \
            "${runtimeRoot}/watch.lock" \
            ${supervisorCli}/bin/hermes-supervisor-runtime state control \
            "''${common_args[@]}" "$action"
          ;;
        emergency-stop)
          exec ${pkgs.util-linux}/bin/flock \
            --nonblock --conflict-exit-code 75 \
            "${runtimeRoot}/watch.lock" \
            ${supervisorCli}/bin/hermes-supervisor-runtime state control \
            "''${common_args[@]}" \
            --ntfy-url ${lib.escapeShellArg cfg.control.ntfyUrl} \
            --curl ${pkgs.curl}/bin/curl \
            "$action"
          ;;
        *)
          echo "unsupported control action" >&2
          exit 2
          ;;
      esac
    '';
  };
  primaryGoalCommand = pkgs.writeShellApplication {
    name = "hermes-supervisor-primary-goal";
    runtimeInputs = [ pkgs.util-linux ];
    text = ''
      if [ "$#" -ne 1 ]; then
        echo "usage: hermes-supervisor-primary-goal <kanban-task-id>" >&2
        exit 2
      fi
      goal_id="$1"
      ${pkgs.coreutils}/bin/install -d -m 0700 "${runtimeRoot}"
      exec ${pkgs.util-linux}/bin/flock \
        --nonblock --conflict-exit-code 75 \
        "${runtimeRoot}/watch.lock" \
        ${supervisorCli}/bin/hermes-supervisor-runtime state primary-goal \
        --state '${stateRoot}/state.json' \
        --audit '${stateRoot}/control-audit.jsonl' \
        --policy ${lib.escapeShellArg "${config.xdg.configHome}/hermes-supervisor/policy.json"} \
        --board ${lib.escapeShellArg cfg.board} \
        --hermes ${hermesPkg}/bin/hermes \
        --goal-id "$goal_id"
    '';
  };
  commonService = {
    Type = "oneshot";
    UMask = "0077";
    StateDirectory = "hermes-supervisor";
    StateDirectoryMode = "0700";
    RuntimeDirectory = "hermes-supervisor";
    RuntimeDirectoryMode = "0700";
    TimeoutStartSec = "9m";
    KillMode = "control-group";
    PrivateTmp = true;
    NoNewPrivileges = true;
    Environment = [ "PATH=${runtimePath}" ];
  };
in
{
  options.services.hermes-supervisor = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the Hermes Supervisor watch and minimal GC timers.";
    };
    control = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Install the manual audited Supervisor control command.";
      };
      ntfyUrl = lib.mkOption {
        type = lib.types.str;
        default = "http://192.168.11.9:8080/nas-alerts";
        description = "Dedicated non-secret emergency ntfy endpoint.";
      };
    };
    retention.apply.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Explicitly permit the retention timer to archive and delete scoped candidates.";
    };
    board = lib.mkOption {
      type = lib.types.str;
      default = "supervisor";
      description = "Pinned lowercase Hermes Kanban board slug.";
    };
    discordTarget = lib.mkOption {
      type = lib.types.str;
      default = "discord";
      description = "Nightly no-LLM Hermes send delivery target.";
    };
    webuiUrl = lib.mkOption {
      type = lib.types.str;
      default = "https://ser7";
      description = "HTTP(S) WebUI URL included in the minimal Decision notification.";
    };
  };

  config = {
    assertions = [
      {
        assertion =
          builtins.stringLength cfg.board <= 64 && builtins.match "[a-z0-9]+(-[a-z0-9]+)*" cfg.board != null;
        message = "services.hermes-supervisor.board must be a lowercase hyphenated slug of at most 64 characters";
      }
      {
        assertion =
          builtins.stringLength cfg.discordTarget <= 64
          && builtins.match "[a-z0-9]+(-[a-z0-9]+)*" cfg.discordTarget != null;
        message = "services.hermes-supervisor.discordTarget must be a lowercase hyphenated slug of at most 64 characters";
      }
      {
        assertion = builtins.match "https?://[^[:space:]]+" cfg.webuiUrl != null;
        message = "services.hermes-supervisor.webuiUrl must be an HTTP(S) URL without whitespace";
      }
      {
        assertion =
          builtins.stringLength cfg.control.ntfyUrl <= 2048
          && builtins.match "https?://[^[:space:]]+" cfg.control.ntfyUrl != null;
        message = "services.hermes-supervisor.control.ntfyUrl must be a bounded HTTP(S) URL without whitespace";
      }
    ];

    home.packages = [
      supervisorCli
      ecoReportCommand
    ]
    ++ lib.optionals cfg.control.enable [
      controlCommand
      primaryGoalCommand
    ];

    xdg.configFile."hermes-supervisor/policy.json".source = ./hermes-supervisor/policy.json;
    xdg.configFile."hermes-supervisor/prompts" = {
      source = ./hermes-supervisor/prompts;
      recursive = true;
    };

    systemd.user.services.hermes-supervisor-watch = {
      Unit = {
        Description = "Run one Hermes Supervisor watch cycle";
        OnFailure = [ "hermes-failure-notify@%N.service" ];
      };
      Service = commonService // {
        ExecStart = "${watchCommand}";
      };
    };

    systemd.user.timers.hermes-supervisor-watch = {
      Unit.Description = "Run Hermes Supervisor every ten minutes";
      Timer = {
        OnCalendar = "*:0/10";
        Persistent = true;
        AccuracySec = "1m";
      };
      Install.WantedBy = lib.optional cfg.enable "timers.target";
    };

    systemd.user.services.hermes-supervisor-briefing = {
      Unit = {
        Description = "Publish the deterministic Hermes Supervisor briefing";
        OnFailure = [ "hermes-failure-notify@%N.service" ];
      };
      Service = commonService // {
        ExecStart = "${briefingCommand}";
      };
    };

    systemd.user.timers.hermes-supervisor-briefing = {
      Unit.Description = "Publish the Hermes Supervisor briefing at 21:00 JST";
      Timer = {
        OnCalendar = "*-*-* 21:00:00 Asia/Tokyo";
        Persistent = true;
        AccuracySec = "1m";
      };
      Install.WantedBy = lib.optional cfg.enable "timers.target";
    };

    systemd.user.services.hermes-supervisor-gc = {
      Unit = {
        Description = "Collect stale Hermes Supervisor state temp files";
        OnFailure = [ "hermes-failure-notify@%N.service" ];
      };
      Service = commonService // {
        ExecStart = "${gcCommand}";
      };
    };

    systemd.user.timers.hermes-supervisor-gc = {
      Unit.Description = "Daily minimal Hermes Supervisor state temp GC";
      Timer = {
        OnCalendar = "*-*-* 03:15:00";
        Persistent = true;
        AccuracySec = "1m";
        RandomizedDelaySec = "15m";
      };
      Install.WantedBy = lib.optional cfg.enable "timers.target";
    };
  };
}
