local M = {}

function M:peek(job)
	local cache = ya.file_cache(job)
	if not cache then return end

	if not fs.cha(cache) then
		local status, _ = Command("sh"):args({ "-c",
			string.format(
				"pdftoppm -r 150 -f 1 -l 1 -png %q - > %q",
				tostring(job.file.url), tostring(cache)
			)
		}):status()
		if not status or not status.success then return end
	end

	ya.image_show(cache, job.area)
	ya.preview_widgets(job, {})
end

function M:seek() end

return M
