require("bunny"):setup({
  hops = {
    { key = "/",          path = "/",                                    },
    { key = "t",          path = "/tmp",                                 },
    { key = "h",          path = "~",              desc = "Home"         },
    { key = "d",          path = "~/Downloads",    desc = "Downloads"    },
    { key = "D",          path = "~/Documents",    desc = "Documents"    },
    { key = "c",          path = "~/.config",      desc = "Config files" },
    { key = "p",          path = "~/projects/",    desc = "projects"     },
    { key = "s",          path = "/mnt/synology/", desc = "synology"     },
    { key = "o",          path = "~/Documents/obsidian/main-vault/", desc = "obsidian vault"},
    { key = { "l", "c" }, path = "~/.local/config",desc = "Local config" },
    { key = { "l", "s" }, path = "~/.local/share", desc = "Local share"  },
    { key = { "l", "b" }, path = "~/.local/bin",   desc = "Local bin"    },
    { key = { "l", "t" }, path = "~/.local/state", desc = "Local state"  },
    { key = { "l", "c" }, path = "~/.local/share/chezmoi/", desc = "chezmoi (dotfiles manager)"},
    -- key and path attributes are required, desc is optional
  },
  desc_strategy = "path", -- If desc isn't present, use "path" or "filename", default is "path"
  ephemeral = true, -- Enable ephemeral hops, default is true
  tabs = true, -- Enable tab hops, default is true
  notify = false, -- Notify after hopping, default is false
  fuzzy_cmd = "fzf", -- Fuzzy searching command, default is "fzf"
})
