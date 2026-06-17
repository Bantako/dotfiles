{ ... }: {
  programs.ssh = {
    enable = true;
    enableDefaultConfig = false;
    matchBlocks = {
      "nas" = {
        # Tailscale MagicDNS 名。外出先・ローカル問わずこれで解決される
        hostname = "dxp2800-ad69";
        user = "morikawa";
        identityFile = "~/.ssh/id_ed25519";
      };
    };
  };
}
