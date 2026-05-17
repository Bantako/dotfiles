{ pkgs, ... }: {
  home.packages = with pkgs; [
    immich-go  # NAS Immich への bulk upload
  ];
}
