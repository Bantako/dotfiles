{ config, pkgs, ... }:

{
  users.users.morikawa = {
    isNormalUser = true;
    description = "morikawa";
    extraGroups = [ "networkmanager" "wheel" "input" "corectrl" ];
    shell = pkgs.zsh;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILBR65MwTU4cCzMnnALIIZubcUF+/uH1m37eD0fdvMoB"
    ];
  };

  programs = {
    git.enable = true;
    zsh.enable = true;
    kdeconnect.enable = true;
    dconf.enable = true;
  };
}
