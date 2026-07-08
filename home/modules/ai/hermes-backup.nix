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

    # ~/.hermes のテキスト設定 (config.yaml / SOUL.md / skills 等) を etckeeper 方式で
    # ローカル git に自動コミットする。エージェント自身が設定を書き換えるため、
    # 「いつ何が変わったか」の履歴と破損時の復元点を確保する。.git ごと NAS に同期される。
    # 除外は .gitignore ではなく .git/info/exclude で管理する
    # (home-manager の symlink .gitignore は git が読まないため)。
    GIT="${pkgs.git}/bin/git -C ${hermesDir}"
    [ -d "${hermesDir}/.git" ] || $GIT init --quiet
    cat > "${hermesDir}/.git/info/exclude" <<'EOF'
    # secrets — 絶対にコミットしない
    auth.json
    .env
    # SQLite / バイナリ状態
    state.db*
    kanban.db*
    *.lock
    *.pid
    # キャッシュ・churn の大きい実行時データ
    logs/
    cache/
    audio_cache/
    image_cache/
    sandboxes/
    bin/
    lsp/
    pastes/
    sessions/
    webui/
    gateway/
    kanban/
    pairing/
    cost-snapshots/
    cron/output/
    plugins/
    # skills 配下のキャッシュ/メタデータ (hub カタログに secret 様文字列が混入しうる)
    .hub/
    .archive/
    .curator_backups/
    .usage.json
    .bundled_manifest
    .curator_state
    *_cache.json
    *cache.yaml
    .hermes_history
    .update_check
    .skills_prompt_snapshot.json
    gateway_state.json
    processes.json
    channel_directory.json
    shell-hooks-allowlist.json
    interrupt_debug.log
    *.bak
    *.bak.*
    config.yaml.corrupt.*
    config.yaml.before-*
    EOF
    $GIT add -A
    if ! $GIT diff --cached --quiet; then
      # シークレットスキャンゲート: 実値らしきパターンが staged に入っていたら
      # コミットを中止して ntfy に警告 (git 履歴は消せないため fail-closed)。
      # tar バックアップ自体は従来どおり続行する (バックアップは暗号化先にしか行かない)。
      leaks="$($GIT diff --cached --no-color \
        | grep -E '^\+' \
        | grep -oiE '\b(sk|ghp|gho|glpat|xoxb|xoxp)-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|(api[_-]?key|access[_-]?token|secret|password)[^A-Za-z0-9]{1,4}[A-Za-z0-9_+-]{16,}' \
        | grep -E '[0-9]' \
        | grep -viE '\$|x{4,}|your[_-]|change-me|generate|placeholder|example|redacted|optional|<' \
        | grep -vE '[A-Z0-9_]{16}$' || true)"
      if [ -n "$leaks" ]; then
        echo "SECRET-LIKE PATTERN STAGED — skipping git commit:" >&2
        echo "$leaks" | cut -c1-40 >&2
        $GIT reset --quiet
        ${pkgs.curl}/bin/curl -fsS -o /dev/null \
          --header "Title: hermes-backup: secret detected, commit skipped" \
          --header "Priority: high" \
          -d "~/.hermes の staged 変更にシークレットらしき値を検出。git commit をスキップした。journalctl --user -u hermes-backup で詳細確認。" \
          http://192.168.0.222:8080/nas-alerts || true
      else
        $GIT -c user.name="hermes-backup" -c user.email="hermes-backup@ser7" \
          commit --quiet -m "auto snapshot $(date -Iseconds)"
      fi
    fi

    # SQLite は書き込み中の生ファイルコピーが壊れるため .backup で整合スナップショットを取る
    ${pkgs.sqlite}/bin/sqlite3 "${hermesDir}/state.db" ".backup $STAGE/state.db"
    ${pkgs.sqlite}/bin/sqlite3 "${hermesDir}/kanban.db" ".backup $STAGE/kanban.db"

    # hermes は稼働中なので "file changed as we read it" (exit 1) は警告扱いで許容する
    ( ${pkgs.gnutar}/bin/tar -C "${hermesDir}" \
      --warning=no-file-changed \
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
      -cf - . || [ "$?" -eq 1 ] ) | ${pkgs.openssh}/bin/ssh -o BatchMode=yes nas '
        set -e
        # tar が読み取り専用ディレクトリのモードを保存するため、削除前に書き込み権限を戻す
        for d in ${remoteDir}/hermes.new ${remoteDir}/hermes.old; do
          if [ -d "$d" ]; then
            chmod -R u+w "$d"
            rm -rf "$d"
          fi
        done
        mkdir -p ${remoteDir}/hermes.new
        tar -xf - -C ${remoteDir}/hermes.new
        [ -d ${remoteDir}/hermes ] && mv ${remoteDir}/hermes ${remoteDir}/hermes.old || true
        mv ${remoteDir}/hermes.new ${remoteDir}/hermes
        if [ -d ${remoteDir}/hermes.old ]; then
          chmod -R u+w ${remoteDir}/hermes.old
          rm -rf ${remoteDir}/hermes.old
        fi
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
