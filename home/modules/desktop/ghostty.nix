{ pkgs, ... }:

{
  xdg.configFile."ghostty/tab-style.css".text = ''
    headerbar {
      min-height: 20px;
      padding: 0;
      margin: 0;
      background-color: #20222b;
    }
    tabbar tabbox {
      margin: 0;
      padding: 0;
      min-height: 15px;
      background-color: #21222c;
    }

    tabbar tabbox tab {
      margin: 0;
      padding: 2px 8px;
      color: #f8f8f2;
      background-color: #282a36;
      border-right: 1px solid #44475a;
    }

    tabbar tabbox tab:checked {
      background-color: #44475a;
      color: #bd93f9;
      border-bottom: 2px solid #bd93f9;
    }

    tabbar tabbox tab:hover {
      background-color: #44475a;
    }

    tabbar tabbox tab label {
      font-size: 9pt;
    }
  '';

  programs.ghostty = {
    enable = true;
    package = pkgs.ghostty;
    settings = {
      # テーマ・外観
      theme = "Dracula";
      # background-opacity = 0.95;

      # フォント
      font-family = "JetBrainsMono Nerd Font Mono";
      font-size = 13;
      # font-feature = "zero";
      font-codepoint-map = "U+3000-U+9FFF=Source Han Code JP,U+FF00-U+FFEF=Source Han Code JP";
      adjust-cell-height = "1";
      bold-is-bright = false;

      # カーソル
      cursor-style = "bar";
      cursor-style-blink = false;

      # シェル統合
      shell-integration = "zsh";
      shell-integration-features = "cursor,sudo,title";


      # ウィンドウ
      window-padding-x = "8";
      window-padding-y = "0";
      window-padding-balance = true;
      window-theme = "dark";
      gtk-titlebar = false;
      gtk-custom-css = "tab-style.css";

      # クリップボード
      clipboard-read = "allow";
      clipboard-write = "allow";
      copy-on-select = "clipboard";

      # その他
      confirm-close-surface = true;
      mouse-hide-while-typing = true;
      scrollback-limit = 10000;

      # キーバインド
      keybind = [
        # コピー・ペースト
        "super+c=copy_to_clipboard"
        "super+v=paste_from_clipboard"
        "shift+insert=paste_from_selection"

        # タブ操作
        "super+t=new_tab"
        "super+w=close_surface"
        "super+tab=next_tab"
        "super+shift+tab=previous_tab"
        "super+one=goto_tab:1"
        "super+two=goto_tab:2"
        "super+three=goto_tab:3"
        "super+four=goto_tab:4"
        "super+five=goto_tab:5"
        "super+six=goto_tab:6"
        "super+seven=goto_tab:7"
        "super+eight=goto_tab:8"
        "super+nine=last_tab"

        # ペイン分割・移動
        "super+shift+alt+apostrophe=new_split:down"
        "super+shift+alt+five=new_split:right"
        "super+shift+left=goto_split:left"
        "super+shift+right=goto_split:right"
        "super+shift+up=goto_split:top"
        "super+shift+down=goto_split:bottom"
        "super+shift+alt+left=resize_split:left,10"
        "super+shift+alt+right=resize_split:right,10"
        "super+shift+alt+up=resize_split:up,10"
        "super+shift+alt+down=resize_split:down,10"
        "super+z=toggle_split_zoom"

        # フォントサイズ
        "super+plus=increase_font_size:1"
        "super+minus=decrease_font_size:1"
        "super+zero=reset_font_size"

        # スクロール
        "shift+page_up=scroll_page_up"
        "shift+page_down=scroll_page_down"
        "super+u=scroll_page_up"
        "super+d=scroll_page_down"

        # プロンプトジャンプ（シェル統合）
        "super+k=jump_to_prompt:-1"
        "super+j=jump_to_prompt:1"

        # その他
        "alt+enter=toggle_fullscreen"
        "super+n=new_window"
        "super+shift+q=quit"
        "super+r=reload_config"
        "super+l=clear_screen"
        "super+f=text:search"
      ];
    };
  };
}
