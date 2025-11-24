return {
  {
    "obsidian-nvim/obsidian.nvim",
    version = "*", -- recommended, use latest release instead of latest commit
    lazy = true,
    enabled = true,
    ft = "markdown",
    -- Replace the above line with this if you only want to load obsidian.nvim for markdown files in your vault:
    -- event = {
    --   -- If you want to use the home shortcut '~' here you need to call 'vim.fn.expand'.
    --   -- E.g. "BufReadPre " .. vim.fn.expand "~" .. "/my-vault/*.md"
    --   -- refer to `:h file-pattern` for more examples
    --   "BufReadPre path/to/my-vault/*.md",
    --   "BufNewFile path/to/my-vault/*.md",
    -- },
    dependencies = {
      -- Required.
      "nvim-lua/plenary.nvim",

      -- see below for full list of optional dependencies 👇
      "obsidian-nvim/obsidian-markmap.nvim",
    },
    opts = {
      workspaces = {
        {
          name = "personal",
          path = "~/Documents/obsidian/main-vault/"
        },
      },
      note_id_func = function(title)
        -- Create note IDs in the format 'YYYYMMDDHHMMSS'.
        if not title or title == "" then
          return tostring(os.time())
        end
        -- 1. 前後の空白を削除
        local sanitized = title:gsub("^%s*(.-)%s*$", "%1")

        -- 2. ファイル名に使えない文字を削除または置換
        -- WindowsやUnixで問題になる記号: / \ : * ? " < > | 
        sanitized = sanitized:gsub("[/\\:*?\"<>|]", "_")

        -- 3. 改行やタブを削除
        sanitized = sanitized:gsub("[%c]", "")
        return sanitized
      end,
      -- see below for full list of options 👇
      notes_subdir = "02-Fleeting",
      new_notes_location = "02-Fleeting",
      daily_notes = {
        folder = "01-Daily",
        date_format = "%Y/%Y-%m/%Y-%m-%d",
      },
      -- front matterに作成日と更新日を追加
      note_frontmatter_func = function(note)
        local now = os.date("%Y-%m-%d")

        -- 既存メタデータをベースにする
        local out = vim.tbl_extend("force", {
          id      = note.id,
          aliases = note.aliases,
          tags    = note.tags,
        }, note.metadata or {})

        -- created は既にあれば維持、無ければ今回付与
        if not out.created then
          out.created = now
        end

        -- updated は毎回現在時刻で上書き
        out.updated = now

        return out
      end,

      legacy_commands = false,
      -- Optional, completion of wiki links, local markdown links, and tags using nvim-cmp.
      completion = {
        -- Enables completion using nvim_cmp
        nvim_cmp = false,
        -- Enables completion using blink.cmp
        blink = true,
        -- Trigger completion at 2 chars.
        min_chars = 2,
      },
      footer = {
        enabled = false,
      },
    },
    picker = {
      -- Set your preferred picker. Can be one of 'telescope.nvim', 'fzf-lua', 'mini.pick' or 'snacks.pick'.
      name = "snacks.pick",
      -- Optional, configure key mappings for the picker. These are the defaults.
      -- Not all pickers support all mappings.
      note_mappings = {
        -- Create a new note from your query.
        new = "<C-x>",
        -- Insert a link to the selected note.
        insert_link = "<C-l>",
      },
      tag_mappings = {
        -- Add tag(s) to current note.
        tag_note = "<C-x>",
        -- Insert a tag at the current location.
        insert_tag = "<C-l>",
      },
    },
    keys = {
      { "<leader>ch", "<cmd>lua require 'obsidian'.util.toggle_checkbox()" },
      { "<leader>on", "<cmd>Obsidian new<cr>", desc = "New Obsidian note" },
      { "<leader>oo", "<cmd>Obsidian search<cr>", desc = "Search Obsidian notes" },
      { "<leader>os", "<cmd>Obsidian quick_switch<cr>", desc = "Quick Switch" },
      { "<leader>ob", "<cmd>Obsidian backlinks<cr>", desc = "Show backlinks" },
      { "<leader>ol", "<cmd>Obsidian links<cr>", desc = "Show Links" },
      { "<leader>ot", "<cmd>Obsidian today<cr>", desc = "Open Today Note" },
      { "<leader>oT", "<cmd>Obsidian tags<cr>", desc = "Open tags menu" },
      { "<leader>of", "<cmd>Obsidian follow_link<cr>", desc = "Open follow link" },
      { "<leader>op", "<cmd>Obsidian paste_img<cr>", desc = "Paste image from clipboard" },
      { "<leader>oc", "<cmd>Obsidian toc<cr>", desc = "Show Table of Contents" },
      -- Visualモード専用。'<,'> のレンジをそのままコマンドへ渡す
      { "<leader>oe", ":'<,'>Obsidian extract_note<CR>", mode = "x", desc = "Extract selection to new note" },
    },
  },
  {
    "gaoDean/autolist.nvim",
    lazy = true,
    ft = "markdown",
    config = function()
      require("autolist").setup()

      vim.keymap.set("i", "<tab>", "<cmd>AutolistTab<cr>")
      vim.keymap.set("i", "<s-tab>", "<cmd>AutolistShiftTab<cr>")
      -- vim.keymap.set("i", "<c-t>", "<c-t><cmd>AutolistRecalculate<cr>") -- an example of using <c-t> to indent
      vim.keymap.set("i", "<CR>", "<CR><cmd>AutolistNewBullet<cr>")
      vim.keymap.set("n", "o", "o<cmd>AutolistNewBullet<cr>")
      vim.keymap.set("n", "O", "O<cmd>AutolistNewBulletBefore<cr>")
      vim.keymap.set("n", "<CR>", "<cmd>AutolistToggleCheckbox<cr><CR>")
      vim.keymap.set("n", "<C-r>", "<cmd>AutolistRecalculate<cr>")

      -- cycle list types with dot-repeat
      vim.keymap.set("n", "<leader>cn", require("autolist").cycle_next_dr, { expr = true })
      vim.keymap.set("n", "<leader>cp", require("autolist").cycle_prev_dr, { expr = true })

      -- if you don't want dot-repeat
      -- vim.keymap.set("n", "<leader>cn", "<cmd>AutolistCycleNext<cr>")
      -- vim.keymap.set("n", "<leader>cp", "<cmd>AutolistCycleNext<cr>")

      -- functions to recalculate list on edit
      vim.keymap.set("n", ">>", ">><cmd>AutolistRecalculate<cr>")
      vim.keymap.set("n", "<<", "<<<cmd>AutolistRecalculate<cr>")
      vim.keymap.set("n", "dd", "dd<cmd>AutolistRecalculate<cr>")
      vim.keymap.set("v", "d", "d<cmd>AutolistRecalculate<cr>")
    end,
  },
  -- {
  --   "MeanderingProgrammer/render-markdown.nvim",
  --   lazy = true,
  --   ft = "markdown",
  --   -- dependencies = { 'nvim-treesitter/nvim-treesitter', 'echasnovski/mini.nvim' }, -- if you use the mini.nvim suite
  --   dependencies = { "nvim-treesitter/nvim-treesitter", "echasnovski/mini.icons" }, -- if you use standalone mini plugins
  --   -- dependencies = { 'nvim-treesitter/nvim-treesitter', 'nvim-tree/nvim-web-devicons' }, -- if you prefer nvim-web-devicons
  --   ---@module 'render-markdown'
  --   ---@type render.md.UserConfig
  --   opts = {},
  -- },
}
