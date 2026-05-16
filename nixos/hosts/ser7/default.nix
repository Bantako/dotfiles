# Edit this configuration file to define what should be installed on
# your system.  Help is available in the configuration.nix(4) man page
# and in the NixOS manual (accessible by running ‘nixos-help’).

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
  ]
  ++ [
    inputs.niri.nixosModules.niri
  ];

  networking.hostName = "nixos";

  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
    sops
    age
    sddm-astronaut
  ];

  # This value determines the NixOS release from which the default
  # settings for stateful data, like file locations and database versions
  # on your system were taken. It‘s perfectly fine and recommended to leave
  # this value at the release version of the first install of this system.
  # Before changing this value read the documentation for this option
  # (e.g. man configuration.nix or on https://nixos.org/nixos/options.html).
  system.stateVersion = "25.11"; # Did you read the comment?

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
