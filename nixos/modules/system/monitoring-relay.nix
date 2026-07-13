{ config, pkgs, ... }:

let
  relayScript = ../../../tools/monitoring_relay.py;
in
{
  systemd.services.hermes-monitoring-relay = {
    description = "Validate Gatus alerts and forward incidents to Hermes";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "morikawa";
      Restart = "on-failure";
      RestartSec = "10s";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ReadOnlyPaths = [
        config.sops.secrets.hermes_monitor_webhook_secret.path
        config.sops.secrets.monitor_relay_token.path
      ];
    };

    script = ''
      # LAN アドレスのみに束縛する。tailscale0 は trustedInterfaces のため
      # 0.0.0.0 だと tailnet 全体から到達可能になってしまう
      export MONITOR_RELAY_HOST=192.168.11.3
      export MONITOR_RELAY_TOKEN="$(cat ${config.sops.secrets.monitor_relay_token.path})"
      export HERMES_WEBHOOK_SECRET="$(cat ${config.sops.secrets.hermes_monitor_webhook_secret.path})"
      export HERMES_WEBHOOK_URL="http://127.0.0.1:8644/webhooks/homelab-alerts"
      exec ${pkgs.python3}/bin/python3 ${relayScript}
    '';
  };

  # Gatus runs on the NAS. It may reach the relay, but other LAN clients may not.
  networking.firewall.extraCommands = ''
    ${pkgs.iptables}/bin/iptables -A nixos-fw -p tcp -s 192.168.11.9 --dport 8643 -j ACCEPT
  '';
  networking.firewall.extraStopCommands = ''
    ${pkgs.iptables}/bin/iptables -D nixos-fw -p tcp -s 192.168.11.9 --dport 8643 -j ACCEPT || true
  '';
}
