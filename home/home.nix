{inputs, config, pkgs, ...}:
{
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "26.05";
  };
  programs.home-manager.enable = true;
  programs.nh = {
    enable = true;
    flake = "/home/morikawa/.dotfiles";
  };

  imports = [
    ./modules/ai/claude-code.nix
    ./modules/cli/git.nix
    ./modules/cli/neovim.nix
    ./modules/cli/sheldon.nix
    ./modules/cli/vimiv.nix
    ./modules/cli/yazi.nix
    ./modules/desktop/apps.nix
    ./modules/desktop/gtk.nix
    ./modules/desktop/ghostty.nix
    ./modules/desktop/niri.nix
    ./modules/desktop/noctalia.nix
    ./modules/desktop/wezterm.nix
    ./modules/desktop/xdg.nix
    ./modules/desktop/xremap.nix
    ./modules/desktop/zen-browser.nix
    ./modules/programs/browser.nix
    ./modules/shell/direnv.nix
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
    vscode-json-languageserver
    shfmt
    tree-sitter   # CLI
    (vimPlugins.nvim-treesitter.withAllGrammars)
    xwayland-satellite
    nemo
    zathura
    android-studio
    # ターミナルツール群
    vimiv-qt      # 画像ビューアー（yaziから起動）
    ov            # ページャー（yaziのbat連携）
    htop          # プロセスモニター
    gh            # GitHub CLI
    bitwarden-cli # パスワード管理CLI
    fio           # ディスクI/Oベンチマーク
    atool         # アーカイブ展開（aunpack, yaziから使用）
    # メディア・ノート
    calibre       # 電子書籍管理
    obsidian      # ノート
  ];

  services.kdeconnect = {
    enable = true;
    package = pkgs.kdePackages.kdeconnect-kde;
    indicator = true;
  };

}
