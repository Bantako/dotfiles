{
  pkgs,
  inputs,
  config,
  ...
}:

let
  system = pkgs.stdenv.hostPlatform.system;
  herdrPkg = inputs.herdr.packages.${system}.default.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      ../../../patches/herdr-detect-claude-unwrapped.patch
    ];
  });
in
{
  home.packages = [ herdrPkg ];

  xdg.configFile."herdr/config.toml".text = ''
    [keys]
    focus_agent = "prefix+1..9"
    switch_tab = ""

    [experimental]
    kitty_graphics = true
  '';

  # herdr-remote relay — WebSocket relay for remote monitoring
  systemd.user.services.herdr-remote-relay = {
    Unit = {
      Description = "herdr-remote relay — WebSocket relay for remote agent monitoring";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
      StartLimitIntervalSec = 120;
      StartLimitBurst = 3;
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "herdr-remote-relay-start" ''
        set -euo pipefail
        RELAY_DIR="${config.home.homeDirectory}/herdr-remote/relay"
        export HERDR_BIN="${herdrPkg}/bin/herdr"
        export HERDR_RELAY="ws://127.0.0.1:8375"
        exec ${pkgs.uv}/bin/uv run --directory "$RELAY_DIR" herdr_relay.py
      '';
      Restart = "on-failure";
      RestartSec = "10s";
      PrivateTmp = true;
    };

    Install.WantedBy = [ "default.target" ];
  };

  # herdr-remote web UI — serves the mobile web app
  systemd.user.services.herdr-remote-web = {
    Unit = {
      Description = "herdr-remote web UI — mobile web app over HTTP";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "herdr-remote-web-start" ''
        set -euo pipefail
        WEB_DIR="${config.home.homeDirectory}/herdr-remote/web"
        cd "$WEB_DIR"
        exec ${pkgs.python3}/bin/python3 -m http.server 8080
      '';
      Restart = "on-failure";
      RestartSec = "10s";
      PrivateTmp = true;
    };

    Install.WantedBy = [ "default.target" ];
  };
}
