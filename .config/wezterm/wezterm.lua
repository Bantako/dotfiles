local wezterm = require("wezterm")

local config = wezterm.config_builder()

-- ****** general behavior ******
config.enable_wayland = false
config.automatically_reload_config = true

-- ****** keybinds ******
-- prefix key（Ctrl + Space）
config.leader = {
	key = "Space",
	mods = "ALT",
	timeout_milliseconds = 2000,
}

config.send_composed_key_when_left_alt_is_pressed = false
config.send_composed_key_when_right_alt_is_pressed = false

if wezterm.target_triple ~= "aarch64-apple-darwin" then
	config.disable_default_key_bindings = true
	local conf = require("keybinds_linux")
	config.keys = conf.keys
	-- config.key_tables = conf.key_tables
	-- table.insert(config, conf)
end

local keybinds = {
	-- Swap Super and Ctrl

	-- quick select (tmux-fingers)
	{
		mods = "LEADER",
		key = "f",
		action = wezterm.action.QuickSelect,
	},

	-- activate copy mode or vim mode
	{
		mods = "LEADER",
		key = "[",
		action = wezterm.action.ActivateCopyMode,
	},
	-- splitting
	{
		mods = "LEADER",
		key = "v",
		action = wezterm.action.SplitVertical({ domain = "CurrentPaneDomain" }),
	},
	{
		mods = "LEADER",
		key = "s",
		action = wezterm.action.SplitHorizontal({ domain = "CurrentPaneDomain" }),
	},
}

for _, keybind in ipairs(keybinds) do
	table.insert(config.keys, keybind)
end

-- ****** color and fonts ******

config.color_scheme = "Dracula"
config.font = wezterm.font_with_fallback({
	{ family = "JetBrains Mono" },
	{ family = "Hack Nerd Font Mono" },
	{ family = "Source Han Code JP" },
})
config.font_size = 13.0
config.harfbuzz_features = { "zero" }

-- ****** window appearance ******

-- config.window_decorations = "RESIZE"
config.window_padding = {
	left = "0.5cell",
	right = "0.5cell",
	top = "0cell",
	bottom = "0cell",
}

-- ****** tabs ******

-- config.hide_tab_bar_if_only_one_tab = true
config.show_new_tab_button_in_tab_bar = false
config.use_fancy_tab_bar = false
config.tab_max_width = 100
-- config.integrated_title_button_style = "MacOsNative"

config.colors = {
	tab_bar = {
		inactive_tab_edge = "none",
	},
}

-- ****** tabs appearance **
-- tabline.wez
local tabline = wezterm.plugin.require("https://github.com/michaelbrusegard/tabline.wez")
tabline.setup({
	options = {
		-- theme = "catppuccin-mocha",
		-- theme = "cyberpunk",
		-- theme = "Cobalt Neon",
		theme = "Dracula",
		section_separators = {
			left = wezterm.nerdfonts.ple_upper_left_triangle,
			right = wezterm.nerdfonts.ple_lower_right_triangle,
		},
		component_separators = {
			left = wezterm.nerdfonts.ple_forwardslash_separator,
			right = wezterm.nerdfonts.ple_forwardslash_separator,
		},
		tab_separators = {
			left = wezterm.nerdfonts.ple_upper_left_triangle,
			right = wezterm.nerdfonts.ple_lower_right_triangle,
		},
		color_overrides = {
			tab = {
				active = { fg = "#091833", bg = "#59c2c6" },
			},
		},
	},
	sections = {
		tab_active = {
			"index",
			{ "process", padding = { left = 0, right = 1 } },
			"",
			{ "cwd", padding = { left = 1, right = 0 } },
			{ "zoomed", padding = 1 },
		},
		tab_inactive = {
			"index",
			{ "process", padding = { left = 0, right = 1 } },
			"󰉋",
			{ "cwd", padding = { left = 1, right = 0 } },
			{ "zoomed", padding = 1 },
		},
	},
})
return config
