{ pkgs, inputs, ... }:

let
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
in
{
  home.packages = [ hermesPkg ];

  systemd.user.services.hermes-discord = {
    Unit = {
      Description = "Hermes Discord bot";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      ExecStart = pkgs.writeShellScript "hermes-discord-start" ''
        export DISCORD_BOT_TOKEN="$(cat /run/secrets/discord_bot_token)"
        export DISCORD_ENABLED=true
        export GATEWAY_ALLOW_ALL_USERS=true
        export DISCORD_ALLOWED_USERS=383918836014907393
        export DISCORD_HOME_CHANNEL=1513925087105912904
        exec ${hermesPkg}/bin/hermes gateway run
      '';
      Restart = "on-failure";
      RestartSec = "15s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
