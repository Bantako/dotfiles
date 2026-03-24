{inputs, config, pkgs, ...}:
let
  terminal = pkgs.writeShellScriptBin "terminal" ''
    exec ${pkgs.wezterm}/bin/wezterm "$@"
  '';
in {
  home.file.".config/wezterm/wezterm.lua".source = ./wezterm/wezterm.lua;
  home.file.".config/wezterm/keybinds.lua".source = ./wezterm/keybinds.lua;

  home.packages = with pkgs; [
    wezterm
    terminal
  ];
}
