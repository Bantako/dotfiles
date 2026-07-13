{ config, lib, pkgs, ... }:

{
  systemd.tmpfiles.rules = [
    "d /srv/paper 0755 morikawa users - -"
    "d /srv/paper/data 0750 morikawa users - -"
    "d /srv/paper/html 0755 morikawa users - -"
    "d /srv/paper/reports 0750 morikawa users - -"
  ];

  systemd.services.iris-news-build = {
    description = "iris-news daily morning paper build";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];

    environment = {
      # sentence-transformers/NumPy loads native extensions. Login shells get
      # this through nix-ld, but system services do not inherit shell init.
      LD_LIBRARY_PATH = lib.makeLibraryPath [ pkgs.stdenv.cc.cc ];

      # Hermes owns the OpenAI Codex OAuth credential.  The news service only
      # invokes its constrained CLI route and does not receive an API key.
      HOME = "/home/morikawa";
      IRIS_NEWS_LLM_PROVIDER = "hermes-cli";
      IRIS_NEWS_HERMES_COMMAND = "/home/morikawa/.nix-profile/bin/hermes";
      IRIS_NEWS_HERMES_PROVIDER = "openai-codex";
      IRIS_NEWS_HERMES_MODEL = "gpt-5.6-luna";
      IRIS_NEWS_HERMES_TOOLSETS = "safe";
      IRIS_NEWS_HERMES_TIMEOUT = "120";
    };

    serviceConfig = {
      Type = "oneshot";
      User = "morikawa";
      WorkingDirectory = "/home/morikawa/workspace/iris-news";
    };

    script = ''
      export IRIS_NEWS_MINIFLUX_API_TOKEN="$(cat /run/secrets/iris_news_miniflux_api_token)"
      exec ${pkgs.uv}/bin/uv run python -m iris_news build-daily \
        --miniflux-base-url http://dxp2800-ad69.taild4ba88.ts.net:8084 \
        --refresh --ingest \
        --db /srv/paper/data/paper.db
    '';

    unitConfig.OnSuccess = [ "iris-news-publish.service" ];
  };

  # Copy only reconstructable static output to the NAS. The SQLite database
  # remains local to ser7 because it is mutable state used by the signal API.
  # Publishing runs independently after a successful build: an unavailable
  # NAS must not turn a locally generated paper into a failed build.
  systemd.services.iris-news-publish = {
    description = "Publish iris-news static paper to NAS";
    requires = [ "mnt-ugreen.mount" ];
    after = [ "mnt-ugreen.mount" "iris-news-build.service" ];

    serviceConfig = {
      Type = "oneshot";
      User = "morikawa";
    };

    script = ''
      set -euo pipefail
      source_dir=/srv/paper/html
      destination=/mnt/ugreen/services/iris-news/site

      ${pkgs.coreutils}/bin/mkdir -p "$destination"
      ${pkgs.rsync}/bin/rsync -a --delete "$source_dir/" "$destination/"

      latest="$(${pkgs.findutils}/bin/find "$source_dir" -maxdepth 1 -type f -name '*.html' -printf '%f\n' | ${pkgs.coreutils}/bin/sort | ${pkgs.coreutils}/bin/tail -n 1)"
      test -n "$latest"
      ${pkgs.coreutils}/bin/cp "$source_dir/$latest" "$destination/index.html"
    '';
  };

  # The NAS Caddy container is the only LAN peer allowed to reach this API.
  # The service itself binds the ser7 LAN address, never the Tailscale address.
  networking.firewall.extraCommands = ''
    iptables -A nixos-fw -s 192.168.11.9 -p tcp --dport 8000 -j nixos-fw-accept
  '';

  systemd.services.iris-news-api = {
    description = "iris-news signal API for NAS Caddy";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];

    environment = {
      LD_LIBRARY_PATH = lib.makeLibraryPath [ pkgs.stdenv.cc.cc ];
      HOME = "/home/morikawa";
      IRIS_NEWS_LLM_PROVIDER = "hermes-cli";
      IRIS_NEWS_HERMES_COMMAND = "/home/morikawa/.nix-profile/bin/hermes";
      IRIS_NEWS_HERMES_PROVIDER = "openai-codex";
      IRIS_NEWS_HERMES_MODEL = "gpt-5.6-luna";
      IRIS_NEWS_HERMES_TOOLSETS = "safe";
      IRIS_NEWS_HERMES_TIMEOUT = "120";
      IRIS_NEWS_KARAKEEP_BASE_URL = "http://192.168.11.9:3003";
    };

    serviceConfig = {
      Type = "simple";
      User = "morikawa";
      WorkingDirectory = "/home/morikawa/workspace/iris-news";
      Restart = "on-failure";
      RestartSec = "10s";
    };

    script = ''
      export IRIS_NEWS_KARAKEEP_API_TOKEN="$(cat /run/secrets/karakeep-api-key)"
      exec ${pkgs.uv}/bin/uv run uvicorn iris_news.api.main:app \
        --host 192.168.11.3 --port 8000
    '';
  };

  systemd.services.iris-news-static = {
    description = "iris-news static paper server";
    after = [ "iris-news-build.service" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "simple";
      User = "morikawa";
      WorkingDirectory = "/srv/paper/html";
      ExecStart = "${pkgs.python3}/bin/python -m http.server 8788 --bind 127.0.0.1 --directory /srv/paper/html";
      Restart = "on-failure";
    };
  };

  systemd.services.iris-news-tailscale-serve = {
    description = "Tailscale Serve for iris-news";
    after = [ "tailscaled.service" "iris-news-static.service" ];
    wants = [ "tailscaled.service" "iris-news-static.service" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=443 --set-path=/iris-news http://127.0.0.1:8788";
    };
  };

  systemd.timers.iris-news-build = {
    description = "Daily timer for iris-news-build.service";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 06:00:00";
      Persistent = true;
      Unit = "iris-news-build.service";
    };
  };
}
