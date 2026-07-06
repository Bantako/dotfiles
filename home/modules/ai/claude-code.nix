{ config, pkgs, inputs, lib, ... }:

let
  system = pkgs.stdenv.hostPlatform.system;

  # nixpkgs未収録のため npx 経由で実行するwrapper（nodejs_22はtools.nixで導入済み）
  ccusage = pkgs.writeShellScriptBin "ccusage" ''
    exec ${pkgs.nodejs_22}/bin/npx -y ccusage "$@"
  '';
in {
  # overlay 方式
  nixpkgs.overlays = [
    inputs.claude-code.overlays.default
  ];

  home.packages = with pkgs; [
    claude-code
    ccusage
  ];

  _module.args.claudeAliases = {
    ccode = "claude";
    cld = "claude";
  };
}
