{ pkgs, inputs, ... }:

let
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
in
{
  home.packages = [ hermesPkg ];

  systemd.user.services.hermes-discord = {
    Unit = {
      Description = "Hermes Discord bot";
      # network-online.target は user インスタンスに存在せず依存指定が無視されるため、
      # スクリプト内で実際に疎通を待つ (ブート直後や回線断からの復帰用)。
      StartLimitIntervalSec = 300;
      StartLimitBurst = 5;
    };
    Service = {
      ExecStart = pkgs.writeShellScript "hermes-discord-start" ''
        until ${pkgs.curl}/bin/curl -fsS --max-time 5 -o /dev/null https://discord.com/api/v10/gateway; do
          echo "waiting for network (discord.com unreachable)..."
          sleep 5
        done
        export DISCORD_BOT_TOKEN="$(cat /run/secrets/discord_bot_token)"
        export DISCORD_ENABLED=true
        export DISCORD_ALLOWED_USERS=383918836014907393
        export DISCORD_HOME_CHANNEL=1513925087105912904
        exec ${hermesPkg}/bin/hermes gateway run --replace
      '';
      Restart = "on-failure";
      RestartSec = "30s";
      TimeoutStopSec = "210s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
