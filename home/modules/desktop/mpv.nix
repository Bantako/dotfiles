{pkgs, ...}: {
  programs.mpv = {
    enable = true;
    config = {
      # レンダリング（AMD / Wayland 向け）
      vo = "gpu-next";
      gpu-api = "vulkan";
      hwdec = "vaapi";

      # 視聴体験
      save-position-on-quit = "yes";
      keep-open = "yes";

      # 音量
      volume-max = 150;
      af = "dynaudnorm=g=5:f=250:r=0.9:p=0.5";  # 単パスリアルタイム。軽い

      # ReplayGain: タグがあればそちらを優先
      replaygain = "track";
      replaygain-clip = "no";
      replaygain-fallback = -3;
    };
    profiles = {
      "audio-only" = {
        "profile-cond" = "audio and not video";
        vo = "null";
      };
    };
    scripts = with pkgs.mpvScripts; [
      mpris  # デスクトップメディアキー/通知連携
    ];
    bindings = {
      # シーク
      h = "seek -5";
      l = "seek 5";
      H = "seek -60";
      L = "seek 60";
      # 音量
      j = "add volume -2";
      k = "add volume 2";
      # チャプター
      J = "add chapter -1";
      K = "add chapter 1";
      # 末尾へジャンプ
      G = "seek 100 absolute-percent";
    };
  };
}