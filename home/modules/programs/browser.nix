{inputs, config, pkgs, ...}:
let
  browser = pkgs.writeShellScriptBin "browser" ''
    exec ${pkgs.vivaldi}/bin/vivaldi "$@"
  '';
in {
  home.packages = with pkgs; [
    browser
    # vivaldi 
  ];
  programs = {
    vivaldi = {
      enable = true;
      commandLineArgs = ["--enable-features=WebUIDarkMode" "--force-dark-mode"];
    };
  };
}
