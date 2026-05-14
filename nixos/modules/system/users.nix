{ config, pkgs, ... }:

{
  users.users.morikawa = {
    isNormalUser = true;
    description = "morikawa";
    extraGroups = [ "networkmanager" "wheel" "input" ];
    packages = with pkgs; [
    ];
    shell = pkgs.zsh;
  };

  programs = {
    git.enable = true;
    zsh.enable = true;
    firefox.enable = true;
    kdeconnect.enable = true;
    dconf.enable = true;
  };
}
