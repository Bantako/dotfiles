{ config, pkgs, ... }:

let
  ntfyUrl = "$(cat ${config.sops.secrets.ntfy_url.path})";
in {
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
    ];
    exclude = [
      "**/.cache"
      "**/node_modules"
      "**/target"
      "**/.venv"
      "**/dist"
    ];
    repo = "/mnt/ugreen/backup/borg/ser7";
    encryption = {
      mode = "repokey-blake2";
      passCommand = "cat ${config.sops.secrets.borg_passphrase.path}";
    };
    compression = "auto,zstd";
    startAt = "daily";
    prune.keep = { daily = 7; weekly = 4; monthly = 6; };
    postHook = ''
      ${pkgs.curl}/bin/curl -fs --retry 3 \
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
          -H "Title: borg backup FAILED" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light" \
          -d "ser7 home backup failed" \
          "${ntfyUrl}" > /dev/null || true
      '';
    };
  };
}
