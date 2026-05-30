{ pkgs, ... }:
{
  stylix = {
    enable = true;
    base16Scheme = "${pkgs.base16-schemes}/share/themes/dracula.yaml";
    image = pkgs.runCommand "stylix-bg" {
      nativeBuildInputs = [ pkgs.imagemagick ];
    } ''convert -size 1x1 xc:"#282a36" png:"$out"'';
    polarity = "dark";

    fonts = {
      monospace = {
        package = pkgs.nerd-fonts.jetbrains-mono;
        name = "JetBrainsMono Nerd Font Mono";
      };
      sansSerif = {
        package = pkgs.noto-fonts-cjk-sans;
        name = "Noto Sans CJK JP";
      };
      serif = {
        package = pkgs.noto-fonts-cjk-serif;
        name = "Noto Serif CJK JP";
      };
      sizes = {
        applications = 11;
        terminal = 13;
        popups = 11;
      };
    };

    cursor = {
      package = pkgs.bibata-cursors;
      name = "Bibata-Modern-Classic";
      size = 24;
    };

    targets = {
      # noctalia は settings.json で predefinedScheme = "Dracula" を直接管理
      noctalia-shell.enable = false;
      # Qt は platformTheme = gtk3 で GTK に追従させているため stylix の Qt target は不要
      qt.enable = false;
      # Niri を使用しているため hyprland target は無効化
      hyprland.enable = false;
    };
  };
}
