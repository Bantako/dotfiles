{pkgs, ...}: {
  programs.zathura = {
    enable = true;
    options = {
      # ダークモードで表示
      recolor = true;
      recolor-darkcolor = "#CDD6F4"; # Catppuccin text
      recolor-lightcolor = "#1E1E2E"; # Catppuccin base
      # スクロール設定
      scroll-step = 50;
      zoom-step = 10;
      # 表示設定
      statusbar-h-padding = 8;
      statusbar-v-padding = 4;
      pages-per-row = 1;
    };
  };
}
