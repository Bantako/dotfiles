{ ... }:

{
  systemd.tmpfiles.rules = [
    "d /srv/paper 0755 morikawa users - -"
    "d /srv/paper/data 0750 morikawa users - -"
    "d /srv/paper/html 0755 morikawa users - -"
    "d /srv/paper/reports 0750 morikawa users - -"
  ];
}
