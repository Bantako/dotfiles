local en = "keyboard-us"
local ja = "mozc"

return {
  "pysan3/fcitx5.nvim",
  event = "ModeChanged",
  opts = {
    imname = {
      norm = en,
      ins = en,
      cmd = en,
    },
    remember_prior = true,
  },
}
