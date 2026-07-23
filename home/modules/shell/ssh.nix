{ ... }: {
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    settings = {
      "nas" = {
        # 外出先では tailscale + MagicDNS 経由。ただしNAS側のfwmark周りで
        # tailscale IPへのSSHが通らないバグあり → 調査未了
        HostName = "192.168.11.9";
        User = "morikawa";
        IdentityFile = "~/.ssh/id_ed25519";
      };
    };
  };
}
