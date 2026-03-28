# Edit this configuration file to define what should be installed on
# your system.  Help is available in the configuration.nix(4) man page
# and in the NixOS manual (accessible by running ‘nixos-help’).

{ inputs, config, pkgs, ... }:

{
  imports = [
    ./hardware.nix
    ../../modules/desktop/desktop.nix
    ../../modules/desktop/portal.nix
    ../../modules/system/flatpak.nix
    ../../modules/system/locale.nix
    ../../modules/system/networking.nix
    ../../modules/system/sops.nix
    ../../modules/system/users.nix
  ]
  ++ [
    inputs.xremap.nixosModules.default
    inputs.niri.nixosModules.niri
  ];

  networking.hostName = "nixos";
  networking.wireless.enable = true;

  services.xremap = {
    userName = "morikawa";
    serviceMode = "system";
    config = {
      modmap = [
        {
	  name = "swap mod";
	  remap = {
	    SUPER_L = "CTRL_L";
	    CTRL_L = "SUPER_L";
          };
	}
      ];
    };
  };

  # List packages installed in system profile. To search, run:
  # $ nix search wget
  environment.systemPackages = with pkgs; [
  #  vim # Do not forget to add an editor to edit configuration.nix! The Nano editor is also installed by default.
  #  wget
    # git
    # vim
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
    dedicatedServer.openFirewall = true;
  };
}
