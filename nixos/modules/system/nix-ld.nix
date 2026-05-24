{ pkgs, ... }:
{
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
      expat
      libxcb
      systemd
      alsa-lib
    ];
  };
}
