{pkgs, ...}: {
  home.packages = with pkgs; [
    file          # mime-ext の fallback_file1 が使う file(1) コマンド
    mediainfo     # video/audio ファイルのメタデータ表示
    poppler-utils # pdftoppm: PDF 1ページ目を PNG 化してプレビュー表示
    libarchive    # bsdtar: CBZ/CBR 両対応（ZIP・RAR 統一展開）
  ];

  programs.yazi = {
    enable = true;
    package = pkgs.yazi;
  };
  xdg.configFile."yazi/yazi.toml".source = ./yazi/yazi.toml;
  xdg.configFile."yazi/keymap.toml".source = ./yazi/keymap.toml;
  xdg.configFile."yazi/init.lua".source = ./yazi/init.lua;
  xdg.configFile."yazi/plugins".source = ./yazi/plugins;
  xdg.configFile."yazi/flavors".source = ./yazi/flavors;
}
