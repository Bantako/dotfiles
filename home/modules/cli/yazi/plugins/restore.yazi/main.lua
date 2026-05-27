local M = {}

local function parse_trash_line(line)
	local date, time, path = line:match("^(%d%d%d%d%-%d%d%-%d%d) (%d%d:%d%d:%d%d) (.+)$")
	if path then
		return { datetime = date .. " " .. time, path = path }
	end
end

local function find_trash_entry(original_path)
	local home = os.getenv("HOME")
	local info_dir = home .. "/.local/share/Trash/info"

	local ls = Command("find")
		:args({ info_dir, "-maxdepth", "1", "-name", "*.trashinfo" })
		:stdout(Command.PIPED)
		:output()
	if not ls then
		return nil, nil
	end

	for info_path in ls.stdout:gmatch("[^\n]+") do
		if info_path ~= "" then
			local f = io.open(info_path, "r")
			if f then
				for line in f:lines() do
					local p = line:match("^Path=(.+)$")
					if p then
						p = p:gsub("%%(%x%x)", function(h)
							return string.char(tonumber(h, 16))
						end)
						if p == original_path then
							f:close()
							local fname = info_path:match("([^/]+)%.trashinfo$")
							return fname, info_path
						end
					end
				end
				f:close()
			end
		end
	end
	return nil, nil
end

local function restore_file(original_path)
	local fname, info_path = find_trash_entry(original_path)
	if not fname then
		return false, "not found in trash index"
	end

	local home = os.getenv("HOME")
	local trash_file = home .. "/.local/share/Trash/files/" .. fname

	local parent = original_path:match("^(.+)/[^/]+$")
	if parent then
		Command("mkdir"):args({ "-p", parent }):spawn():wait()
	end

	local status = Command("mv"):args({ trash_file, original_path }):spawn():wait()
	if status and status.success then
		os.remove(info_path)
		return true, nil
	end
	return false, "mv failed"
end

function M:entry()
	local check = Command("trash-list"):stdout(Command.PIPED):stderr(Command.NULL):output()
	if not check or check.stdout:match("^%s*$") then
		ya.notify({ title = "Trash", content = "Trash is empty", level = "info", timeout = 3 })
		return
	end

	-- fzf の選択結果を tmpfile 経由で受け取る（ya.mgr_emit shell で terminal 制御を渡す）
	local tmpfile = os.tmpname()
	ya.mgr_emit("shell", {
		"trash-list | fzf --multi --prompt='Restore from trash> ' --reverse > " .. ya.quote(tmpfile),
		block = true,
	})

	local f = io.open(tmpfile, "r")
	os.remove(tmpfile)
	if not f then
		return
	end

	local lines = {}
	for line in f:lines() do
		lines[#lines + 1] = line
	end
	f:close()

	if #lines == 0 then
		return
	end

	local restored, failed = 0, 0
	for _, line in ipairs(lines) do
		local entry = parse_trash_line(line)
		if entry then
			local ok, err = restore_file(entry.path)
			if ok then
				restored = restored + 1
			else
				failed = failed + 1
				ya.notify({
					title = "Restore failed",
					content = entry.path .. " — " .. tostring(err),
					level = "error",
					timeout = 5,
				})
			end
		end
	end

	if restored > 0 then
		ya.notify({
			title = "Restored",
			content = string.format("%d file(s) restored", restored),
			level = "info",
			timeout = 3,
		})
	end
end

return M
