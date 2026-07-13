{ inputs, pkgs, ... }:
let
  hunkPkg = inputs.hunk.packages.${pkgs.stdenv.hostPlatform.system}.default;
in
{
  programs.hunk = {
    enable = true;
    package = hunkPkg;
    enableClaudeIntegration = true;
    settings = {
      theme = "auto";
      mode = "auto";
      line_numbers = true;
    };
  };

  # Hunkの公式review skillをHermesにも配る。Git pagerはDeltaを維持する。
  home.file.".hermes/skills/hunk-review".source = "${hunkPkg}/skills/hunk-review";
}
