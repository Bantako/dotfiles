local M = {}

function M:peek(job)
	local cache = ya.file_cache(job)
	if not cache then return end

	if not fs.cha(cache) then
		local status, _ = Command("sh"):args({ "-c",
			string.format(
				"img=$(bsdtar -tf %q | grep -iE '\\.(jpe?g|png|webp|gif|bmp)$' | sort | head -1)"
				.. " && [ -n \"$img\" ] && bsdtar -xOf %q \"$img\" | convert - PNG:%q",
				tostring(job.file.url), tostring(job.file.url), tostring(cache)
			)
		}):status()
		if not status or not status.success then return end
	end

	ya.image_show(cache, job.area)
	ya.preview_widgets(job, {})
end

function M:seek() end

return M
