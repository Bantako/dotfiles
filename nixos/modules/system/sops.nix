{ config, ... }:
let
  userReadable = {
    owner = "morikawa";
    group = "users";
    mode = "0400";
  };
in
{
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
      todoist_api_token = userReadable // {
        path = "/run/secrets/todoist-api-token";
      };
      paperless_token = userReadable // { };
      immich_token = userReadable // { };
      wger_api_token = userReadable // { };
      jelu_api_token = userReadable // { };
      lanraragi_api_token = userReadable // { };
      openrouter_api_key = userReadable // { };
      discord_bot_token = userReadable // { };
      pavlok_api_key = userReadable // { };
      n8n_api_key = userReadable // {
        path = "/run/secrets/n8n-api-key";
      };
      iris_news_miniflux_api_token = userReadable // { };
      iris_news_llm_base_url = userReadable // { };
      iris_news_llm_api_key = userReadable // { };
      borg_passphrase = {
        mode = "0400";
      };
      ntfy_url = {
        mode = "0444";
      };
      radicale_password = userReadable // {
        path = "/run/secrets/radicale-password";
      };
      paperless_admin_password = userReadable // { };
      karakeep_api_key = userReadable // {
        path = "/run/secrets/karakeep-api-key";
      };
      karakeep_env = userReadable // {
        path = "/run/secrets/karakeep-env";
      };
      materialious_env = userReadable // {
        path = "/run/secrets/materialious-env";
      };
      miniflux_env = userReadable // {
        path = "/run/secrets/miniflux-env";
      };
      szurubooru_env = userReadable // {
        path = "/run/secrets/szurubooru-env";
      };
      gelbooru_api_key = userReadable // {
        path = "/run/secrets/gelbooru-api-key";
      };
      gelbooru_user_id = userReadable // {
        path = "/run/secrets/gelbooru-user-id";
      };
      szurubooru_importer_token = userReadable // {
        path = "/run/secrets/szurubooru-importer-token";
      };
      hermes_monitor_webhook_secret = userReadable // { };
      monitor_relay_token = userReadable // { };
    };
  };
}
