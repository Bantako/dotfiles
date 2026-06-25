{ ... }: {
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    matchBlocks = {
      "nas" = {
        # 外出先では tailscale + MagicDNS 経由。ただしNAS側のfwmark周りで
        # tailscale IPへのSSHが通らないバグあり → 調査未了
        hostname = "192.168.0.222";
        user = "morikawa";
        identityFile = "~/.ssh/id_ed25519";
      };
    };
  };
}
