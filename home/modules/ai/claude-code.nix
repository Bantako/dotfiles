{ config, pkgs, inputs, lib, ... }:

let
  system = pkgs.stdenv.hostPlatform.system;
in {
  # overlay 方式
  nixpkgs.overlays = [
    inputs.claude-code.overlays.default
  ];

  home.packages = with pkgs; [
    claude-code
  ];

  _module.args.claudeAliases = {
    ccode = "claude;";
  };
}
