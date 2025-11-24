-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

vim.g.autoformat = false

local code_bg = "#3C3D46"

-- 従来syntax用
vim.api.nvim_set_hl(0, "markdownCode",      { bg = code_bg })
vim.api.nvim_set_hl(0, "markdownCodeBlock", { bg = code_bg })
vim.api.nvim_set_hl(0, "RenderMarkdownCode", { bg = code_bg })

-- Tree-sitter markdown用
vim.api.nvim_set_hl(0, "@markup.raw.block.markdown",    { bg = code_bg })
vim.api.nvim_set_hl(0, "@markup.raw.markdown_inline",   { bg = code_bg })
