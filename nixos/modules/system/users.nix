{ config, pkgs, ... }:

{
  users.users.morikawa = {
    isNormalUser = true;
    description = "morikawa";
    extraGroups = [ "networkmanager" "wheel" ];
    packages = with pkgs; [
      kdePackages.kate
    ];
    shell = pkgs.zsh;
  };

  programs = {
    git.enable = true;
    starship.enable = true;
    zsh.enable = true;
    firefox.enable = true;
    kdeconnect.enable = true;
  };
}
