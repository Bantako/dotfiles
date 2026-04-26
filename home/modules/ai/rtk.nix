{ pkgs, lib, ... }:

let
  version = "0.37.2";
  src = pkgs.fetchurl {
    url = "https://github.com/rtk-ai/rtk/releases/download/v${version}/rtk-x86_64-unknown-linux-musl.tar.gz";
    hash = "sha256-Pft6BWNqaGh7ocWqaW+o1fy0lER97YbZ64uItxAKN8Y=";
  };
  rtk = pkgs.stdenv.mkDerivation {
    pname = "rtk";
    inherit version src;
    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out/bin
      tar -xzf $src -C $out/bin
      chmod +x $out/bin/rtk
    '';
    meta = {
      description = "CLI proxy that reduces LLM token consumption by 60-90%";
      homepage = "https://github.com/rtk-ai/rtk";
      license = lib.licenses.mit;
      platforms = [ "x86_64-linux" ];
    };
  };
in {
  home.packages = [ rtk ];
}
