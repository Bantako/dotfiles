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
      af = "loudnorm";  # ラウドネス正規化（ファイル間の音量差をならす）
    };
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
