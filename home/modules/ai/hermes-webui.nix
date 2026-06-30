{
  pkgs,
  config,
  inputs,
  ...
}:

let
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
  # WebUI bootstrap.py は「同じPythonでWebUI依存 + Hermes Agentをimportできること」を要求する。
  # HermesのNix venvには pyyaml / cryptography / run_agent が揃っているので、これを明示的に使わせる。
  hermesPython = "${hermesPkg.passthru.hermesVenv}/bin/python3";

  src = pkgs.fetchFromGitHub {
    owner = "nesquena";
    repo = "hermes-webui";
    rev = "3b120e70cc887f6099c52f32cf0cbe6ce5b857e0";
    hash = "sha256-lRbBgaQWMnqST11BLxvxQpdZZ1hwWDl4W/PkqDgYAtw=";
  };
in
{
  systemd.user.services.hermes-webui = {
    Unit = {
      Description = "Hermes WebUI (nesquena)";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
      StartLimitIntervalSec = 120;
      StartLimitBurst = 3;
    };

    Service = {
      Type = "exec";
      ExecStart = pkgs.writeShellScript "hermes-webui-start" ''
        set -euo pipefail

        # ---- paths ----
        SRC="${src}"
        TARGET="${config.home.homeDirectory}/.local/share/hermes-webui"
        STATE_DIR="${config.home.homeDirectory}/.hermes/webui"

        # ---- copy source to writable location (first run / update) ----
        if ! [ -d "$TARGET" ] || ! [ -f "$TARGET/.nix-store-rev" ] \
           || [ "$(cat "$TARGET/.nix-store-rev")" != "$SRC" ]; then
          mkdir -p "$TARGET"
          cp -r "$SRC/"* "$TARGET/"
          echo "$SRC" > "$TARGET/.nix-store-rev"
        fi

        # ---- env ----
        # Bind all interfaces so other machines can access it directly; Tailscale Serve also exposes HTTPS.
        export HERMES_WEBUI_HOST="0.0.0.0"
        export HERMES_WEBUI_PORT="8787"
        export HERMES_WEBUI_STATE_DIR="$STATE_DIR"
        export HERMES_WEBUI_SKIP_ONBOARDING=1
        export HERMES_WEBUI_PYTHON="${hermesPython}"
        # systemd supervisor auto-detection → --foreground implicit
        # PATH: hermes CLI + Hermes venv
        export PATH="${hermesPkg.passthru.hermesVenv}/bin:${hermesPkg}/bin:$PATH"

        cd "$TARGET"
        exec python3 bootstrap.py
      '';
      Restart = "on-failure";
      RestartSec = "15s";

      # Direct network exposure is controlled by the NixOS firewall; HTTPS is handled by Tailscale Serve.
      PrivateTmp = true;
    };

    Install.WantedBy = [ "default.target" ];
  };
}
