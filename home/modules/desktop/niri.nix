{inputs, config, pkgs, ...}: {
  imports = [
    inputs.niri.homeModules.niri
  ];

  programs.niri = {
    enable = true;
    settings =
    let na = config.lib.niri.actions;
    in {
      spawn-at-startup = [
        {
          command = [
            "noctalia-shell"
          ];
        }
      ];
      input = {
        mod-key = "Alt";
      };
      prefer-no-csd = true;
      hotkey-overlay.skip-at-startup = true;
      layout = {
        gaps = 8;        # デフォルト: 16
        border = {
          width = 1;     # デフォルト: 4
        };
      };
      binds = {
        # アプリ起動系
        # バインド被りのため休止

        # 端末起動
        # "Mod+T".action.spawn = [ "terminal" ];
        # ブラウザ起動
        # "Mod+B".action.spawn = [ "browser" ];
        # ランチャー
        # "Mod+D".action.spawn = [ "fuzzel" ];
        "Mod+D".action.spawn = [ "noctalia-shell" "ipc" "call" "launcher" "toggle" ];
        "Mod+C".action.spawn = [ "noctalia-shell" "ipc" "call" "plugin:custom-commands" "toggle" ];

        # 終了
        # "Mod+Shift+E".action = "quit";
        # ロック
        # → スクリーンロック・アイドル管理は Noctalia が担当（settings.json の idle セクション）
        #   screenOff: 600s / lock: 660s / suspend: 1800s
        #   手動ロックは Noctalia のセッションメニュー（lock action）から実行
        # "Mod+Shift+L".action.spawn = [ "swaylock" ];
        # ホットキー表示
        "Mod+slash".action = na.show-hotkey-overlay;
        # ウィンドウを閉じる
        "Mod+Q".action = na.close-window;
        # カラム最大化
        "Mod+F".action = na.maximize-column;
        # フロート化切り替え
        "Mod+V".action = na.toggle-window-floating;
        # オーバービュー
        "Mod+O".action = na.toggle-overview;
        # columnサイズ変更
        "Mod+R".action = na.switch-preset-column-width;

        # フォーカス移動
        "Mod+H".action = na.focus-column-left;
        "Mod+L".action = na.focus-column-right;
        "Mod+J".action = na.focus-workspace-down;
        "Mod+K".action = na.focus-workspace-up;
        "Mod+T".action = na.focus-monitor-left;
        "Mod+Y".action = na.focus-monitor-right;

        # カラム移動
        "Mod+Shift+H".action = na.move-column-left;
        "Mod+Shift+L".action = na.move-column-right;
        "Mod+Shift+J".action = na.move-column-to-workspace-down;
        "Mod+Shift+K".action = na.move-column-to-workspace-up;
        "Mod+Shift+T".action = na.move-column-to-monitor-left;
        "Mod+Shift+Y".action = na.move-column-to-monitor-right;

        # ワークスペース移動
        "Mod+1".action.focus-workspace = [ 1 ];
        "Mod+2".action.focus-workspace = [ 2 ];
        "Mod+3".action.focus-workspace = [ 3 ];
        "Mod+4".action.focus-workspace = [ 4 ];
        "Mod+5".action.focus-workspace = [ 5 ];
        "Mod+6".action.focus-workspace = [ 6 ];
        "Mod+7".action.focus-workspace = [ 7 ];
        "Mod+8".action.focus-workspace = [ 8 ];
        "Mod+9".action.focus-workspace = [ 9 ];
        "Mod+0".action.focus-workspace = [ 10 ];

        # 自作キーボード配列上の動作前提
        # &#=;: '"*@|
        "Mod+Shift+7".action.move-column-to-workspace = [ 1 ];
        "Mod+Shift+3".action.move-column-to-workspace = [ 2 ];
        "Mod+equal".action.move-column-to-workspace = [ 3 ];
        "Mod+semicolon".action.move-column-to-workspace = [ 4 ];
        "Mod+Shift+semicolon".action.move-column-to-workspace = [ 5 ];
        "Mod+apostrophe".action.move-column-to-workspace = [ 6 ];
        "Mod+Shift+apostrophe".action.move-column-to-workspace = [ 7 ];
        "Mod+Shift+8".action.move-column-to-workspace = [ 8 ];
        "Mod+Shift+2".action.move-column-to-workspace = [ 9 ];
        "Mod+Shift+backslash".action.move-column-to-workspace = [ 10 ];
      };
      # config = with inputs.niri.lib.kdl;
    };
  };
}
