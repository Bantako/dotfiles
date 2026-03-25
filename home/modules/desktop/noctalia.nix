{inputs, config, pkgs, ...}: {
  imports = [
    inputs.noctalia.homeModules.default
  ];
  home.file.".config/noctalia/settings.json".source = ./noctalia/settings.json;
  programs.noctalia-shell = {
    enable = true;
  };

  # fuzzel
  xdg.configFile."fuzzel/fuzzel.ini".text = ''
    [main]
    font=JetBrainsMono Nerd Font:size=12
    width=40
    lines=10

    # dracula color scheme
    [colors]
    background=282a36dd
    text=f8f8f2ff
    match=8be9fdff
    selection-match=be9fdff
    selection=44475add
    selection-text=f8f8f2ff
    border=bd93f9ff
  '';
}
