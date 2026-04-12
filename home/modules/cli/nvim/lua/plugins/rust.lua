-- NixOSではrust-analyzerをNix管理（neovim.extraPackagesで提供）
-- mason = false はnix-mason.luaで設定済み
return {
  {
    "mrcjkb/rustaceanvim",
    opts = function(_, opts)
      opts.server = opts.server or {}
      opts.server.cmd = { "rust-analyzer" }
    end,
  },
}
