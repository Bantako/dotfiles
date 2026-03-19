{inputs, config, pkgs, ...}: {
  imports = [
    inputs.niri.homeModules.niri
    inputs.dms.homeModules.dank-material-shell
    inputs.dms.homeModules.niri
  ];

  programs.niri = {
    enable = true;
    settings = 
    let na = config.lib.niri.actions;
    in {
      input = {
        mod-key = "Alt";
      };
      binds = {
        # 端末起動
        "Mod+T".action.spawn = [ "Wezterm" ];
        # ランチャー
        "Mod+D".action.spawn = [ "fuzzel" ];
        # 終了
        # "Mod+Shift+E".action = "quit";
        # ロック
        "Mod+Shift+L".action.spawn = [ "swaylock" ];
        # ホットキー表示
        "Mod+slash".action = na.show-hotkey-overlay;
        # ウィンドウを閉じる
        "Mod+Q".action = na.close-window;
        # カラム最大化
        "Mod+F".action = na.fullscreen-window;
        # フロート化切り替え
        "Mod+V".action = na.toggle-window-floating;
        # オーバービュー
        "Mod+O".action = na.toggle-overview;

        # フォーカス移動
        "Mod+H".action = na.focus-column-left;
        "Mod+L".action = na.focus-column-right;
        # "Mod+K".action = "focus-up";
        # "Mod+J".action = "focus-down";

        # カラム移動
        # "Mod+Shift+H".action = na.move-column-left;
        # "Mod+Shift+L".action = na.move-column-right;

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
  programs.dank-material-shell = {
    enable = true;

    systemd = {
      enable = true;
      restartIfChanged = true;
    };
    # うまく動作しないのでsystemdオプションを使用する
    # niri = {
    #   enableKeybinds = true;
    #   enableSpawn = true;
    # };
  };

  # fuzzel
  xdg.configFile."fuzzel/fuzzel.ini".text = ''
    [main]
    font=JetBrainsMono Nerd Font:size=12
    width=40
    lines=10

    # dracula color scheme
    [colors]
    background=282a36dd
    text=f8f8f2ff
    match=8be9fdff
    selection-match=be9fdff
    selection=44475add
    selection-text=f8f8f2ff
    border=bd93f9ff
  '';

}
