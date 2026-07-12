{ inputs, config, pkgs, ... }:

{
  imports = [
    ./hardware.nix
    ../../modules/desktop/commands.nix
    ../../modules/desktop/desktop.nix
    ../../modules/desktop/portal.nix
    ../../modules/system/bluetooth.nix
    ../../modules/system/flatpak.nix
    ../../modules/system/locale.nix
    ../../modules/system/networking.nix
    ../../modules/system/sops.nix
    ../../modules/system/podman.nix
    ../../modules/system/users.nix
    ../../modules/system/nix-ld.nix
    ../../modules/system/zram.nix
    ../../modules/system/oom.nix
    ../../modules/system/fwupd.nix
    ../../modules/system/monitoring.nix
    ../../modules/system/ssh.nix
    ../../modules/system/fail2ban.nix
    ../../modules/system/backup.nix
    ../../modules/system/iris-news.nix
    ../../modules/system/n8n.nix
    ../../modules/system/nas-monitor-heartbeat.nix
  ]
  ++ [
    inputs.niri.nixosModules.niri
  ];

  networking.hostName = "ser7";

  environment.systemPackages = with pkgs; [
    sops
    age
    sddm-astronaut
    appimage-run
    gsettings-desktop-schemas
    umu-launcher
  ];

  system.stateVersion = "26.05";

  nix = {
    settings = {
      auto-optimise-store = true;
      experimental-features = ["nix-command" "flakes"];
      max-jobs = "auto";
      # dev-shell の再ビルドを抑制。現在世代は GC root で保護されるため
      # 下の --delete-older-than 7d とは競合しない（古い世代のみ削除対象）
      keep-outputs = true;
      keep-derivations = true;
      substituters = [
        "https://cache.nixos.org"
        "https://niri.cachix.org"
      ];
      trusted-public-keys = [
        "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
        "niri.cachix.org-1:Wv0OmO7PsuocRKzfDoJ3mulSl7Z6oezYhGhR+3W2964="
      ];
    };
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };
  };

  nixpkgs.config.allowUnfree = true;

  # steam
  programs.steam = {
    enable = true;
    remotePlay.openFirewall = true;
    gamescopeSession.enable = true;
  };

  programs.gamemode.enable = true;

  programs.gamescope = {
    enable = true;
    capSysNice = true;
  };

  programs.corectrl.enable = true;
  hardware.amdgpu.overdrive.enable = true;

  # Wine / Proton 用: 32-bit グラフィクスサポート
  hardware.graphics.enable32Bit = true;
}
