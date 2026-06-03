{ pkgs, inputs, ... }:

let
  system = pkgs.stdenv.hostPlatform.system;
in {
  home.packages = [
    inputs.hermes-agent.packages.${system}.default
  ];
}
