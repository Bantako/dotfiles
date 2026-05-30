{pkgs, ...}: {
  programs.zathura = {
    enable = true;
    options = {
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
