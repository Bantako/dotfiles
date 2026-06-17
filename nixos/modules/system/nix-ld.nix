{ pkgs, ... }:
{
  # Python の dlopen は NIX_LD_LIBRARY_PATH を参照しないため LD_LIBRARY_PATH に追記する
  # (sessionVariables は pipewire と競合するため extraInit で append する)
  environment.extraInit = ''
    export LD_LIBRARY_PATH=/run/current-system/sw/share/nix-ld/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
  '';

  programs.nix-ld = {
    enable = true;
    libraries = with pkgs; [
      stdenv.cc.cc
      zlib
      openssl
      curl
      glib
      nss
      nspr
      libxkbcommon
      dbus
      atk
      at-spi2-atk
      at-spi2-core
      cups
      cairo
      gtk3
      pango
      libx11
      libxcomposite
      libxdamage
      libxext
      libxfixes
      libxrandr
      libgbm
      libGL
      expat
      libxcb
      systemd
      alsa-lib
    ];
  };
}
