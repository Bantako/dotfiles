# Noctalia Shell は以下の機能も担っている（外部デーモン不要）：
#   - スクリーンロック・アイドル管理: settings.json の `idle` セクションで設定
#       screenOffTimeout: 600s / lockTimeout: 660s / suspendTimeout: 1800s
#   - 通知デーモン: `notifications` セクション（mako/dunst は不要）
#   - クリップボード履歴: appLauncher.enableClipboardHistory + cliphist で管理
#       wl-paste --watch cliphist store をランチャー内部で起動
#   - 壁紙管理: `wallpaper` セクション（~/Pictures/Wallpapers からランダム）
#
# 日本語IME は Noctalia ではなく NixOS システム側で管理:
#   nixos/modules/system/locale.nix: i18n.inputMethod (fcitx5 + fcitx5-mozc)

{inputs, config, pkgs, ...}: {
  imports = [
    inputs.noctalia.homeModules.default
  ];

  home.packages = with pkgs; [
    wl-clipboard  # クリップボード操作
    cliphist      # クリップボード履歴
  ];

  home.file.".config/noctalia/settings.json".source = ./noctalia/settings.json;
  programs.noctalia-shell = {
    enable = true;
    plugins = {
      sources = [
        {
          enabled = true;
          name = "Official Noctalia Plugins";
          url = "https://github.com/noctalia-dev/noctalia-plugins";
        }
      ];
      states = {
        kde-connect = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
        privacy-indicator = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
        video-wallpaper = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
        timer = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
        custom-commands = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
        screen-recorder = {
          enabled = true;
          sourceUrl = "https://github.com/noctalia-dev/noctalia-plugins";
        };
      };
      version = 2;
    };
    pluginSettings = {
      custom-commands = {
        commands = [
          {
            name = "フルスクリーン切り替え";
            command = "niri msg action fullscreen-window";
            icon = "arrows-maximize";
          }
          {
            name = "仮フルスクリーン切り替え";
            command = "niri msg action toggle-windowed-fullscreen";
            icon = "window-maximize";
          }
          {
            name = "スクリーンショット（範囲選択）";
            command = "niri msg action screenshot";
            icon = "camera";
          }
          {
            name = "スクリーンショット（全画面）";
            command = "niri msg action screenshot-screen";
            icon = "device-desktop";
          }
          {
            name = "スクリーンショット（ウィンドウ）";
            command = "niri msg action screenshot-window";
            icon = "app-window";
          }
        ];
      };
      kde-connect = {
        hideIfNoDeviceConnected = true;
      };
      privacy-indicator = {
        hideInactive = true;
        enableToast = true;
        iconSpacing = 4;
        removeMargins = false;
        activeColor = "primary";
        inactiveColor = "none";
        micFilterRegex = "";
      };
      video-wallpaper = {
        thumbCacheReady = true;
        enabled = true;
        activeBackend = "qt6-multimedia";
        monitorSpecific = false;
        wallpapersFolder = "~/Pictures/Wallpapers";
        mpvSocket = "/tmp/mpv-socket";
      };
    };
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
