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
    ./modules/cli/tools.nix
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


  services.kdeconnect = {
    enable = true;
    package = pkgs.kdePackages.kdeconnect-kde;
    indicator = true;
  };

}
