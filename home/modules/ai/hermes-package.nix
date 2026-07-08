{ pkgs, inputs }:

let
  system = pkgs.stdenv.hostPlatform.system;
  hermesSrc = pkgs.applyPatches {
    name = "hermes-agent-patched-src";
    src = inputs.hermes-agent;
    patches = [
      ../../../patches/hermes-safe-tmp-deletes.patch
      # クリティカル層: 不可逆なデータ破壊コマンド (down -v / volume rm /
      # restic forget / b2 delete / DROP DATABASE) は毎回人間の承認必須。
      # セッション承認・allowlist・yolo・smart approve のどれでも素通りさせない。
      # 経緯: wger インシデント (2026-07-08, docs/report-nas-pruning-2026-07-08.md)
      ../../../patches/hermes-critical-approval-gate.patch
    ];
  };
  # 使う機能だけに絞る (2026-07-07 P7)。復帰候補:
  #   daytona — コンテナオーケストレーションを使い始めるなら追加
  extraDependencyGroups = [
    "anthropic" # Anthropic API 直叩き (.env に key あり)
    "messaging" # Discord ほかチャットプラットフォーム基盤
    "exa" # web検索 backend
    "firecrawl" # web抽出 backend
    "parallel-web" # web検索 backend
  ];
in
pkgs.callPackage "${hermesSrc}/nix/hermes-agent.nix" {
  inherit (inputs.hermes-agent.inputs) uv2nix pyproject-nix pyproject-build-systems;
  npm-lockfile-fix = inputs.hermes-agent.inputs.npm-lockfile-fix.packages.${system}.default;
  rev = inputs.hermes-agent.rev or null;
  inherit extraDependencyGroups;
}
