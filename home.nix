
 {pkgs, ...}: {
  home = rec {
    username = "morikawa";
    homeDirectory = "/home/${username}";
    stateVersion = "25.11";
  };
  programs.home-manager.enable = true;

  imports = [
    ./zsh.nix
    ./apps.nix
    ./git.nix
    ./browser.nix
  ];

  home.packages = with pkgs; [
    bat
    bottom
    eza
    fzf
    httpie
    ripgrep
    zoxide
  ];
}
