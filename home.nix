 {inputs, config, pkgs, ...}: {
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
    ./desktop.nix
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
    # builds
    gcc
    nodejs_22
    lua-language-server
    nodePackages.vscode-json-languageserver
    shfmt
    tree-sitter   # CLI
    (vimPlugins.nvim-treesitter.withAllGrammars)
    xwayland-satellite
  ];

  # Shell
  home.file.".config/sheldon/plugins.toml".source = ./sheldon/plugins.toml;

  home.file.".config/wezterm/wezterm.lua".source = ./wezterm/wezterm.lua;
  home.file.".config/wezterm/keybinds.lua".source = ./wezterm/keybinds.lua;
  home.file.".config/nvim".source = config.lib.file.mkOutOfStoreSymlink "${config.home.homeDirectory}/.dotfiles/nvim";

  # nvim
  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    defaultEditor = true;
  };
}
