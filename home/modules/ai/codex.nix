{ pkgs, inputs, ... }:

{
  # 本体 nixpkgs より新しい codex を使うため専用 input から取得
  home.packages = [
    inputs.nixpkgs-codex.legacyPackages.${pkgs.stdenv.hostPlatform.system}.codex
  ];
}
