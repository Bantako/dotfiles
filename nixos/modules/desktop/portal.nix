{ config, pkgs, ... }:

{
  xdg.portal = {
    enable = true;
    config.common.default = "*";
  };
  xdg.portal.wlr.enable = true;
}
