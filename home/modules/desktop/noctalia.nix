{inputs, config, pkgs, lib, ...}: {
  imports = [
    # homeModules.default は self.packages を参照し noctalia-qs（llama.cpp）を引き込むため
    # home-module.nix（オプション定義のみ）を直接インポートする
    (inputs.noctalia + "/nix/home-module.nix")
  ];

  # noctalia 自身の packages.default を使う（noctalia-qs の正しい quickshell でビルド済み）
  # pkgs.quickshell は別バージョンで動作しないため使わない
  # noctalia のピン済み noctalia-qs を使うので我々の flake 側にハッシュ不一致が起きない
  programs.noctalia-shell.package = inputs.noctalia.packages.${pkgs.stdenv.hostPlatform.system}.default;

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

  # fuzzel（noctalia のランチャー）: 色・フォントは stylix が管理
  programs.fuzzel = {
    enable = true;
    settings.main = {
      width = 40;
      lines = 10;
    };
  };
}
