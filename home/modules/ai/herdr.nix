{ pkgs, inputs, ... }:

let
  system = pkgs.stdenv.hostPlatform.system;
  herdrPkg = inputs.herdr.packages.${system}.default.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      ../../../patches/herdr-detect-claude-unwrapped.patch
    ];
  });
in
{
  home.packages = [ herdrPkg ];

  xdg.configFile."herdr/config.toml".text = ''
    [keys]
    focus_agent = "prefix+1..9"
    switch_tab = ""

    [experimental]
    kitty_graphics = true
  '';
}
