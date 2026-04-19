#!/usr/bin/env bash
# PKM stale note checker
# 03-Permanent からランダムにサンプリングし、
# バックリンク数と最終更新日を出力する
#
# Usage: pkm-stale-check.sh [options]
#   -n NUM     サンプル数 (default: 100)
#   -b NUM     バックリンク数の上限フィルタ (default: 表示のみ、フィルタなし)
#   -d DAYS    最終更新からの日数フィルタ (default: 表示のみ、フィルタなし)
#
# Example:
#   pkm-stale-check.sh -n 50 -b 2 -d 365
#   → 50件サンプル中、バックリンク2以下かつ365日以上更新なしのノートのみ表示

VAULT="main-vault"
SAMPLE_SIZE=100
MAX_BACKLINKS=""
MAX_DAYS=""

while getopts "n:b:d:" opt; do
  case $opt in
    n) SAMPLE_SIZE="$OPTARG" ;;
    b) MAX_BACKLINKS="$OPTARG" ;;
    d) MAX_DAYS="$OPTARG" ;;
  esac
done

TODAY=$(date +%Y-%m-%d)
TODAY_SEC=$(date +%s)

echo "# PKM stale check - $TODAY"
[[ -n "$MAX_BACKLINKS" ]] && echo "# filter: backlinks <= $MAX_BACKLINKS"
[[ -n "$MAX_DAYS" ]]      && echo "# filter: updated >= ${MAX_DAYS} days ago"
printf "%-50s  %9s  %s\n" "file" "backlinks" "updated"
printf "%-50s  %9s  %s\n" "$(printf '%0.s-' {1..50})" "---------" "----------"

mapfile -t files < <(
  obsidian-cli vault=$VAULT files folder="03-Permanent" \
    | grep "\.md$" \
    | grep -v "decisions/" \
    | shuf -n $SAMPLE_SIZE
)

results=()
for path in "${files[@]}"; do
  name="${path##*/}"
  name="${name%.md}"
  backlinks=$(obsidian-cli vault=$VAULT backlinks file="$name" total 2>/dev/null)
  updated=$(obsidian-cli vault=$VAULT property:read name="updated" file="$name" 2>/dev/null)
  backlinks="${backlinks:-0}"
  updated="${updated:-unknown}"

  # バックリンクフィルタ
  if [[ -n "$MAX_BACKLINKS" ]] && (( backlinks > MAX_BACKLINKS )); then
    continue
  fi

  # 日数フィルタ
  if [[ -n "$MAX_DAYS" && "$updated" != "unknown" ]]; then
    updated_sec=$(date -d "$updated" +%s 2>/dev/null)
    if [[ -n "$updated_sec" ]]; then
      diff_days=$(( (TODAY_SEC - updated_sec) / 86400 ))
      (( diff_days < MAX_DAYS )) && continue
    fi
  fi

  results+=("$(printf '%05d\t%s\t%s\t%s' "$backlinks" "$updated" "$backlinks" "$name")")
done

printf '%s\n' "${results[@]}" | sort | while IFS=$'\t' read -r _ _ bl upd name; do
  printf "%-50s  %9s  %s\n" "$name" "$bl" "$upd"
done
