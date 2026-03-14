{inputs, pkgs, ...}: {
  imports = [
    inputs.niri.homeModules.niri
    inputs.dms.homeModules.dank-material-shell
    inputs.dms.homeModules.niri
  ];

  programs.niri = {
    enable = true;
    settings = {
      # config = with inputs.niri.lib.kdl;
    };
  };
  programs.dank-material-shell = {
    enable = true;

    systemd = {
      enable = true;
      restartIfChanged = true;
    };
    # うまく動作しないのでsystemdオプションを使用する
    # niri = {
    #   enableKeybinds = true;
    #   enableSpawn = true;
    # };
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
