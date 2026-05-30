{pkgs, ...}: {
  programs.bat = {
    enable = true;
    config = {
      pager = "ov -F";
    };
  };
}
