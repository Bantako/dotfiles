-- Mason 完全停止。LSP / formatter は全て Nix (dev.nix) で管理する。
return {
  { "mason-org/mason.nvim",                       enabled = false },
  { "mason-org/mason-lspconfig.nvim",             enabled = false },
  { "WhoIsSethDaniel/mason-tool-installer.nvim",  enabled = false },

  -- LazyVim の各 lang extra が opts.servers に mason=true を入れるのを一括上書き
  {
    "neovim/nvim-lspconfig",
    opts = function(_, opts)
      opts.servers = opts.servers or {}
      for _, server in pairs(opts.servers) do
        if type(server) == "table" then
          server.mason = false
        end
      end
      return opts
    end,
  },
}
