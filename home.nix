
 {inputs, pkgs, ...}: {
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "26.05";
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
    wezterm
    alacritty
    fuzzel
  ];

  # Shell
  home.file.".config/sheldon/plugins.toml".source = ./sheldon/plugins.toml;

  home.file.".config/wezterm/wezterm.lua".source = ./wezterm/wezterm.lua;
  home.file.".config/wezterm/keybinds.lua".source = ./wezterm/keybinds.lua;
  home.file.".config/nvim".source = ./nvim;

  # Desktop Environment
  programs.niri = {
    enable = true;
    settings = {
      # config = with inputs.niri.lib.kdl;
    };
  };
  programs.dank-material-shell = {
    enable = true;

    systemd = {
      enable = true;
      restartIfChanged = true;
    };
    # うまく動作しないのでsystemdオプションを使用する
    # niri = {
    #   enableKeybinds = true;
    #   enableSpawn = true;
    # };
  };

  # fuzzel
  xdg.configFile."fuzzel/fuzzel.ini".text = ''
    [main]
    font=JetBrainsMono Nerd Font:size=12
    width=40
    lines=10

    # dracula color scheme
    [colors]
    background=282a36dd
    text=f8f8f2ff
    match=8be9fdff
    selection-match=be9fdff
    selection=44475add
    selection-text=f8f8f2ff
    border=bd93f9ff
  '';

  # nvim
  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    defaultEditor = true;
  };

}
