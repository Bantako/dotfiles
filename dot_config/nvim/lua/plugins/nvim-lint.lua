return {
  "mfussenegger/nvim-lint",
  opts = {
    linters_py_ft = {
      markdown = { "markdownlint-cli2" },
    },
    linters = {
      ["markdownlint-cli2"] = {
        args = { "--config", vim.fn.expand("~/.config/nvim/.markdownlint.yaml"), "--" },
      },
    },
  },
}
