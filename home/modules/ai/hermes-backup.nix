{ pkgs, config, ... }:

# ~/.hermes(エージェントの記憶・認証・設定)を NAS の ~/backup/ser7-hermes/ へ毎晩同期する。
# NAS 側では restic コンテナがこのディレクトリを B2 へバックアップする（services/backup）。
# NAS の restic cron は 03:00 UTC (12:00 JST) 実行なので、それより前に同期しておく。
#
# UGOS の rsync はサーバー側パッチでパス検証に失敗し使えないため、tar over ssh で転送する。
# リモートでは一時ディレクトリに展開してからアトミックに入れ替える。
let
  hermesDir = "${config.home.homeDirectory}/.hermes";
  remoteDir = "/home/morikawa/backup/ser7-hermes";

  backupScript = pkgs.writeShellScript "hermes-backup" ''
    set -euo pipefail

    STAGE="$(mktemp -d)"
    trap 'rm -rf "$STAGE"' EXIT

    # SQLite は書き込み中の生ファイルコピーが壊れるため .backup で整合スナップショットを取る
    ${pkgs.sqlite}/bin/sqlite3 "${hermesDir}/state.db" ".backup $STAGE/state.db"
    ${pkgs.sqlite}/bin/sqlite3 "${hermesDir}/kanban.db" ".backup $STAGE/kanban.db"

    ${pkgs.gnutar}/bin/tar -C "${hermesDir}" \
      --exclude './logs' \
      --exclude './cache' \
      --exclude './audio_cache' \
      --exclude './image_cache' \
      --exclude './sandboxes' \
      --exclude './bin' \
      --exclude './lsp' \
      --exclude './state.db*' \
      --exclude './kanban.db*' \
      --exclude './models_dev_cache.json' \
      --exclude '*.lock' \
      --exclude './gateway.pid' \
      -cf - . | ${pkgs.openssh}/bin/ssh -o BatchMode=yes nas '
        set -e
        rm -rf ${remoteDir}/hermes.new
        mkdir -p ${remoteDir}/hermes.new
        tar -xf - -C ${remoteDir}/hermes.new
        rm -rf ${remoteDir}/hermes.old
        [ -d ${remoteDir}/hermes ] && mv ${remoteDir}/hermes ${remoteDir}/hermes.old || true
        mv ${remoteDir}/hermes.new ${remoteDir}/hermes
        rm -rf ${remoteDir}/hermes.old
      '

    ${pkgs.gnutar}/bin/tar -C "$STAGE" -cf - . | ${pkgs.openssh}/bin/ssh -o BatchMode=yes nas '
        set -e
        mkdir -p ${remoteDir}/db
        tar -xf - -C ${remoteDir}/db
      '

    echo "hermes backup synced to nas:${remoteDir}"
  '';
in
{
  systemd.user.services.hermes-backup = {
    Unit.Description = "Sync ~/.hermes to NAS for restic backup";
    Service = {
      Type = "oneshot";
      ExecStart = "${backupScript}";
    };
  };

  systemd.user.timers.hermes-backup = {
    Unit.Description = "Nightly ~/.hermes backup sync";
    Timer = {
      OnCalendar = "*-*-* 02:30:00";
      Persistent = true;
      RandomizedDelaySec = "10m";
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
