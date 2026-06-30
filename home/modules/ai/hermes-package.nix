{ pkgs, inputs }:

let
  system = pkgs.stdenv.hostPlatform.system;
  hermesSrc = pkgs.applyPatches {
    name = "hermes-agent-safe-tmp-src";
    src = inputs.hermes-agent;
    patches = [ ../../../patches/hermes-safe-tmp-deletes.patch ];
  };
  extraDependencyGroups = [
    "anthropic"
    "azure-identity"
    "bedrock"
    "daytona"
    "dingtalk"
    "edge-tts"
    "exa"
    "fal"
    "feishu"
    "firecrawl"
    "hindsight"
    "honcho"
    "messaging"
    "modal"
    "parallel-web"
    "tts-premium"
    "voice"
  ]
  ++ pkgs.lib.optionals pkgs.stdenv.isLinux [ "matrix" ];
in
pkgs.callPackage "${hermesSrc}/nix/hermes-agent.nix" {
  inherit (inputs.hermes-agent.inputs) uv2nix pyproject-nix pyproject-build-systems;
  npm-lockfile-fix = inputs.hermes-agent.inputs.npm-lockfile-fix.packages.${system}.default;
  rev = inputs.hermes-agent.rev or null;
  inherit extraDependencyGroups;
}
