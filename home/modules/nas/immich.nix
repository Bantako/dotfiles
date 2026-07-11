{ pkgs, ... }:
let
  immich-preview = pkgs.writeShellScript "immich-preview" ''
    printf '\033_Ga=d\033\\'
    IMMICH_URL="''${IMMICH_URL:-http://192.168.11.9:2283}"
    ${pkgs.xh}/bin/xh GET "''${IMMICH_URL}/api/assets/$1/thumbnail" \
      "x-api-key:''${IMMICH_TOKEN}" \
      size==preview 2>/dev/null \
      | ${pkgs.timg}/bin/timg -pk -g "''${FZF_PREVIEW_COLUMNS:-80}x''${FZF_PREVIEW_LINES:-40}" -
  '';

  immich-browse = pkgs.writeShellScriptBin "immich-browse" ''
    set -euo pipefail
    IMMICH_URL="''${IMMICH_URL:-http://192.168.11.9:2283}"
    : "''${IMMICH_TOKEN:?IMMICH_TOKEN が未設定}"

    list=$(${pkgs.xh}/bin/xh POST \
      "''${IMMICH_URL}/api/search/metadata" \
      "x-api-key:''${IMMICH_TOKEN}" \
      size:=200 page:=1 2>/dev/null \
      | ${pkgs.jq}/bin/jq -r '.assets.items[] | "\(.id)\t\(.fileCreatedAt[:10])\t\(.type)\t\(.originalFileName)"')

    [[ -z "$list" ]] && { echo "アセットが取得できませんでした"; exit 1; }

    selected=$(printf '%s\n' "$list" \
      | ${pkgs.fzf}/bin/fzf \
          --delimiter=$'\t' \
          --with-nth='2,3,4' \
          --header='日付        タイプ  ファイル名' \
          --preview='${immich-preview} {1}' \
          --preview-window='right:50%:wrap' \
          --query="''${*:-}")

    [[ -z "$selected" ]] && exit 0

    id=$(printf '%s' "$selected" | cut -f1)
    type=$(printf '%s' "$selected" | cut -f3)
    filename=$(printf '%s' "$selected" | cut -f4)
    ext="''${filename##*.}"
    tmpfile=$(mktemp "/tmp/immich-XXXXXX.''${ext}")
    trap 'rm -f "$tmpfile"' EXIT

    echo "ダウンロード中 ($filename)..."
    ${pkgs.xh}/bin/xh GET "''${IMMICH_URL}/api/assets/$id/original" \
      "x-api-key:''${IMMICH_TOKEN}" \
      --output "$tmpfile" 2>/dev/null

    if [[ "$type" == "VIDEO" ]]; then
      mpv "$tmpfile"
    else
      vimiv "$tmpfile"
    fi
  '';
in {
  home.packages = with pkgs; [
    immich-go
    timg
    immich-browse
  ];
}
