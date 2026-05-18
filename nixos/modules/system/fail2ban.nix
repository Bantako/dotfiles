{ ... }:

{
  services.fail2ban = {
    enable = true;
    maxretry = 5;
    ignoreIP = [
      "100.64.0.0/10"
    ];
  };
}
