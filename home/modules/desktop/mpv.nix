{pkgs, ...}: {
  programs.mpv = {
    enable = true;
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
