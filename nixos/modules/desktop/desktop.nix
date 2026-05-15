# nixos/modules/desktop/desktop.nix
{ inputs, config, pkgs, ... }:

{
  services.displayManager.sddm = {
    enable = true;
    wayland.enable = true;
    theme = "sddm-astronaut-theme";
    extraPackages = [ pkgs.sddm-astronaut ];
  };

  services.displayManager.sessionPackages = [
    inputs.niri.packages.${pkgs.stdenv.hostPlatform.system}.niri-unstable
  ];

  services.xserver.enable = true;

  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
    jack.enable = true;
    # use the example session manager (no others are packaged yet so this is enabled by default,
    # no need to redefine it in your config for now)
    #media-session.enable = true;
  };

  fonts = {
    packages = with pkgs; [
      noto-fonts-cjk-serif
      noto-fonts-cjk-sans
      noto-fonts-color-emoji
      nerd-fonts.jetbrains-mono
      source-han-code-jp
      migu
    ];
    fontDir.enable = true;
    fontconfig = {
      defaultFonts = {
        serif = ["Noto Serif CJK JP" "Noto Color Emoji"];
        sansSerif = ["Noto Sans CJK JP" "Noto ColorEmoji"];
        monospace = ["JetBrainsMono Nerd Font" "Noto Color Emoji"];
        emoji = ["Noto Color Emoji"];
      };
      localConf = ''
<?xml version="1.0"?>
	<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
	<fontconfig>
	  <description>Change default fonts for Steam client</description>
	  <match>
	    <test name="prgname">
	      <string>steamwebhelper</string>
	    </test>
	    <test name="family" qual="any">
	      <string>sans-serif</string>
	    </test>
	    <edit mode="prepend" name="family">
	      <string>Migu 1P</string>
	    </edit>
	  </match>
	</fontconfig>
      '';
    };
  };
}
