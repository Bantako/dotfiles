{inputs, config, pkgs, lib, ...}:
{
  # programs.neovim が生成する init.lua を抑制する
  # 実際の init.lua は nvimSymlink 経由の dotfiles 版を使う
  xdg.configFile."nvim/init.lua" = lib.mkForce { enable = false; };

  # dotfilesのnvim設定をsymlinkにして変更可能にする
  # home.file からは除外し activation script で作成する（programs.neovim と競合するため）
  home.activation.nvimSymlink = lib.hm.dag.entryAfter ["writeBoundary"] ''
    target="${config.home.homeDirectory}/.dotfiles/home/modules/cli/nvim"
    link="${config.home.homeDirectory}/.config/nvim"
    if [ "$(readlink "$link" 2>/dev/null)" != "$target" ]; then
      $DRY_RUN_CMD rm -rf "$link"
      $DRY_RUN_CMD ln -sfn "$target" "$link"
    fi
  '';

  # nvim
  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    defaultEditor = true;
    extraPackages = with pkgs; [
      rust-analyzer
      rustfmt
      nil        # Nix LSP
      nixfmt
      lua-language-server
      vscode-json-languageserver
      shfmt
    ];
  };

  home.packages = with pkgs; [
    (vimPlugins.nvim-treesitter.withAllGrammars)
  ];
}
