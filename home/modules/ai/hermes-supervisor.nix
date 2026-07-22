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
    name = "hermes-supervisor";
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
  watchCommand = pkgs.writeShellScript "hermes-supervisor-watch" ''
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${supervisorCli}/bin/hermes-supervisor watch \
      --policy ${config.xdg.configHome}/hermes-supervisor/policy.json \
      --state ${stateRoot}/state.json \
      --state-db ${config.home.homeDirectory}/.hermes/state.db \
      --kanban-db ${config.home.homeDirectory}/.hermes/kanban.db \
      --board ${lib.escapeShellArg cfg.board} \
      --hermes ${hermesPkg}/bin/hermes \
      --profile default
  '';
  gcCommand = pkgs.writeShellScript "hermes-supervisor-gc" ''
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${supervisorCli}/bin/hermes-supervisor gc \
      --older-than 30d \
      --state-root ${stateRoot}
  '';
  briefingCommand = pkgs.writeShellScript "hermes-supervisor-briefing" ''
    exec ${pkgs.util-linux}/bin/flock \
      --nonblock \
      --conflict-exit-code 0 \
      "${runtimeRoot}/watch.lock" \
      ${hermesPkg.passthru.hermesVenv}/bin/python3 \
      ${../../../tools/hermes_supervisor.py} brief \
      --kanban-db ${config.home.homeDirectory}/.hermes/kanban.db \
      --state-root ${stateRoot} \
      --hermes ${hermesPkg}/bin/hermes \
      --discord-target ${lib.escapeShellArg cfg.discordTarget} \
      --webui-url ${lib.escapeShellArg cfg.webuiUrl} \
      --prompt ${./hermes-supervisor/prompts/briefing.md}
  '';
  commonService = {
    Type = "oneshot";
    UMask = "0077";
    StateDirectory = "hermes-supervisor";
    StateDirectoryMode = "0700";
    RuntimeDirectory = "hermes-supervisor";
    RuntimeDirectoryMode = "0700";
    RuntimeMaxSec = "9m";
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
    ];

    home.packages = [ supervisorCli ];

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
