{ pkgs, ...}:
{
  gtk = {
    enable = true;
    iconTheme = {
      name = "Papirus-Dark";
      # breeze-icons: Papirus-Dark が Inherits=breeze-dark,hicolor なので
      # フォールバックチェーンを通すために breeze-icons も必要
      package = pkgs.symlinkJoin {
        name = "papirus-with-breeze";
        paths = [ pkgs.papirus-icon-theme pkgs.kdePackages.breeze-icons ];
      };
    };
  };

  # Qt アプリのテーマを GTK3 テーマに追従させる
  qt = {
    enable = true;
    platformTheme.name = "gtk3";
  };
}
