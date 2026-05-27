local M = {}

function M:peek(job)
	local output, err = Command("mediainfo"):arg(tostring(job.file.url)):stdout(Command.PIPED):output()
	if not output then
		ya.preview_widgets(job, {
			ui.Text({ ui.Line("mediainfo error: " .. tostring(err)) }):area(job.area),
		})
		return
	end

	local lines = {}
	local skip = job.skip
	local i = 0
	for line in output.stdout:gmatch("[^\n]+") do
		i = i + 1
		if i > skip then
			lines[#lines + 1] = ui.Line(line)
		end
		if #lines >= job.area.h then
			break
		end
	end

	ya.preview_widgets(job, { ui.Text(lines):area(job.area) })
end

function M:seek(job)
	local h = cx.active.preview.skip + job.units
	ya.preview_code({ skip = math.max(0, h) })
end

return M
