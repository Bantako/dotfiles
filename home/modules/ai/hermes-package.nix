{ pkgs, inputs }:

let
  system = pkgs.stdenv.hostPlatform.system;
  hermesSrc = pkgs.applyPatches {
    name = "hermes-agent-safe-tmp-src";
    src = inputs.hermes-agent;
    patches = [ ../../../patches/hermes-safe-tmp-deletes.patch ];
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
