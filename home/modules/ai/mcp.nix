{ pkgs, ... }:

let
  # SOPS管理のトークンをランタイムに読み込んでMCPサーバーを起動するwrapper
  todoist-mcp-server = pkgs.writeShellScriptBin "todoist-mcp-server" ''
    export TODOIST_API_TOKEN=$(cat /run/secrets/todoist-api-token)
    exec ${pkgs.nodejs}/bin/npx -y @abhiz123/todoist-mcp-server "$@"
  '';
in {
  home.packages = [ todoist-mcp-server ];
}
