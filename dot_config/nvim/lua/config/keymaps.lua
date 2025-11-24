-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
--
local set = vim.keymap.set

local map = vim.api.nvim_set_keymap
local opts = { noremap = true, silent = true }

vim.keymap.set("n", "gf",
  function()
    if require("obsidian").util.cursor_link() then
      return "<cmd>Obsidian follow_link<cr>"
    else
      return "gf"
    end
  end, {
    expr = true,
    desc = "[g]o to [f]ile under cursor (Obsidian)",
})
