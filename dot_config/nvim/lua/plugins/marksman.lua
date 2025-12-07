return {
  "neovim/nvim-lspconfig",
  opts = {
    servers = {
      marksman = {
        -- Markdownでは起動させない
        filetypes = {},  -- もしくは { "markdown.mdx" } など、使いたいftだけ
      },
    },
  },
}
