{ ... }: {
  programs.ssh = {
    enable = true;
    matchBlocks = {
      "nas" = {
        hostname = "192.168.0.222";
        user = "morikawa";
        identityFile = "~/.ssh/id_ed25519";
      };
    };
  };
}
