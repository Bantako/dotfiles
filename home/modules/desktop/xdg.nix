{ inputs, config, pkgs, ...}:
{
  xdg = {
    enable = true;
    userDirs = {
      enable = true;
      createDirectories = true;
      desktop   = "${config.home.homeDirectory}/Desktop";
      documents = "${config.home.homeDirectory}/Documents";
      download  = "${config.home.homeDirectory}/Downloads";
      music     = "${config.home.homeDirectory}/Music";
      pictures  = "${config.home.homeDirectory}/Pictures";
      publicShare = "${config.home.homeDirectory}/Public";
      templates = "${config.home.homeDirectory}/Templates";
      videos    = "${config.home.homeDirectory}/Videos";
    };
    mimeApps = {
      enable = true;
      associations.added = {
        "application/pdf" = [ "org.pwmt.zathura.desktop" ];
      };

      defaultApplications = {
        # browser
        "x-scheme-handler/http"  = [ "vivaldi-stable.desktop" ];
        "x-scheme-handler/https" = [ "vivaldi-stable.desktop" ];
        "text/html"              = [ "vivaldi-stable.desktop" ];
        # file manager
        "inode/directory"   = [ "nemo.desktop" ];
        "x-directory/normal" = [ "nemo.desktop" ];
      };
    };
  };
}
