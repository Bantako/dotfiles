{ pkgs, ... }:

let
  # SOPS管理のトークンをランタイムに読み込んでMCPサーバーを起動するwrapper
  todoist-mcp-server = pkgs.writeShellScriptBin "todoist-mcp-server" ''
    export TODOIST_API_TOKEN=$(cat /run/secrets/todoist-api-token)
    exec ${pkgs.nodejs}/bin/npx -y @abhiz123/todoist-mcp-server "$@"
  '';

  calendar-mcp-python = pkgs.python313.withPackages (ps: [ ps.mcp ]);
  # khalのローカルCalDAV mirrorだけを読む。Radicaleへの同期・書き込みはしない。
  calendar-mcp-server = pkgs.writeShellScriptBin "calendar-mcp-server" ''
    export PATH=${pkgs.khal}/bin
    exec ${calendar-mcp-python}/bin/python ${./calendar-mcp-server.py} "$@"
  '';

  # Vault検索と、専用tokenが設定済みの場合だけKarakeep検索を公開する。
  knowledge-mcp-server = pkgs.writeShellScriptBin "knowledge-mcp-server" ''
    if [ -r /run/secrets/karakeep-api-key ]; then
      export KARAKEEP_API_TOKEN="$(cat /run/secrets/karakeep-api-key)"
    fi
    exec ${calendar-mcp-python}/bin/python ${./knowledge-mcp-server.py} "$@"
  '';

  # Paperlessの文書メタデータだけを検索する。本文・PDF・変更系の操作は公開しない。
  documents-mcp-server = pkgs.writeShellScriptBin "documents-mcp-server" ''
    export PAPERLESS_TOKEN="$(cat /run/secrets/paperless_token)"
    exec ${calendar-mcp-python}/bin/python ${./documents-mcp-server.py} "$@"
  '';
in
{
  home.packages = [
    todoist-mcp-server
    calendar-mcp-server
    knowledge-mcp-server
    documents-mcp-server
  ];
}
