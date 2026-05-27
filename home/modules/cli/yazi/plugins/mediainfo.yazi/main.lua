local M = {}

function M:entry(job)
	local file = cx.active.current.hovered
	if not file then
		ya.notify({ title = "mediainfo", content = "No file selected", level = "warn", timeout = 3 })
		return
	end

	local child = Command("sh")
		:args({ "-c", "mediainfo " .. ya.quote(tostring(file.url)) .. " | bat --paging=always --style=plain" })
		:stdin(Command.INHERIT)
		:stdout(Command.INHERIT)
		:stderr(Command.INHERIT)
		:spawn()

	if child then
		child:wait()
	end
end

return M
