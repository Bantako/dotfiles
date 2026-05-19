{pkgs, ...}: {
  home.packages = [ pkgs.vimiv-qt ];

  xdg.configFile."vimiv/vimiv.conf".source = ./vimiv/vimiv.conf;
  xdg.configFile."vimiv/styles/dracula".source = ./vimiv/styles/dracula;
}
