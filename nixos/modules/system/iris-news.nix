{ config, pkgs, ... }:

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
