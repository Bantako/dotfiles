{inputs, config, pkgs, ...}: {
  imports = [
    inputs.niri.homeModules.niri
    inputs.noctalia.homeModules.default
  ];
  xdg.configFile."noctalia/settings.json".force = true;
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
      binds = {
        # 端末起動
        "Mod+T".action.spawn = [ "Wezterm" ];
        # ランチャー
        # "Mod+D".action.spawn = [ "fuzzel" ];
        "Mod+D".action.spawn = [ "noctalia-shell" "ipc" "call" "launcher" "toggle" ];
        # 終了
        # "Mod+Shift+E".action = "quit";
        # ロック
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

        # フォーカス移動
        "Mod+H".action = na.focus-column-left;
        "Mod+L".action = na.focus-column-right;
        # "Mod+K".action = "focus-up";
        # "Mod+J".action = "focus-down";

        # カラム移動
        "Mod+Shift+H".action = na.move-column-left;
        "Mod+Shift+L".action = na.move-column-right;

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

  programs.noctalia-shell = {
    enable = true;

    settings = {
      bar = {
        barType = "simple";
        position = "top";
        monitors = [ ]; # 必要になったら "eDP-1" などを追加
        density = "default";
        showOutline = false;
        showCapsule = true;
        capsuleOpacity = 0.5;
        capsuleColorKey = "none";
        widgetSpacing = 6;
        contentPadding = 2;
        fontScale = 1;
        enableExclusionZoneInset = true;
        backgroundOpacity = 0.93;
        useSeparateOpacity = false;
        floating = false;
        marginVertical = 4;
        marginHorizontal = 4;
        frameThickness = 8;
        frameRadius = 12;
        outerCorners = false;
        hideOnOverview = false;
        displayMode = "always_visible";
        autoHideDelay = 500;
        autoShowDelay = 150;
        showOnWorkspaceSwitch = true;

        widgets = {
          left = [
            {
              colorizeSystemIcon = "none";
              customIconPath = "";
              enableColorization = false;
              icon = "rocket";
              iconColor = "none";
              id = "Launcher";
              useDistroLogo = true;
            }
            {
              colorizeIcons = false;
              hideMode = "hidden";
              id = "ActiveWindow";
              maxWidth = 145;
              scrollingMode = "hover";
              showIcon = true;
              textColor = "none";
              useFixedWidth = false;
            }
            {
              compactMode = false;
              hideMode = "hidden";
              hideWhenIdle = false;
              id = "MediaMini";
              maxWidth = 145;
              panelShowAlbumArt = true;
              scrollingMode = "hover";
              showAlbumArt = true;
              showArtistFirst = true;
              showProgressRing = true;
              showVisualizer = false;
              textColor = "none";
              useFixedWidth = false;
              visualizerType = "linear";
            }
          ];

          center = [
            {
              characterCount = 2;
              colorizeIcons = false;
              emptyColor = "secondary";
              enableScrollWheel = true;
              focusedColor = "primary";
              followFocusedScreen = false;
              fontWeight = "bold";
              groupedBorderOpacity = 1;
              hideUnoccupied = false;
              iconScale = 0.8;
              id = "Workspace";
              labelMode = "index";
              occupiedColor = "secondary";
              pillSize = 0.6;
              showApplications = false;
              showApplicationsHover = false;
              showBadge = true;
              showLabelsOnlyWhenOccupied = true;
              unfocusedIconsOpacity = 1;
            }
          ];

          right = [
            {
              blacklist = [ ];
              chevronColor = "none";
              colorizeIcons = false;
              drawerEnabled = true;
              hidePassive = false;
              id = "Tray";
              pinned = [ ];
            }
            {
              hideWhenZero = false;
              hideWhenZeroUnread = false;
              iconColor = "none";
              id = "NotificationHistory";
              showUnreadBadge = true;
              unreadBadgeColor = "primary";
            }
            {
              deviceNativePath = "__default__";
              displayMode = "graphic-clean";
              hideIfIdle = false;
              hideIfNotDetected = true;
              id = "Battery";
              showNoctaliaPerformance = false;
              showPowerProfiles = false;
            }
            {
              displayMode = "onhover";
              iconColor = "none";
              id = "Volume";
              middleClickCommand = "pwvucontrol || pavucontrol";
              textColor = "none";
            }
            {
              compactMode = true;
              diskPath = "/";
              iconColor = "none";
              id = "SystemMonitor";
              showCpuCores = false;
              showCpuFreq = false;
              showCpuTemp = true;
              showCpuUsage = true;
              showDiskAvailable = false;
              showDiskUsage = false;
              showDiskUsageAsPercent = false;
              showGpuTemp = false;
              showLoadAverage = false;
              showMemoryAsPercent = false;
              showMemoryUsage = true;
              showNetworkStats = false;
              showSwapUsage = false;
              textColor = "none";
              useMonospaceFont = true;
              usePadding = false;
            }
            {
              clockColor = "none";
              customFont = "";
              formatHorizontal = "MM/dd HH:mm";
              formatVertical = "HH mm - dd MM";
              id = "Clock";
              tooltipFormat = "MM/dd HH:mm ddd";
              useCustomFont = false;
            }
            {
              colorizeDistroLogo = false;
              colorizeSystemIcon = "none";
              customIconPath = "";
              enableColorization = false;
              icon = "noctalia";
              id = "ControlCenter";
              useDistroLogo = false;
            }
          ];
        };

        mouseWheelAction = "none";
        reverseScroll = false;
        mouseWheelWrap = true;
        middleClickAction = "settings";
        middleClickFollowMouse = false;
        middleClickCommand = "";
        rightClickAction = "controlCenter";
        rightClickFollowMouse = true;
        rightClickCommand = "";
        screenOverrides = [ ];
      };
      general = {
        compactLockScreen = true;
        clockStyle = "analog";
        clockFormat = "MM/dd HH:mm";
        passwordChars = true;
      };
      colorSchemes = {
        predefinedScheme = "Dracula";
        drakMode = true;
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
