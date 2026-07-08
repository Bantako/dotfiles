{ config, pkgs, ... }:

{
  systemd.services.nas-monitor-heartbeat = {
    description = "Check NAS container-alerts heartbeat, alert ntfy if stale";

    # Needs network to reach ntfy on NAS
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];

    serviceConfig = {
      Type = "oneshot";
      User = "morikawa";
    };

    script = ''
      NTFY_URL="http://192.168.0.222:8080"
      HEARTBEAT_TOPIC="nas-alerts-heartbeat"
      HEARTBEAT_TIMEOUT=1200  # 20 min (2x 10min interval)

      # Fetch heartbeat events from the last 2 hours
      last_time=$(${pkgs.curl}/bin/curl -s --max-time 10 \
        "$NTFY_URL/$HEARTBEAT_TOPIC?since=2h" \
        | ${pkgs.python3}/bin/python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    events = data.get('events', [])
    if events:
        print(events[-1].get('time', 0))
    else:
        print(0)
except Exception:
    print(0)
" 2>/dev/null)

      if [ -z "$last_time" ] || [ "$last_time" -eq 0 ]; then
        # No heartbeat found in window → monitor container likely down
        ${pkgs.curl}/bin/curl -fs --retry 3 \
          -H "Title: NAS Monitor HEARTBEAT LOST" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light,sos" \
          -d "container-alerts heartbeat not found in last 2h (monitor container may be down)" \
          "$NTFY_URL/nas-alerts" > /dev/null || true
        exit 1
      fi

      now=$(date +%s)
      elapsed=$(( now - last_time ))
      if [ "$elapsed" -gt "$HEARTBEAT_TIMEOUT" ]; then
        ${pkgs.curl}/bin/curl -fs --retry 3 \
          -H "Title: NAS Monitor HEARTBEAT STALE" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light,sos" \
          -d "container-alerts heartbeat last seen ''${elapsed}s ago (>20m). Monitor may be stuck or down." \
          "$NTFY_URL/nas-alerts" > /dev/null || true
        exit 1
      fi
    '';
  };

  systemd.timers.nas-monitor-heartbeat = {
    description = "15-minute timer for nas-monitor-heartbeat.service";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*:0/15";   # Every 15 minutes
      Persistent = true;
      Unit = "nas-monitor-heartbeat.service";
    };
  };
}