
 {inputs, pkgs, ...}: {
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "25.11";
  };
  programs.home-manager.enable = true;

  imports = [
    ./zsh.nix
    ./apps.nix
    ./git.nix
    ./browser.nix
    ./yazi.nix
    inputs.niri.homeModules.niri
    inputs.dms.homeModules.dank-material-shell
    inputs.dms.homeModules.niri
  ];

  home.packages = with pkgs; [
    bat
    bottom
    eza
    fzf
    httpie
    ripgrep
    zoxide
    sheldon
    # nixai
  ];

  # Shell
  home.file.".config/sheldon/plugins.toml".source = ./sheldon/plugins.toml;

  # Desktop Environment
  programs.niri = {
    enable = true;
    settings = {
      # config = with inputs.niri.lib.kdl;
    };
  };
  programs.dank-material-shell = {
    enable = true;
    niri = {
      enableKeybinds = true;
      enableSpawn = true;
    };
  };


}
