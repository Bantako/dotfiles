{ pkgs, inputs, ... }:

let
  hermesPkg = import ./hermes-package.nix { inherit pkgs inputs; };
in
{
  home.packages = [ hermesPkg ];

  systemd.user.services.hermes-discord = {
    Unit = {
      Description = "Hermes Discord bot";
      # network-online.target は user インスタンスに存在せず依存指定が無視されるため、
      # スクリプト内で実際に疎通を待つ (ブート直後や回線断からの復帰用)。
      StartLimitIntervalSec = 300;
      StartLimitBurst = 5;
      OnFailure = [ "hermes-failure-notify@%N.service" ];
    };
    Service = {
      ExecStart = pkgs.writeShellScript "hermes-discord-start" ''
        until ${pkgs.curl}/bin/curl -fsS --max-time 5 -o /dev/null https://discord.com/api/v10/gateway; do
          echo "waiting for network (discord.com unreachable)..."
          sleep 5
        done
        export DISCORD_BOT_TOKEN="$(cat /run/secrets/discord_bot_token)"
        export DISCORD_ENABLED=true
        export DISCORD_ALLOWED_USERS=383918836014907393
        export DISCORD_HOME_CHANNEL=1513925087105912904
        exec ${hermesPkg}/bin/hermes gateway run --replace
      '';
      Restart = "on-failure";
      RestartSec = "30s";
      TimeoutStopSec = "210s";
    };
    Install.WantedBy = [ "default.target" ];
  };

  # テンプレートユニット: OnFailure=hermes-failure-notify@%n.service で失敗ユニット名を %i に受け取る。
  # 単一の notify.service を複数ユニットから参照すると systemd がトリガー元を特定できず
  # (multiple trigger source candidates)、MONITOR_* が渡らないためこの形にしている。
  systemd.user.services."hermes-failure-notify@" = {
    Unit = {
      Description = "Notify ntfy that %i failed";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${pkgs.writeShellScript "hermes-failure-notify" ''
        FAILED_UNIT="$1"
        # hermes は SIGTERM で exit 1 するため、restart やリビルドでも一瞬 failed になる。
        # 猶予期間 (RestartSec=30s より長め) 待って復帰していれば通知しない。
        # 「落ちて、落ちたまま」(StartLimit 到達・手動停止) のときだけ鳴らす。
        sleep 45
        state="$(systemctl --user is-active "$FAILED_UNIT" 2>/dev/null || true)"
        case "$state" in active|activating) exit 0 ;; esac
        # /run/secrets/ntfy_url はトピック込み URL (hermes 用) なので使わない。
        # nas-alerts へはベース URL 直書き (nas-monitor-heartbeat.nix と同じ方式)。
        ${pkgs.curl}/bin/curl -fs --retry 3 \
          -H "Title: ''${FAILED_UNIT} FAILED" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light,hermes" \
          -d "''${FAILED_UNIT} failed. Result: ''${MONITOR_SERVICE_RESULT:-unknown} Exit: ''${MONITOR_EXIT_CODE:-?} / ''${MONITOR_EXIT_STATUS:-?}" \
          http://192.168.0.222:8080/nas-alerts > /dev/null \
          || echo "ntfy notify failed for ''${FAILED_UNIT}" >&2
      ''} %i";
    };
  };
}
