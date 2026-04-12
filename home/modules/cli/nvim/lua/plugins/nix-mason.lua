-- NixOSではLSPツール群をNix管理するためmasonの自動インストールを無効化
-- LazyVimはlspconfig opts.servers[server].mason = false でmasonをスキップする
return {
  {
    "neovim/nvim-lspconfig",
    opts = {
      servers = {
        nil_ls = { mason = false },
        rust_analyzer = { mason = false },
      },
    },
  },
}
