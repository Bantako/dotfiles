{ pkgs, ... }:

let
  # SOPS管理のトークンをランタイムに読み込んでMCPサーバーを起動するwrapper
  todoist-mcp-server = pkgs.writeShellScriptBin "todoist-mcp-server" ''
    export TODOIST_API_TOKEN=$(cat /run/secrets/todoist-api-token)
    exec ${pkgs.nodejs}/bin/npx -y @abhiz123/todoist-mcp-server "$@"
  '';

  calendar-mcp-python = pkgs.python313.withPackages (ps: [ ps.mcp ]);
  # Hermes は Python 3.12 の site-packages を指す PYTHONPATH/PYTHONHOME を export する。
  # 3.13 の Nix Python を呼ぶ前に両者を除去しないと pydantic_core が ABI 不一致で壊れる。
  # 他の環境変数や PATH には触れない。
  runPython = "${pkgs.coreutils}/bin/env -u PYTHONPATH -u PYTHONHOME ${calendar-mcp-python}/bin/python";
  # khalのローカルCalDAV mirrorだけを読む。Radicaleへの同期・書き込みはしない。
  calendar-mcp-server = pkgs.writeShellScriptBin "calendar-mcp-server" ''
    export PATH=${pkgs.khal}/bin
    exec ${runPython} ${./calendar-mcp-server.py} "$@"
  '';

  # Vault検索と、専用tokenが設定済みの場合だけKarakeep検索を公開する。
  knowledge-mcp-server = pkgs.writeShellScriptBin "knowledge-mcp-server" ''
    if [ -r /run/secrets/karakeep-api-key ]; then
      export KARAKEEP_API_TOKEN="$(cat /run/secrets/karakeep-api-key)"
    fi
    exec ${runPython} ${./knowledge-mcp-server.py} "$@"
  '';

  # Paperlessの文書メタデータだけを検索する。本文・PDF・変更系の操作は公開しない。
  documents-mcp-server = pkgs.writeShellScriptBin "documents-mcp-server" ''
    export PAPERLESS_TOKEN="$(cat /run/secrets/paperless_token)"
    exec ${runPython} ${./documents-mcp-server.py} "$@"
  '';

  # Immichのアセット時刻と市/国レベルの場所候補だけを読む。
  photos-mcp-server = pkgs.writeShellScriptBin "photos-mcp-server" ''
    export IMMICH_TOKEN="$(cat /run/secrets/immich_token)"
    exec ${runPython} ${./photos-mcp-server.py} "$@"
  '';

  # 予定・写真・Paperless書類を同じJST日付で読み取り集計する。
  today-mcp-server = pkgs.writeShellScriptBin "today-mcp-server" ''
    export PATH=${pkgs.khal}/bin
    export IMMICH_TOKEN="$(${pkgs.coreutils}/bin/cat /run/secrets/immich_token)"
    export PAPERLESS_TOKEN="$(${pkgs.coreutils}/bin/cat /run/secrets/paperless_token)"
    exec ${runPython} ${./today-mcp-server.py} "$@"
  '';

  # 公開Transit APIだけを読む。APIキーもローカルの位置情報も渡さない。
  transit-mcp-server = pkgs.writeShellScriptBin "transit-mcp-server" ''
    exec ${runPython} ${./transit-mcp-server.py} "$@"
  '';
in
{
  home.packages = [
    todoist-mcp-server
    calendar-mcp-server
    knowledge-mcp-server
    documents-mcp-server
    photos-mcp-server
    today-mcp-server
    transit-mcp-server
  ];
}
