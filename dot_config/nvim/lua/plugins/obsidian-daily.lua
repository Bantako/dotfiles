-- lua/plugins/obsidian-daily-navigate.lua
return {
  {
    "obsidian-nvim/obsidian.nvim",
    keys = function(_, keys)
      -- ファイル名やFrontmatterから日付を取り出し、±offset日を開く
      local function goto_daily_by_current(offset)
        -- 1) ファイル名から YYYY-MM-DD を抽出（例: 2025-11-12）
        local fname = vim.fn.expand("%:t:r") -- 拡張子除去
        local y, m, d = fname:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)$")
        if not (y and m and d) then
          -- 2) ファイル名に無い場合、Frontmatterの date: YYYY-MM-DD を探す（任意）
          --    必要なければこのブロックは削除しても良い
          local lines = vim.api.nvim_buf_get_lines(0, 0, math.min(200, vim.api.nvim_buf_line_count(0)), false)
          local in_yaml = false
          for _, line in ipairs(lines) do
            if line:match("^%-%-%-$") then
              in_yaml = not in_yaml
            elseif in_yaml then
              local yy, mm, dd = line:match("^date:%s*(%d%d%d%d)%-(%d%d)%-(%d%d)")
              if yy and mm and dd then
                y, m, d = yy, mm, dd
                break
              end
            end
          end
        end
        if not (y and m and d) then
          vim.notify("[obsidian.nvim] このノートから基準日付を取得できませんでした（ファイル名/Frontmatterを確認）", vim.log.levels.WARN)
          return
        end

        -- 日付→time、±offset日、再フォーマット
        local base = os.time({ year = tonumber(y), month = tonumber(m), day = tonumber(d), hour = 12 })
        local target = base + (offset * 24 * 60 * 60)
        local title = os.date("%Y-%m-%d", target)

        -- クライアント経由で該当日付のデイリーノートを開く
        local client = require("obsidian").get_client()
        -- フォーク/オリジナルとも「指定日付のデイリーNoteを返す」APIがある想定
        -- 無い場合は today [OFFSET] のサブコマンドを使うフォールバックへ
        local ok, note = pcall(function()
          -- community forkは client:daily(date) / client:_daily(date) 等の内部APIがあり（将来変更の可能性）
          -- 互換性優先で "today [OFFSET]" サブコマンドにフォールバック
          return nil
        end)
        if ok and note then
          client:open_note(note)
          return
        end

        -- フォールバック: 今“システム日付”基準で today [OFFSET] を呼ぶのではなく、
        -- カレント日付→システム今日との差分 “delta” を足し合わせる
        -- delta = (target - today) / 86400
        local today_mid = os.time({ year = tonumber(os.date("%Y")), month = tonumber(os.date("%m")), day = tonumber(os.date("%d")), hour = 12 })
        local delta = math.floor((target - today_mid) / (24 * 60 * 60))

        -- コミュニティフォーク: :Obsidian today <delta>
        -- epwalsh版: :ObsidianToday <delta>
        if pcall(vim.cmd, string.format("Obsidian today %d", delta)) then
          return
        else
          pcall(vim.cmd, string.format("ObsidianToday %d", delta))
        end
      end

      -- 前日へ（現在のノートを基準）
      table.insert(keys, { "<leader>o[", function() goto_daily_by_current(-1) end, desc = "Daily: Previous (by current note date)" })
      -- 翌日へ（現在のノートを基準）
      table.insert(keys, { "<leader>o]", function() goto_daily_by_current(1) end,  desc = "Daily: Next (by current note date)"  })
        -- その場で「昨日/明日」を直接確認したいショートカットも用意しておくと便利
        -- { "<leader>oy", "<cmd>Obsidian today -1<CR>", desc = "Open Yesterday (system today -1)" },
        -- { "<leader>on", "<cmd>Obsidian today 1<CR>",  desc = "Open Tomorrow (system today +1)" },
      return keys
    end,
  },
}
