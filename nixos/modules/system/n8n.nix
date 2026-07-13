{ pkgs, ... }:

let
  # home/modules/desktop/pavlok.nix と同じスクリプトを n8n の
  # Execute Command ノードから呼べるようにシステム側にも用意する
  pavlok-stimulus = pkgs.writeShellScriptBin "pavlok-stimulus" ''
    exec ${pkgs.python3}/bin/python3 ${../../../home/modules/desktop/scripts/pavlok-stimulus.py} "$@"
  '';
  n8nUrl = "https://ser7.taild4ba88.ts.net:8443/";
in
{
  services.n8n = {
    enable = true;
    environment = {
      # tailscale serve 経由でのみ公開するため localhost に束縛
      # (デフォルトは 0.0.0.0 で、tailscale0 が trustedInterfaces のため
      #  生の HTTP :5678 が tailnet に露出してしまう)
      N8N_LISTEN_ADDRESS = "127.0.0.1";
      N8N_EDITOR_BASE_URL = n8nUrl;
      WEBHOOK_URL = n8nUrl;
      N8N_PROXY_HOPS = 1;
      # n8n 2.0 から Execute Command ノードがデフォルト無効化されたため再有効化。
      # 単一ユーザー・tailnet 限定公開なのでリスクは許容範囲
      NODES_EXCLUDE = "[]";
      # _FILE サフィックスにより systemd LoadCredential 経由で渡される。
      # ワークフローの Execute Command ノードからは
      #   pavlok-stimulus --secret "$PAVLOK_API_KEY_FILE" --type vibe --value 10
      # のように参照する
      PAVLOK_API_KEY_FILE = "/run/secrets/pavlok_api_key";
    };
  };

  systemd.services.n8n.path = [ pavlok-stimulus ];

  # hermes WebUI (443) と同様の Tailscale-only HTTPS 公開。443 は使用済みのため 8443
  systemd.services.n8n-tailscale-serve = {
    description = "Tailscale Serve for n8n";
    wants = [ "tailscaled.service" ];
    after = [ "tailscaled.service" ];
    wantedBy = [ "multi-user.target" ];

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.tailscale}/bin/tailscale serve --bg --yes --https=8443 http://127.0.0.1:5678";
    };
  };
}
