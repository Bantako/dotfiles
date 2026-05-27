local M = {}

function M:entry()
	local check = Command("trash-list"):stdout(Command.PIPED):stderr(Command.NULL):output()
	if not check or check.stdout:match("^%s*$") then
		ya.notify({ title = "Trash", content = "Trash is empty", level = "info", timeout = 3 })
		return
	end

	ya.mgr_emit("shell", {
		[[
tmpsel=$(mktemp)
trash-list 2>/dev/null | cut -c21- \
  | fzf --multi --prompt="Restore from trash> " --reverse > "$tmpsel" \
  || { rm -f "$tmpsel"; exit 0; }
[ ! -s "$tmpsel" ] && { rm -f "$tmpsel"; exit 0; }

TRASH_INFO="$HOME/.local/share/Trash/info"
TRASH_FILES="$HOME/.local/share/Trash/files"
count=0

while IFS= read -r original; do
    [ -z "$original" ] && continue
    for info in "$TRASH_INFO"/*.trashinfo; do
        [ -f "$info" ] || continue
        raw=$(grep -m1 "^Path=" "$info" | cut -d= -f2-)
        if [ "$raw" = "$original" ]; then
            fname=$(basename "$info" .trashinfo)
            mkdir -p "$(dirname "$original")"
            if mv "$TRASH_FILES/$fname" "$original"; then
                rm -f "$info"
                count=$((count+1))
            fi
            break
        fi
    done
done < "$tmpsel"

rm -f "$tmpsel"

if [ "$count" -gt 0 ]; then
    printf 'Restored %d file(s). Press Enter.\n' "$count"
    read -r _
fi
exit 0
]],
		block = true,
	})
end

return M
