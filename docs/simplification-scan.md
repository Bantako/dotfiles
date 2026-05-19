# dotfiles シンプル化スキャン

Mac 側で `nixos/` `home/` を全 .nix ファイル横断してシンプル化観点で分析した結果。
2 つの並列 agent (system 側 / desktop+cli 側) でフルスキャンしたうえで重複を取り除いた。
家のマシン (ser7) で取り込み・実装する。

---

## 全体所感

設定はかなり熟れてる。「中身が悪い」モジュールはほぼない。
問題は **構造の重み**：

1. **1 サービス 1 ファイル × 多数** → ファイル間ジャンプが多い
2. **設定の inline 記述** （vimiv ini / ghostty CSS）→ 巨大な heredoc が module を膨らませる
3. **マルチホスト前提の scaffold** が単一ホストに残ってる
4. **拾い箱モジュール** （`apps.nix`）が便利すぎて成長中
5. **死コメント / 死コード** が少しずつ堆積（個別は小さいが scan tax）

逆に、yazi.nix / git.nix / direnv.nix / nas/paperless.nix は手本になる構造。
**「yazi.nix パターン」（外部設定ファイル + 薄い Nix）を他に伝播させるのが伸びしろ**。

---

## P0: 即やる（10 分以内、ノーリスク）

### 死コード / 死コメント削除

| 場所 | 内容 | 削除理由 |
|---|---|---|
| `nixos/modules/system/networking.nix:7-16` | proxy / mtr / gnupg のコメントアウト 5 行 | NixOS install template 残骸 |
| `nixos/modules/desktop/desktop.nix:32-33` | `# media-session.enable = true;` | pipewire デフォルトと矛盾 |
| `nixos/hosts/ser7/hardware.nix:27-28` | `# services.xserver.libinput.enable` | 死コメント |
| `nixos/modules/system/users.nix:8-9` | 空の `packages = with pkgs; [ ];` | 空ブロック |
| `nixos/hosts/ser7/default.nix:36, 43-49` | NixOS boilerplate 生成コメント "List packages installed..." 等 | template 残骸 |
| `home/modules/cli/zsh→shell/zsh.nix:44` | `# "INTERACTIVE_COMMENTS"` | コメントアウト setopt |
| `home/modules/desktop/ghostty.nix:53` | `# background-opacity = 0.95;` | コメントアウト option |
| `home/modules/desktop/niri.nix:38-47, 66-71` | 10+ 行のコメントアウト keybind + 「バインド被りのため休止」墓碑 | 死コード |
| `home/modules/desktop/niri.nix:126` | `# config = with inputs.niri.lib.kdl;` | 孤児コメント |

### 真の重複（同じ設定が 2 か所）

- ~~**`programs.kdeconnect.enable = true`** が `nixos/modules/system/users.nix:20` と `home/home.nix:48-52` の両方~~ — **誤検出**。system 側は firewall ポート 1714-1764 を開ける役、HM 側は daemon を立てる役。**両方必要**。過去に片方外して動かなくなった実体験あり。動かす（コメントで役割明示してもよい）
- **`programs.firefox.enable = true`** が `nixos/modules/system/users.nix:19` にある。ファイル名と中身が不一致。**削除**（メインブラウザは Vivaldi、plan の "firefox 撤去" 項目も未着手のままだった）
- **Bibata cursor 二重指定** `home/modules/desktop/gtk.nix:18-22`（`gtk.cursorTheme`）と `:32-37`（`home.pointerCursor`）。`pointerCursor.gtk.enable = true` が GTK 側を駆動するので **`cursorTheme` 側を削除**
- **zsh history 設定の二重宣言** `home/modules/shell/zsh.nix:36-55` の `setOptions` に `HIST_IGNORE_ALL_DUPS`/`HIST_IGNORE_SPACE`、`:61-72` の `history.ignoreDups`/`ignoreSpace` が同じ意図を 2 方言で宣言。**`history.*` 側に統一して `setOptions` から削除**

### コメント密度の調整

- `home/modules/shell/zsh.nix:53-55, 60-71, 75-80` — `size = 100000` の上に「メモリ上の履歴件数」のような literal restate コメント。**削除**（識別子が説明してる）
- `home/modules/desktop/niri.nix:62-71` — noctalia の `screenOff: 600s / lock: 660s / suspend: 1800s` を niri 側にも書いてある。**サイレントドリフトの種**。削除して noctalia 側を canonical に
- `home/modules/desktop/noctalia.nix:1-10` — 10 行の「他モジュールの説明」preamble。コミットメッセージ向き。**削除 or `docs/` に移す**

---

## P1: 中規模リファクタ（30 分〜1 時間、独立）

### A. `vimiv.nix` を yazi パターンに揃える（最大 ROI）

`home/modules/cli/vimiv.nix:4-167` が **170 行の INI 文字列を Nix 文字列に inline している**。
`yazi.nix:10-15` は同種の設定を `./yazi/*` から `.source = ./yazi` で外出ししてて綺麗。

**移行**:
```
home/modules/cli/vimiv/
├── vimiv.conf
└── styles/dracula
```
+ `vimiv.nix` を `~10 行`に圧縮（`xdg.configFile."vimiv/...".source = ./vimiv/...`）。

副次効果: `vimiv.nix` 内の Dracula パレットハードコード（73-167）が conf ファイルへ。
stylix 導入時にここを最終的に削るので、**stylix までの中間形**としても妥当。

### B. `ghostty.nix:8-43` 35 行の GTK CSS を外出し

同じパターン。`./ghostty/tab-style.css` + `programs.ghostty.config = readFile ./ghostty/tab-style.css`。

### C. `apps.nix` 拾い箱を解体

`home/modules/desktop/apps.nix:9-46` が
**openldap overlay + 2 programs + 17 unrelated パッケージ**（alacritty / fuzzel / nemo / discord / slack / spotify / minecraft / calibre / obsidian / mangohud / protontricks / featherpad …）。
今は無害でも次の追加で必ず迷う。

**案 1**（軸別分割）:
- `desktop/communication.nix` — discord / slack
- `desktop/media.nix` — spotify / calibre / featherpad
- `desktop/gaming.nix` — minecraft / mangohud / protontricks（→ 既存 gaming 系と合流）
- `desktop/file-manager.nix` — nemo
- `desktop/launchers.nix` — fuzzel / alacritty（fuzzel は noctalia から剥がす議論にも繋がる）

**案 2**（最小）: `tools.nix` の `home.packages` に GUI アプリも統合してしまう（"そもそも分ける意味あった？"）。

→ **案 2 推奨**。tools.nix を「インストール対象 1 元化」にして、設定が必要なものだけ別ファイルにする方針が yazi/git/direnv パターンと整合。

### D. `apps.nix` の openldap overlay 是非確認

```
"nixpkgs-unstable の一時的な問題"
```
コメントどおりまだ必要か。**`nix build nixpkgs-unstable#openldap` を手で叩いて壊れてなければ overlay 削除**。これだけで `apps.nix` が大幅に軽くなる。

### E. `home/modules/cli/sheldon.nix` 解体検討

6 行のファイル：
```nix
xdg.configFile."sheldon/plugins.toml".source = ./sheldon/plugins.toml;
```
だけしてる。**`zsh.nix` に統合 or `programs.zsh.plugins` に書き直す**。
ただし sheldon 経由でのみ実現できる順序制御（carapace を fzf-tab より前に init）があるので **toml は残す**、Nix モジュールだけ畳む。

### F. `zsh.nix` の `initContent` 50 行を外出し

`home/modules/shell/zsh.nix:82-138` が OSC 133 prompt mark / `y()` / sops loaders / wl-copy alias / 計 50 行超の shell スクリプト inline。
**`./zshrc.sh` に切り出して `programs.zsh.initContent = builtins.readFile ./zshrc.sh`**。
副次効果: shellcheck / treesitter が効く。

### G. sops env-export ループ化

`home/modules/shell/zsh.nix:127-138` で 4 つの API key を near-identical な手動 export ブロック。

```nix
sopsEnv = {
  OPENAI_API_KEY = config.sops.secrets.openai_api_key.path;
  DEEPSEEK_API_KEY = config.sops.secrets.deepseek_api_key.path;
  # ...
};
initContent = lib.concatStringsSep "\n" (lib.mapAttrsToList (k: p:
  ''[ -r ${p} ] && export ${k}="$(cat ${p})"''
) sopsEnv);
```

新しい API key を 1 行追加で済むようになる。

### H. claudeAliases の `_module.args` 経由を見直す

`home/modules/ai/claude-code.nix:15-18` が
```nix
_module.args.claudeAliases = { ccode = "claude"; cld = "claude"; };
```
を export し、`home/modules/shell/zsh.nix:31` で受け取る。
**alias 2 個のためだけの module 越境**。
zsh.nix にインライン化 or claude-code.nix 内に alias を書く方が単純。
ただし「AI 関連は AI フォルダ」原則は通るので、**強い推奨ではない**。

---

## P2: 構造変更（半日コミット、影響大）

### α. `nixos/hosts/ser7/` を畳む

メモリ `project_single_host_policy.md`: 「ser7 1 台運用、マルチホスト前提の予防的抽象化はしない」と一致。

```
nixos/
├── configuration.nix      # 旧 hosts/ser7/default.nix
├── hardware.nix           # 旧 hosts/ser7/hardware.nix
├── hardware-configuration.nix
├── secrets/secrets.yaml   # 旧 hosts/ser7/secrets/
└── modules/...
```

`flake.nix` の `nixosConfigurations.nixos.modules = [ ./nixos/configuration.nix ]` も短くなる。

**注意**: `.sops.yaml` の path 規則を要更新。secrets パスの変更は再暗号化が必要。家で要動作確認。

### β. system モジュールの粒度判断

現状 `nixos/modules/system/` に 14 ファイル（fwupd / oom / zram / fail2ban / flatpak / bluetooth / monitoring / ssh / nix-ld / ...）。
それぞれ 4-15 行。

**統合派の論**: 50 行が 14 ファイルに散ってるのは scan tax。
**1 ファイル 1 サービス派の論**: grep / git blame / Nix モジュール ID として明示的で安全。

→ **このユーザーの嗜好 (navigate-first, terminal 内効率) には 1 サービス 1 ファイル**が合う気がする。
**統合は却下**、ただし `commands.nix` / `portal.nix` のように **本当に 5 行未満** のものは parent (`desktop.nix`) に inline する。

具体的に inline 候補:
- `nixos/modules/desktop/commands.nix` (7 行、nix-index-database を import するだけ) → `desktop.nix` に
- `nixos/modules/desktop/portal.nix` (9 行) → `desktop.nix` に

### γ. ~~`home/modules/ai/` の整理~~ — **保留**

当初 aider / mcp / rtk を `ai.nix` に統合する案を出したが、**LLM スタックは研究途中**で構成が流動的（memory `project-browser-llm-experimental-state` 参照）。シンプル化のために統合すると試行錯誤の障害になるため、**当面 5 ファイル維持**。

研究フェーズが落ち着いて構成が安定したら再検討する。

---

## やらないリスト

- **Dracula パレットの抽出 (`lib/colors.nix` 化)** — vimiv / noctalia / ghostty / gtk に分散。**stylix 導入時に全消去される予定**なので、いま手で抽出すると二重作業。stylix 着手と同じタイミングで処理する
- **`with pkgs;` 排除** — 70 行のパッケージリストで `with pkgs;` は Nix idiomatic。可読性損なってない
- **`hosts/ser7/` を保持しながらの小規模リネーム** — 中途半端。やるなら α でフラット化、やらないなら現状維持
- **sheldon プラグインの Nix 化** — sheldon の順序制御 (carapace-init を fzf-tab 前に) が依存してる。書き換えで壊すリスクがある割に得が薄い
- **`apps.nix` の Vivaldi / Zen 統廃合** — Zen は試し中、Vivaldi はプライマリ（memory `project-browser-llm-experimental-state` 参照）。「片方に寄せる」議論は本人の試行が落ち着いてから
- **`ai/` ディレクトリ統合** — γ で書いたが LLM スタックが研究途中。保留

---

## 推奨着手順

1. **P0 一括コミット** — 死コード / 死コメント / 真の重複 4 件 を 1 PR で。1 時間以内
2. **P1-A vimiv 外出し** — yazi パターンの伝播。単独 PR
3. **P1-C apps.nix 案 2 (tools.nix 統合)** — junk drawer 解体。単独 PR
4. **P1-D openldap overlay 確認 → 削除** — apps.nix リファクタの前後どちらでも
5. **P1-F zshrc 外出し** + **P1-G sops env-export ループ化** — zsh.nix まとめて 1 PR
6. **P2-β commands.nix / portal.nix を desktop.nix に inline** — 5 分仕事
7. **P2-α `hosts/ser7/` フラット化** — 別日に集中。sops の path 更新 + 再暗号化検証が要る
8. ~~P2-γ ai/ 整理~~ — LLM 研究途中のため保留

P0 + P1-A + P1-C + P1-F まで来れば、設定全体の見通しが体感で 1 段良くなる。
P2-α は気力のある週末向け。

---

## improvement-plan.md への追記候補

```markdown
| **シンプル化** | 死コード掃除 + vimiv/ghostty 外出し + apps.nix 解体 + hosts/ser7/ フラット化 |
```

未着手側「H Mason」「K xremap」「stylix」と並列の項目として。
**stylix 着手時に Dracula パレット重複 5 箇所が一掃される**と明示しておくと忘れない。
