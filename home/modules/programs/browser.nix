{inputs, config, pkgs, ...}:
let
  vivaldi = pkgs.vivaldi.override { proprietaryCodecs = true; };
  browser = pkgs.writeShellScriptBin "browser" ''
    exec ${vivaldi}/bin/vivaldi "$@"
  '';
in {
  home.packages = [
    browser
  ];
  programs = {
    vivaldi = {
      enable = true;
      package = vivaldi;
      commandLineArgs = ["--enable-features=WebUIDarkMode" "--force-dark-mode"];
    };
  };
}
