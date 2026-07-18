{ config, pkgs, ... }:

let
  ntfyUrl = "$(cat ${config.sops.secrets.ntfy_url.path})";

  # Miniflux は rootless Podman の user service (owner: morikawa) なので、file 単位の
  # data ディレクトリ backup はクラッシュ一貫性が無い。Borg が読む前に論理 dump を
  # backup 対象サブツリー内へ書き出す。pod は止めない。tmp → mv の atomic 置換で、
  # dump 失敗時は直前の known-good dump を保持する。
  # user context の podman/systemd への到達は borg-notify-failure と同じ
  # `systemd-run --machine=morikawa@.host --user` パターンを流用する。
  minifluxDump = pkgs.writeShellScript "miniflux-pg-dump" ''
    set -euo pipefail
    dump_dir="$HOME/.local/share/miniflux/dumps"
    tmp="$dump_dir/miniflux.sql.gz.tmp"
    dest="$dump_dir/miniflux.sql.gz"
    ${pkgs.coreutils}/bin/mkdir -p "$dump_dir"
    ${pkgs.coreutils}/bin/rm -f "$tmp"
    # DB 認証情報は miniflux-db コンテナ自身の POSTGRES_USER/POSTGRES_DB に従う
    # (secret は読まない)。未設定なら値を出さず変数名だけで失敗させる。
    ${pkgs.podman}/bin/podman exec miniflux-db sh -c \
      'set -eu; : "''${POSTGRES_USER:?unset}"; : "''${POSTGRES_DB:?unset}"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      | ${pkgs.gzip}/bin/gzip -c > "$tmp"
    ${pkgs.coreutils}/bin/mv -f "$tmp" "$dest"
  '';
  # Materialious stores its internal accounts, subscriptions, history, and
  # playback progress in SQLite. Snapshot it with SQLite's online backup API
  # before Borg runs; copying its live database/WAL files would not be safe.
  materialiousDump = pkgs.writeShellScript "materialious-sqlite-dump" ''
    set -euo pipefail
    state_dir="$HOME/.local/share/materialious"
    db="$state_dir/materialious.db"
    dump_dir="$state_dir/dumps"
    tmp="$dump_dir/materialious.db.tmp"
    dest="$dump_dir/materialious.db"

    test -f "$db" || exit 0
    ${pkgs.coreutils}/bin/mkdir -p "$dump_dir"
    ${pkgs.coreutils}/bin/rm -f "$tmp"
    ${pkgs.sqlite}/bin/sqlite3 "$db" ".backup '$tmp'"
    ${pkgs.coreutils}/bin/mv -f "$tmp" "$dest"
  '';
  szurubooruDump = pkgs.writeShellScript "szurubooru-pg-dump" ''
    set -euo pipefail
    dump_dir="$HOME/.local/share/szurubooru/dumps"
    tmp="$dump_dir/szurubooru.sql.gz.tmp"
    dest="$dump_dir/szurubooru.sql.gz"
    ${pkgs.coreutils}/bin/mkdir -p "$dump_dir"
    ${pkgs.coreutils}/bin/rm -f "$tmp"
    # DB credentials remain inside the container environment; neither the
    # backup service nor its logs read or display them.
    ${pkgs.podman}/bin/podman exec szurubooru-sql sh -c \
      'set -eu; : "''${POSTGRES_USER:?unset}"; : "''${POSTGRES_DB:?unset}"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      | ${pkgs.gzip}/bin/gzip -c > "$tmp"
    ${pkgs.coreutils}/bin/mv -f "$tmp" "$dest"
  '';
in
{
  services.borgbackup.jobs.home = {
    paths = [
      "/home/morikawa/.ssh"
      "/home/morikawa/.gnupg"
      "/home/morikawa/.config/sops"
      "/home/morikawa/Obsidian"
      "/home/morikawa/Documents"
      "/home/morikawa/Pictures"
      "/home/morikawa/.local/share/atuin"
      "/home/morikawa/.local/share/PrismLauncher"
      "/var/lib/sops-nix/key.txt"
      # n8n のフロー定義と暗号化キー (SQLite, git 管理外の唯一の正本)
      "/var/lib/n8n"
      # Karakeep のブックマークDBと検索index (rootless Podman user service)
      "/home/morikawa/.local/share/karakeep"
      # Miniflux のPostgreSQLデータ (rootless Podman user service)
      "/home/morikawa/.local/share/miniflux"
      # Materialious internal accounts, subscriptions, history, and playlists.
      # The live SQLite database itself is excluded below; its consistent dump
      # under dumps/ is included instead.
      "/home/morikawa/.local/share/materialious"
      # Szurubooru media data and logical PostgreSQL dumps (rootless Podman)
      "/home/morikawa/.local/share/szurubooru"
    ];
    exclude = [
      "**/.cache"
      # 稼働中PostgreSQLの生ファイルは一貫性を持って読めない。preHookの論理dumpだけを残す。
      "**/.local/share/miniflux/postgres"
      "**/node_modules"
      "**/target"
      "**/.venv"
      "**/dist"
      # SQLite's database, WAL, and shared-memory files are replaced by the
      # consistent online snapshot written by materialiousDump above.
      "/home/morikawa/.local/share/materialious/materialious.db*"
    ];
    repo = "/mnt/ugreen/backup/borg/ser7";
    encryption = {
      mode = "repokey-blake2";
      passCommand = "cat ${config.sops.secrets.borg_passphrase.path}";
    };
    compression = "auto,zstd";
    startAt = "daily";
    prune.keep = {
      daily = 7;
      weekly = 4;
      monthly = 6;
    };
    # dump 失敗 (Miniflux 停止中など) は backup ジョブ全体を止めない。直前の
    # known-good dump が残るため、他パスの backup は継続する。
    preHook = ''
      ${pkgs.systemd}/bin/systemd-run --machine=morikawa@.host --user \
        --pipe --wait --collect --quiet -- ${minifluxDump} \
        || echo "miniflux pg_dump failed; keeping previous dump" >&2
      ${pkgs.systemd}/bin/systemd-run --machine=morikawa@.host --user \
        --pipe --wait --collect --quiet -- ${materialiousDump} \
        || echo "materialious SQLite backup failed; keeping previous dump" >&2
      ${pkgs.systemd}/bin/systemd-run --machine=morikawa@.host --user \
        --pipe --wait --collect --quiet -- ${szurubooruDump} \
        || echo "szurubooru pg_dump failed; keeping previous dump" >&2
    '';
    postHook = ''
      ${pkgs.curl}/bin/curl -fs --retry 3 \
        --connect-timeout 5 --max-time 15 \
        -H "Title: borg backup completed" \
        -d "ser7 home backup OK" \
        "${ntfyUrl}" > /dev/null || true
    '';
  };

  systemd.services.borgbackup-job-home = {
    requires = [ "mnt-ugreen.mount" ];
    after = [ "mnt-ugreen.mount" ];
    unitConfig.OnFailure = [ "borg-notify-failure.service" ];
    environment.BORG_RELOCATED_REPO_ACCESS_IS_OK = "yes";
  };

  systemd.services.obsidian-rsync = {
    description = "Obsidian vault rsync to NAS";
    requires = [ "mnt-ugreen.mount" ];
    after = [ "mnt-ugreen.mount" ];
    serviceConfig = {
      Type = "oneshot";
      User = "morikawa";
      ExecStart = "${pkgs.rsync}/bin/rsync -a --delete --copy-links /home/morikawa/Obsidian/main-vault/ /mnt/ugreen/data/obsidian/main-vault/";
    };
  };

  systemd.timers.obsidian-rsync = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "hourly";
      Persistent = true;
    };
  };

  systemd.services.borg-notify-failure = {
    description = "Notify desktop session of borg failure";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = pkgs.writeShellScript "borg-notify-failure" ''
        ${pkgs.systemd}/bin/systemd-run --machine=morikawa@.host --user --collect \
          ${pkgs.libnotify}/bin/notify-send -u critical 'borgbackup failed' 'home バックアップが失敗しました'
        ${pkgs.curl}/bin/curl -fs --retry 3 \
          --connect-timeout 5 --max-time 15 \
          -H "Title: borg backup FAILED" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light" \
          -d "ser7 home backup failed" \
          "${ntfyUrl}" > /dev/null || true
      '';
    };
  };
}
