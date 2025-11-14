return {
  {
    lazy = false,
    "Mofiqul/dracula.nvim",
    opts = {
      overrides = {
        CursorLine = { bg = "#303341" },
      },
    },
  },

  -- Configure LazyVim to load dracula
  {
    "LazyVim/LazyVim",
    opts = {
      colorscheme = "dracula-soft",
      cursorline = false,
    },
  },
}
