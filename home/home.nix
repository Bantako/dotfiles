{
  inputs,
  config,
  pkgs,
  ...
}:
{
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "26.05";
    sessionPath = [ "${homeDirectory}/.local/bin" ];
    sessionVariables.NIXOS_OZONE_WL = "1";
  };
  programs.home-manager.enable = true;
  programs.nh = {
    enable = true;
    flake = "/home/morikawa/.dotfiles";
  };

  imports = [
    inputs.hunk.homeManagerModules.default
    ./modules/ai/beszel-agent.nix
    ./modules/ai/claude-code.nix
    ./modules/ai/codex.nix
    ./modules/ai/herdr.nix
    ./modules/ai/hermes-backup.nix
    ./modules/ai/hermes-webui.nix
    ./modules/ai/hermes.nix
    ./modules/ai/karakeep.nix
    ./modules/ai/materialious.nix
    ./modules/ai/miniflux.nix
    ./modules/ai/szurubooru.nix
    ./modules/ai/hunk.nix
    ./modules/ai/mcp.nix
    ./modules/ai/opencode.nix
    ./modules/ai/rtk.nix
    ./modules/cli/co2.nix
    ./modules/cli/bat.nix
    ./modules/cli/dev.nix
    ./modules/cli/fastfetch.nix
    ./modules/cli/git.nix
    ./modules/cli/gpg.nix
    ./modules/cli/neovim.nix
    ./modules/cli/tools.nix
    ./modules/cli/calendar.nix
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
    ./modules/desktop/pavlok.nix
    ./modules/desktop/bedtime.nix
    ./modules/desktop/noctalia-state-bridge.nix
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
