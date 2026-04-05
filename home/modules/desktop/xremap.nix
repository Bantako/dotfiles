{ config, pkgs, ... }:

let
  xremapConfig = ''
    modmap:
      - name: "swap ctrl/super in terminals"
        application:
          only:
            - "org.wezfurlong.wezterm"
            - "com.mitchellh.ghostty"
        remap:
          CTRL_L: SUPER_L
          SUPER_L: CTRL_L
  '';
in {
  home.packages = with pkgs; [
    xremap
  ];

  xdg.configFile."xremap/config.yml".text = xremapConfig;

  systemd.user.services.xremap = {
    Unit = {
      Description = "xremap key remapper";
      After = [ "graphical-session.target" ];
      PartOf = [ "graphical-session.target" ];
    };
    Service = {
      ExecStart = "${pkgs.xremap}/bin/xremap --watch ${config.xdg.configHome}/xremap/config.yml";
      Restart = "on-failure";
    };
    Install = {
      WantedBy = [ "graphical-session.target" ];
    };
  };
}
