{ pkgs, inputs, ... }:

let
  system = pkgs.stdenv.hostPlatform.system;
in {
  home.packages = [ inputs.herdr.packages.${system}.default ];
}
