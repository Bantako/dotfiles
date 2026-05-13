{ inputs, pkgs, ... }:

{
  programs.uwsm = {
    enable = true;
    waylandCompositors.niri = {
      prettyName = "Niri";
      comment = "Niri compositor managed by UWSM";
      binPath = "${inputs.niri.packages.${pkgs.stdenv.hostPlatform.system}.niri-unstable}/bin/niri";
    };
  };
}
