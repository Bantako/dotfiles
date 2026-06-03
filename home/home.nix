{inputs, config, pkgs, ...}:
{
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "26.05";
    sessionPath = [ "${homeDirectory}/.local/bin" ];
  };
  programs.home-manager.enable = true;
  programs.nh = {
    enable = true;
    flake = "/home/morikawa/.dotfiles";
  };

  imports = [
    ./modules/ai/claude-code.nix
    ./modules/ai/hermes.nix
    ./modules/ai/mcp.nix
    ./modules/ai/rtk.nix
    ./modules/cli/co2.nix
    ./modules/cli/bat.nix
    ./modules/cli/dev.nix
    ./modules/cli/fastfetch.nix
    ./modules/cli/git.nix
    ./modules/cli/gpg.nix
    ./modules/cli/neovim.nix
    ./modules/cli/tools.nix
    ./modules/cli/vimiv.nix
    ./modules/cli/yazi.nix
    ./modules/desktop/apps.nix
    ./modules/desktop/gtk.nix
    ./modules/desktop/stylix.nix
    ./modules/desktop/gammastep.nix
    ./modules/desktop/fcitx5.nix
    ./modules/desktop/ghostty.nix
    ./modules/desktop/mpv.nix
    ./modules/desktop/niri.nix
    ./modules/desktop/bedtime.nix
    ./modules/desktop/noctalia.nix
./modules/desktop/xdg.nix
    ./modules/desktop/xremap.nix
    ./modules/desktop/browsers.nix
    ./modules/desktop/zathura.nix
    ./modules/nas/immich.nix
    ./modules/nas/paperless.nix
    ./modules/shell/direnv.nix
    ./modules/shell/ssh.nix
    ./modules/shell/zsh.nix
  ];


  services.kdeconnect = {
    enable = true;
    package = pkgs.kdePackages.kdeconnect-kde;
    indicator = true;
  };

}
