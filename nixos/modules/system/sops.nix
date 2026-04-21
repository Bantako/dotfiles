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
    };
  };
}
