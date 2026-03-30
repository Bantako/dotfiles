{inputs, config, pkgs, ...}:
{
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "26.05";
  };
  programs.home-manager.enable = true;

  imports = [
    ./modules/ai/claude-code.nix
    ./modules/cli/git.nix
    ./modules/cli/neovim.nix
    ./modules/cli/sheldon.nix
    ./modules/cli/yazi.nix
    ./modules/desktop/apps.nix
    ./modules/desktop/gtk.nix
    ./modules/desktop/niri.nix
    ./modules/desktop/noctalia.nix
    ./modules/desktop/wezterm.nix
    ./modules/desktop/xremap.nix
    ./modules/programs/browser.nix
    ./modules/shell/zsh.nix
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
    jq
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
    nemo
    zathura
  ];

  services.kdeconnect = {
    enable = true;
    package = pkgs.kdePackages.kdeconnect-kde;
    indicator = true;
  };

}
