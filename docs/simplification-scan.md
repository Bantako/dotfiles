# dotfiles シンプル化スキャン

Mac 側で `nixos/` `home/` を全 .nix ファイル横断してシンプル化観点で分析した結果。
2 つの並列 agent (system 側 / desktop+cli 側) でフルスキャンしたうえで重複を取り除いた。

**2026-05-19 実施済み**: P0 全件 + P1-A/B/D/E/F/G 完了。P1-C/H・P2 は後述の判断で現状維持。

---

## 全体所感

設定はかなり熟れてる。「中身が悪い」モジュールはほぼない。
問題は **構造の重み**：

1. ~~**設定の inline 記述** （vimiv ini / ghostty CSS）→ 巨大な heredoc が module を膨らませる~~ → **解消済み**
2. ~~**拾い箱モジュール** （`apps.nix`）が便利すぎて成長中~~ → **openldap overlay 削除済み、CLI/GUI 分類で落ち着いた**
3. ~~**死コメント / 死コード** が少しずつ堆積~~ → **解消済み**
4. **マルチホスト前提の scaffold** が単一ホストに残ってる → P2-α 参照（現状維持）

---

## P0: ✅ 完了

### 死コード / 死コメント削除（完了）

- `networking.nix` proxy/mtr/gnupg template コメント
- `desktop.nix` media-session コメントアウト
- `hardware.nix` libinput 死コメント
- `users.nix` 空の packages ブロック
- `default.nix` NixOS boilerplate コメント群
- `zsh.nix` INTERACTIVE_COMMENTS コメントアウト
- `ghostty.nix` background-opacity コメントアウト
- `niri.nix` 孤児コメント（config = with inputs.niri.lib.kdl）
- `niri.nix:38-47, 66-71` 休止中 keybind ブロック — **現状維持**（ユーザー判断）

### 真の重複（完了）

- `users.nix` firefox.enable 削除（Vivaldi がプライマリ）
- `gtk.nix` Bibata cursor 二重指定解消（cursorTheme 側削除）
- ~~kdeconnect 重複~~ — 誤検出。system 側 = firewall、HM 側 = daemon で両方必要

> **注**: zsh history の二重宣言（setOptions vs history.*）は setOptions 側のコメントを削除することで
> 実質的に整理済み。history.* が canonical。

### コメント密度の調整（完了）

- `zsh.nix` history ブロックの literal restate コメント削除
- `noctalia.nix` 冒頭 preamble 削除

---

## P1: 中規模リファクタ

| 項目 | 状態 | 内容 |
|---|---|---|
| A vimiv 外出し | ✅ | `./vimiv/vimiv.conf` + `./vimiv/styles/dracula`、vimiv.nix を5行に圧縮 |
| B ghostty CSS 外出し | ✅ | `./ghostty/tab-style.css` に切り出し |
| C apps.nix 解体 | **現状維持** | openldap overlay 削除後、GUI 専用ファイルとして十分。tools.nix 統合より CLI/GUI の2ファイル分離が明確 |
| D openldap overlay 削除 | ✅ | nixpkgs-unstable 側で解消済みを確認 |
| E sheldon.nix 統合 | ✅ | zsh.nix に統合、sheldon.nix 削除 |
| F zshrc.sh 外出し | ✅ | `./zshrc.sh` に切り出し（shellcheck/treesitter 対応） |
| G sops ループ化 | ✅ | `sopsEnv` attrset + `mapAttrsToList` で生成、APIキー追加が1行 |
| H claudeAliases 見直し | **現状維持** | alias 2個のためだけの module 越境だが「AI関連はAIフォルダ」原則が通るため |

---

## P2: 現状維持

### α. `nixos/hosts/ser7/` フラット化

sops 再暗号化と path 更新が必要な割に得られるのは `hosts/ser7/` ディレクトリが消えるだけ。
単一ホスト運用で現状壊れていないため **保留**。気力のある週末向け。

実施するなら:
```
nixos/
├── configuration.nix      # 旧 hosts/ser7/default.nix
├── hardware.nix
├── hardware-configuration.nix
├── secrets/secrets.yaml   # 旧 hosts/ser7/secrets/
└── modules/...
```
`.sops.yaml` のパス規則を更新して再暗号化が必要。

### β. system モジュール粒度

`commands.nix`（7行）/ `portal.nix`（9行）の desktop.nix inline 案 → **現状維持**。
navigate-first の嗜好に 1 ファイル 1 サービスの方が合う。

### γ. `home/modules/ai/` 整理 — **保留**

LLM スタックが研究途中で構成が流動的。安定したら再検討。

---

## やらないリスト

- **Dracula パレットの抽出 (`lib/colors.nix` 化)** — stylix 導入時に全消去される予定。二重作業になるため保留
- **`with pkgs;` 排除** — 70 行のパッケージリストでは Nix idiomatic。可読性を損なっていない
- **`hosts/ser7/` 保持しながらの小規模リネーム** — 中途半端。やるなら α でフラット化、やらないなら現状維持
- **sheldon プラグインの Nix 化** — sheldon の順序制御（carapace-init を fzf-tab 前に）が依存してる。リスクに対して得が薄い
- **`apps.nix` の Vivaldi / Zen 統廃合** — Zen は試し中、Vivaldi はプライマリ。ブラウザ試行が落ち着いてから

---

## improvement-plan.md への追記候補

```markdown
| **シンプル化** | 死コード掃除 + vimiv/ghostty 外出し + apps.nix overlay 削除 + zshrc 外出し（2026-05-19 完了） |
```

**stylix 着手時に Dracula パレット重複（vimiv/noctalia/ghostty/gtk に分散）が一掃される**ことを明示しておくと忘れない。
