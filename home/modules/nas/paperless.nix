{pkgs, ...}:
let
  paperless-preview = pkgs.writeShellScript "paperless-preview" ''
    PAPERLESS_URL="''${PAPERLESS_URL:-http://192.168.0.222:8010}"
    ${pkgs.xh}/bin/xh GET "''${PAPERLESS_URL}/api/documents/$1/" \
      "Authorization:Token ''${PAPERLESS_TOKEN}" 2>/dev/null \
      | ${pkgs.jq}/bin/jq -r \
          '"[\(.created[:10])] \(.title)\n\nタグ数: \(.tags | length)\n\n---\n" + (.content[:500] // "")'
  '';

  paperless-browse = pkgs.writeShellScriptBin "paperless-browse" ''
    set -euo pipefail
    PAPERLESS_URL="''${PAPERLESS_URL:-http://192.168.0.222:8010}"
    : "''${PAPERLESS_TOKEN:?PAPERLESS_TOKEN が未設定}"

    list=$(${pkgs.xh}/bin/xh GET \
      "''${PAPERLESS_URL}/api/documents/?page_size=200&ordering=-created" \
      "Authorization:Token ''${PAPERLESS_TOKEN}" 2>/dev/null \
      | ${pkgs.jq}/bin/jq -r '.results[] | "\(.id)\t\(.created[:10])\t\(.title)"')

    [[ -z "$list" ]] && { echo "ドキュメントが取得できませんでした"; exit 1; }

    selected=$(printf '%s\n' "$list" \
      | ${pkgs.fzf}/bin/fzf \
          --delimiter=$'\t' \
          --with-nth='2,3' \
          --header='日付        タイトル' \
          --preview='${paperless-preview} {1}' \
          --preview-window='right:50%:wrap' \
          --query="''${*:-}")

    [[ -z "$selected" ]] && exit 0

    id=$(printf '%s' "$selected" | cut -f1)
    tmpfile=$(mktemp /tmp/paperless-XXXXXX.pdf)
    trap 'rm -f "$tmpfile"' EXIT

    echo "ダウンロード中 (ID: $id)..."
    ${pkgs.xh}/bin/xh GET "''${PAPERLESS_URL}/api/documents/$id/download/" \
      "Authorization:Token ''${PAPERLESS_TOKEN}" \
      --output "$tmpfile" 2>/dev/null

    zathura "$tmpfile"
  '';
in {
  home.packages = [ paperless-browse ];
}
