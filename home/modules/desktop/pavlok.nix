{ pkgs, ... }:

let
  pavlok-stimulus = pkgs.writeShellScriptBin "pavlok-stimulus" ''
    exec ${pkgs.python3}/bin/python3 ${./scripts/pavlok-stimulus.py} "$@"
  '';
in
{
  # bedtime の定時 vibe は n8n (nixos/modules/system/n8n.nix) の
  # ワークフローに移行済み。CLI は手動テスト・デバッグ用に残す
  home.packages = [ pavlok-stimulus ];
}
