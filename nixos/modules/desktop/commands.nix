{ inputs, config, pkgs, ... }:

{
  imports = [
    inputs.nix-index-database.nixosModules.nix-index
  ];
}
