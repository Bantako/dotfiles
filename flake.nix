{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixos-hardware.url = "github:NixOS/nixos-hardware/master";
    xremap.url = "github:xremap/nix-flake";
    niri.url = "github:sodiboo/niri-flake";
    niri.inputs.nixpkgs.follows = "nixpkgs";
    claude-code.url = "github:sadjow/claude-code-nix";
    hermes-agent.url = "github:NousResearch/hermes-agent";
    herdr.url = "github:ogulcancelik/herdr";
    zen-browser.url = "github:youwen5/zen-browser-flake";
    zen-browser.inputs.nixpkgs.follows = "nixpkgs";
    nix-index-database.url = "github:nix-community/nix-index-database";
    nix-index-database.inputs.nixpkgs.follows = "nixpkgs";

    noctalia = {
      url = "github:noctalia-dev/noctalia-shell";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    stylix = {
      url = "github:danth/stylix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs:
    let
      # ghostty 1.3.1: setCursorLocation に 1x1px ではなくセル全体を渡すパッチ
      # imePoint() が返す y はセル下端なので top-left 基準に戻し、height も実セル高さにする。
      # Niri が候補窓を画面上端に反転したとき入力行を覆わなくなる。
      ghosttyImeOverlay = final: prev: {
        ghostty = prev.ghostty.overrideAttrs (old: {
          patches = (old.patches or [ ]) ++ [
            ./patches/ghostty-ime-cursor-rect.patch
          ];
        });
      };
    in
    {
      nixosConfigurations = {
        ser7 = inputs.nixpkgs.lib.nixosSystem {
          system = "x86_64-linux";
          modules = [
            ./nixos/hosts/ser7/default.nix
            inputs.sops-nix.nixosModules.sops
            { nixpkgs.overlays = [ ghosttyImeOverlay ]; }
          ];
          specialArgs = {
            inherit inputs;
          };
        };
      };
      homeConfigurations = {
        "morikawa@ser7" = inputs.home-manager.lib.homeManagerConfiguration {
          pkgs = import inputs.nixpkgs {
            system = "x86_64-linux";
            config.allowUnfree = true;
            overlays = [ ghosttyImeOverlay ];
          };
          extraSpecialArgs = {
            inherit inputs;
          };
          modules = [
            ./home/home.nix
            inputs.stylix.homeModules.stylix
          ];
        };
      };
    };
}
