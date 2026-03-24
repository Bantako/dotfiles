{inputs, config, pkgs, ...}:
{
  home.file.".config/sheldon/plugins.toml".source = ./sheldon/plugins.toml;
}

