{ inputs, config, pkgs, ...}:
{
  # xdg-user-dirs-update がシステムロケール(ja_JP)を見てディレクトリ名を
  # 日本語に上書きするのを防ぐ。en_US で作成済みと宣言しておく。
  xdg.configFile."user-dirs.locale".text = "en_US";

  xdg = {
    enable = true;
    userDirs = {
      enable = true;
      createDirectories = true;
      desktop   = "${config.home.homeDirectory}/Desktop";
      documents = "${config.home.homeDirectory}/Documents";
      download  = "${config.home.homeDirectory}/Downloads";
      music     = "${config.home.homeDirectory}/Music";
      pictures  = "${config.home.homeDirectory}/Pictures";
      publicShare = "${config.home.homeDirectory}/Public";
      templates = "${config.home.homeDirectory}/Templates";
      videos    = "${config.home.homeDirectory}/Videos";
    };
    mimeApps = {
      enable = true;
      associations.added = {
        "application/pdf"      = [ "org.pwmt.zathura-pdf-mupdf.desktop" ];
        "application/epub+zip" = [ "org.pwmt.zathura-pdf-mupdf.desktop" ];
      };

      defaultApplications = {
        # Claude Code URL ハンドラ
        "x-scheme-handler/claude-cli"  = [ "claude-code-url-handler.desktop" ];
        # ブラウザ
        "x-scheme-handler/http"        = [ "vivaldi-stable.desktop" ];
        "x-scheme-handler/https"       = [ "vivaldi-stable.desktop" ];
        "text/html"                    = [ "vivaldi-stable.desktop" ];
        "application/xhtml+xml"        = [ "vivaldi-stable.desktop" ];
        # ファイルマネージャ
        "inode/directory"              = [ "nemo.desktop" ];
        "x-directory/normal"           = [ "nemo.desktop" ];
        # 画像ビューアー (vimiv)
        "image/jpeg"                   = [ "vimiv.desktop" ];
        "image/png"                    = [ "vimiv.desktop" ];
        "image/gif"                    = [ "vimiv.desktop" ];
        "image/bmp"                    = [ "vimiv.desktop" ];
        "image/tiff"                   = [ "vimiv.desktop" ];
        "image/webp"                   = [ "vimiv.desktop" ];
        "image/svg+xml"                = [ "vimiv.desktop" ];
        # 動画・音声プレーヤー (mpv)
        "video/mp4"                    = [ "mpv.desktop" ];
        "video/x-matroska"             = [ "mpv.desktop" ];
        "video/webm"                   = [ "mpv.desktop" ];
        "video/mpeg"                   = [ "mpv.desktop" ];
        "video/x-msvideo"              = [ "mpv.desktop" ];
        "video/quicktime"              = [ "mpv.desktop" ];
        "video/ogg"                    = [ "mpv.desktop" ];
        "audio/mpeg"                   = [ "mpv.desktop" ];
        "audio/flac"                   = [ "mpv.desktop" ];
        "audio/ogg"                    = [ "mpv.desktop" ];
        "audio/wav"                    = [ "mpv.desktop" ];
        "audio/x-wav"                  = [ "mpv.desktop" ];
        "audio/mp4"                    = [ "mpv.desktop" ];
        "audio/aac"                    = [ "mpv.desktop" ];
        # ドキュメントビューアー (zathura)
        "application/pdf"              = [ "org.pwmt.zathura-pdf-mupdf.desktop" ];
        "application/epub+zip"         = [ "org.pwmt.zathura-pdf-mupdf.desktop" ];
        "image/vnd.djvu"               = [ "org.pwmt.zathura-pdf-mupdf.desktop" ];
      };
    };
  };
}
