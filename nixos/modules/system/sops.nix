{ config, ... }:
{
  sops = {
    defaultSopsFile = ../../hosts/ser7/secrets/secrets.yaml;
    defaultSopsFormat = "yaml";

    age = {
      generateKey = false;
      keyFile = "/var/lib/sops-nix/key.txt";
    };

    secrets.example_key = {
    };

  };
}
