local get_hovered = ya.sync(function()
	local hovered = cx.active.current.hovered
	if hovered then
		return tostring(hovered.url)
	end
end)

return {
	entry = function()
		local url = get_hovered()
		if not url then
			return ya.notify { title = "mediainfo", content = "No file selected", level = "warn", timeout = 3 }
		end

		local child = Command("sh")
			:args({ "-c", "mediainfo " .. ya.quote(url) .. " | bat --paging=always --style=plain" })
			:stdin(Command.INHERIT)
			:stdout(Command.INHERIT)
			:stderr(Command.INHERIT)
			:spawn()

		if child then
			child:wait()
		end
	end,
}
