{inputs, config, pkgs, ...}:
{
  # dotfilesのコピーではなくsymlinkにして変更可能にする
  home.file.".config/nvim".source = config.lib.file.mkOutOfStoreSymlink "${config.home.homeDirectory}/.dotfiles/home/modules/cli/nvim";

  # nvim
  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    defaultEditor = true;
  };
}
