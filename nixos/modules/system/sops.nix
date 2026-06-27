{ config, ... }:
let
  userReadable = { owner = "morikawa"; group = "users"; mode = "0400"; };
in {
  sops = {
    defaultSopsFile = ../../hosts/ser7/secrets/secrets.yaml;
    defaultSopsFormat = "yaml";

    age = {
      generateKey = false;
      keyFile = "/var/lib/sops-nix/key.txt";
    };

    secrets = {
      openai_api_key = userReadable // { };
      deepseek_api_key = userReadable // { };
      raindrop_token = userReadable // { };
      todoist_api_token = userReadable // { path = "/run/secrets/todoist-api-token"; };
      paperless_token = userReadable // { };
      immich_token = userReadable // { };
      wger_api_token = userReadable // { };
      openrouter_api_key = userReadable // { };
      discord_bot_token = userReadable // { };
      borg_passphrase = { mode = "0400"; };
      ntfy_url = { mode = "0444"; };
      radicale_password = userReadable // { path = "/run/secrets/radicale-password"; };
      paperless_admin_password = userReadable // { };
    };
  };
}
