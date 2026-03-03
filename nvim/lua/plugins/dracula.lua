return {
  {
    "Mofiqul/dracula.nvim",
    lazy = false,
    priority = 1000,
    opts = {
      colors = {
        bg = "#282A36",
        selection = "#44475A",
      },
      overrides = {
        CursorLine = { bg = "#3E4452" },
      },
    },
  },
  {
    "LazyVim/LazyVim",
    opts = {
      colorscheme = "dracula-soft",
    },
  },
}
