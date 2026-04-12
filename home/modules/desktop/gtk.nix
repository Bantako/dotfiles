{ inputs, config, pkgs, ...}:
{
  gtk = {
    enable = true;
    theme = {
      name = "Dracula";
      package = pkgs.dracula-theme;
    };
    iconTheme = {
      name = "Papirus-Dark";
      # breeze-icons: Papirus-Dark が Inherits=breeze-dark,hicolor なので
      # フォールバックチェーンを通すために breeze-icons も必要
      package = pkgs.symlinkJoin {
        name = "papirus-with-breeze";
        paths = [ pkgs.papirus-icon-theme pkgs.kdePackages.breeze-icons ];
      };
    };
    cursorTheme = {
      name = "Bibata-Modern-Classic";
      package = pkgs.bibata-cursors;
      size = 24;
    };
  };

  # Qt アプリのテーマを GTK3 テーマ（Dracula）に追従させる
  qt = {
    enable = true;
    platformTheme.name = "gtk3";
  };

  # Waylandアプリにもカーソルテーマを適用
  home.pointerCursor = {
    name = "Bibata-Modern-Classic";
    package = pkgs.bibata-cursors;
    size = 24;
    gtk.enable = true;
  };
}
