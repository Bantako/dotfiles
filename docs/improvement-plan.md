# NixOS dotfiles 改善プラン

家のマシン (`ser7`, NixOS + Niri + Home Manager) 向けの導入候補リスト。
優先度別・カテゴリ別に整理。各項目には「追加場所」「設定例」「検証コマンド」を併記。

---

## 進捗サマリー

### 完了

| 項目 | 内容 |
|---|---|
| **B** | starship 撤去・pure 単独化 |
| **D** | parsec-bin / remmina 削除 |
| **E** | evince / totem 削除 |
| **F** | 死コード sheldon プラグイン2本削除 |
| **G** | atool / htop 削除 + fd / sd / xh / navi / hyperfine 追加 |
| **I** | bottles / easyrpg-player 削除 + gamemode / gamescope / corectrl / mangohud / protonup-qt / protontricks 追加 |
| **J** | bitwarden-cli 削除 |
| **L** | pandoc 追加 |
| **N** | exiftool / gallery-dl 追加 |
| **A** | wezterm 撤去・Ghostty 主軸化・terminal ラッパー移管 |
| **P0** | nix-ld / zramSwap / systemd-oomd / fwupd 追加 |
| **CLI+** | fastfetch / dust / procs / hexyl / dog / vhs / frogmouth / nix-tree / nom / nvd / comma 追加 |

### 未着手（優先度順）

| 項目 | 内容 | 規模 |
|---|---|---|
| **openssh** | Tailscale 経由 SSH | 小 |
| **M** | aider 追加 | 小 |
| **H** | Mason 完全停止 + Nix LSP 完全管理 | 大（集中1〜2h） |
| **GPG agent** | コミット署名・pinentry | 小 |
| **borgbackup** | NAS へのスナップショットバックアップ | 中（sops 鍵追加が必要） |
| **P1 Wayland** | satty / hyprpicker / gammastep / udiskie 等 | 小粒 |
| **K** | xremap キーリマップ設計 | 保留中 |
| **stylix** | base16 テーマ全アプリ統一 | 大 |

---

各 PR/コミット単位で 1 項目ずつ進めると安全 (`nh os switch --dry` で必ず確認)。

---

## P0: 基盤として欠けているもの（早めに）

### [ ] nix-ld — 非Nixバイナリを動かせるようにする

VSCode拡張、AppImage、`mise` でインストールする言語ランタイム等の prebuilt ELF が動くようになる。
NixOSデスクトップでほぼデファクト。

**追加場所**: `nixos/modules/system/` 新規ファイル `nix-ld.nix` を作り、`hosts/ser7/default.nix` でimport。

```nix
# nixos/modules/system/nix-ld.nix
{ pkgs, ... }:
{
  programs.nix-ld = {
    enable = true;
    libraries = with pkgs; [
      stdenv.cc.cc
      zlib openssl curl
      glib nss nspr
      libxkbcommon
    ];
  };
}
```

**検証**: `ldd $(which node)` などで warning が消える。VSCode の rust-analyzer 拡張等が動く。

---

### [ ] zramSwap — メモリ圧縮スワップ

物理swapを切っていても OOM 直前の挙動が安定する。RAM 1/2 を上限 zstd 圧縮で確保するのが定石。

**追加場所**: `nixos/modules/system/` に `zram.nix` を新規。

```nix
# nixos/modules/system/zram.nix
{ ... }:
{
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
  };
}
```

**検証**: `zramctl` で `/dev/zram0` が見える。`swapon --show` でも確認。

---

### [ ] systemd-oomd または earlyoom — OOMでフリーズしない

Chrome/Slack/AndroidStudio/Steam を併用しているとメモリ食い潰してマシンごと固まりがち。
systemd-oomd が最近の主流。

**追加場所**: `nixos/modules/system/oom.nix`

```nix
{ ... }:
{
  systemd.oomd = {
    enable = true;
    enableRootSlice = true;
    enableUserSlices = true;
  };
}
```

**検証**: `systemctl status systemd-oomd`、`oomctl` で監視中サービスが見える。

---

### [ ] fwupd — ファームウェア更新

SER7 の BIOS/SSD/USB-HUB 等のファーム更新が `fwupdmgr refresh && fwupdmgr update` でできるようになる。

**追加場所**: `nixos/modules/system/fwupd.nix`

```nix
{ ... }:
{
  services.fwupd.enable = true;
}
```

**検証**: `fwupdmgr get-devices` で対応デバイスが列挙される。

---

### [ ] services.openssh — リモート作業用

LAN 内別端末や Tailscale 経由で Mac/iPhone から作業できる。
ファイアウォールは `trustedInterfaces = ["tailscale0"]` 既存設定でカバー済み。

**追加場所**: `nixos/modules/system/networking.nix` に追記、または `ssh.nix` を新規。

```nix
{
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
    openFirewall = false;  # Tailscale経由のみ受ける
  };
  # 公開鍵は users.nix 側の users.users.morikawa.openssh.authorizedKeys.keys に
}
```

**検証**: Tailscale同一テナント内の端末から `ssh morikawa@<tailscale-ip>` で入れる。

---

### [ ] backup — borgbackup または restic

Syncthing は同期、バックアップではない（誤削除が他端末にも伝播）。
スナップショット型バックアップを `/mnt/ugreen` (NAS) に。

**追加場所**: `nixos/modules/system/backup.nix`

```nix
# 例: borgbackup
{ config, ... }:
{
  services.borgbackup.jobs.home = {
    paths = [ "/home/morikawa" ];
    exclude = [
      "/home/morikawa/.cache"
      "/home/morikawa/.local/share/Trash"
      "/home/morikawa/Downloads"
      "/home/morikawa/.dotfiles"  # gitで管理
    ];
    repo = "/mnt/ugreen/borg/ser7";
    encryption = {
      mode = "repokey-blake2";
      passCommand = "cat ${config.sops.secrets.borg_passphrase.path}";
    };
    compression = "auto,zstd";
    startAt = "daily";
    prune.keep = { daily = 7; weekly = 4; monthly = 6; };
  };
}
```

sops に `borg_passphrase` を追加する必要あり。
初回は手動で `borg init --encryption=repokey-blake2 /mnt/ugreen/borg/ser7`。

**検証**: `systemctl start borgbackup-job-home` 即時実行 → `borg list /mnt/ugreen/borg/ser7`

---

### [ ] GPG agent — コミット署名・SSH代替

`pinentry-gnome3` か `pinentry-curses` 推奨（Wayland対応注意）。

**追加場所**: `home/modules/cli/gpg.nix`

```nix
{ pkgs, ... }:
{
  programs.gpg.enable = true;
  services.gpg-agent = {
    enable = true;
    enableZshIntegration = true;
    pinentry.package = pkgs.pinentry-gnome3;
    defaultCacheTtl = 3600;
    maxCacheTtl = 28800;
    # SSHエージェントとしても使う場合
    # enableSshSupport = true;
  };
}
```

**検証**: `gpg --list-keys`、`gpg -s` でパスフレーズダイアログが出る。

---

## P1: Wayland/Niri 体験の底上げ

### [ ] スクショ加筆ツール (satty)

```nix
# home/modules/desktop/apps.nix の home.packages に追加
satty
```

niri.nix のスクショbindを変更:

```nix
# screenshot を撮ってから satty に渡す
"Ctrl+Shift+4".action.spawn = [
  "sh" "-c"
  "grim -g \"$(slurp)\" - | satty -f - --copy-command wl-copy"
];
```

`grim`, `slurp` も必要 (`grim slurp` を packages に追加)。

---

### [ ] hyprpicker — カラーピッカー

Niri でも動作。`wl-copy` でクリップボードに HEX が入る。

```nix
# home/modules/desktop/apps.nix
hyprpicker
```

niri bind:

```nix
"Mod+Shift+P".action.spawn = [ "sh" "-c" "hyprpicker -a -f hex" ];
```

---

### [ ] wf-recorder — 軽量画面録画

OBS は重いので短いキャプチャ用に。

```nix
home.packages = with pkgs; [ wf-recorder wl-screenrec ];
```

niri bindで `wf-recorder -g "$(slurp)" -f ~/Videos/cap-$(date +%s).mp4` をトグル起動するスクリプトを用意。

---

### [ ] rofimoji or wofi-emoji — 絵文字ピッカー

IME とは別レイヤーで絵文字が欲しい時に。

```nix
home.packages = [ pkgs.rofimoji ];
```

niri bind 例: `"Mod+period".action.spawn = [ "rofimoji" "--selector" "fuzzel" ];`

---

### [ ] gammastep — ブルーライト軽減

夜間色温度を下げる。Wayland対応版。

```nix
# home/modules/desktop/gammastep.nix
{ ... }:
{
  services.gammastep = {
    enable = true;
    provider = "manual";
    latitude = 35.6;
    longitude = 139.6;  # 東京
    temperature = {
      day = 6500;
      night = 3500;
    };
  };
}
```

---

### [ ] udiskie — USB自動マウント

```nix
{
  services.udiskie = {
    enable = true;
    automount = true;
    notify = true;
    tray = "auto";
  };
}
```

---

### [ ] xdg-desktop-portal-gtk 併用

現状 wlr portal のみ。Chromium / Electron のファイル選択ダイアログが文字化けしたり崩れたりするので gtk portal を併用すると堅い。

```nix
# nixos/modules/desktop/portal.nix を更新
{ pkgs, ... }:
{
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
    config.common.default = [ "wlr" "gtk" ];
  };
}
```

---

## P1: ゲーミング (Steam 有効済み)

### [ ] gamemode

Steam が自動で `gamemoderun %command%` できる枠を作る。

```nix
{
  programs.gamemode.enable = true;
}
```

Steam の起動オプションに `gamemoderun %command%` を入れる (これは GUI 操作)。

---

### [ ] gamescope

スケーリング・HDR・フレーム制限が効く Wayland コンポジタを Steam の中で動かす。

```nix
{
  programs.steam.gamescopeSession.enable = true;
  programs.gamescope = {
    enable = true;
    capSysNice = true;
  };
}
```

Steam起動オプション例: `gamescope -W 2560 -H 1440 -r 144 -- %command%`

---

### [ ] mangohud

FPS/温度/CPU使用率オーバーレイ。

```nix
home.packages = [ pkgs.mangohud ];
```

Steam 起動オプション: `mangohud %command%` (または環境変数 `MANGOHUD=1`)

---

### [ ] corectrl — AMD GPU 電力カーブGUI

AMD APU/dGPU の電力プロファイル切替。

```nix
{
  programs.corectrl = {
    enable = true;
    gpuOverclock.enable = true;
  };
  users.users.morikawa.extraGroups = [ "corectrl" ];  # users.nix側
}
```

---

## P1: CLI / 開発ツール

### [ ] nix-output-monitor (nom)

`nh` と連携してビルド進捗が見やすくなる。

```nix
# home/modules/cli/tools.nix の home.packages に
nix-output-monitor
nvd  # nix version diff: 切替前後のパッケージ差分
```

`nh` は自動で nom/nvd を検出して使う。

---

### [ ] comma (`,`) — 即席パッケージ実行

`nix run` 不要。`, cowsay hi` のように使える。
`nix-index-database` を既に入れてるので相性◎。

```nix
home.packages = [ pkgs.comma ];
```

---

### [ ] hyperfine / dust / procs / bandwhich

地味だが常用化しやすい現代的なCLI。

```nix
# home/modules/cli/tools.nix の home.packages に追加
hyperfine    # ベンチマーク (`hyperfine 'cmd1' 'cmd2'`)
dust         # du のモダン版 (ツリー型でサイズ可視化)
procs        # ps のモダン版 (色付き・ツリー表示)
bandwhich    # プロセス別ネットワーク使用量
gping        # ping をグラフで可視化
```

---

### [ ] mise — 言語ランタイム管理

Node/Go/Python/Ruby/JDK のバージョン管理を一元化。
`uv` (Python専用) を併用しつつ他言語は mise でカバー。

```nix
{
  programs.mise = {
    enable = true;
    enableZshIntegration = true;
  };
}
```

---

### [ ] git-absorb

`git commit --fixup` を自動でやってくれる。レビュー対応で連発したい時に便利。

```nix
home.packages = [ pkgs.git-absorb ];
```

---

## P2: テーマ統一 (大きめ・効果も大きい)

### [ ] stylix — base16 で全アプリに一括カラー適用

GTK/Qt/Niri/Ghostty/WezTerm/Zathura/bat/yazi/mpv/fuzzel/delta などを一発で同じカラーパレットに揃えられる。
現状各ファイルでDraculaの色をベタ書きしている部分が消える。

**flake.nix に追加**:
```nix
inputs.stylix = {
  url = "github:danth/stylix";
  inputs.nixpkgs.follows = "nixpkgs";
  inputs.home-manager.follows = "home-manager";
};
```

**設定例** (`home/modules/desktop/stylix.nix`):
```nix
{ pkgs, ... }:
{
  stylix = {
    enable = true;
    image = ./wallpapers/dark.jpg;  # ベースになる壁紙
    base16Scheme = "${pkgs.base16-schemes}/share/themes/dracula.yaml";
    polarity = "dark";
    fonts = {
      monospace = {
        package = pkgs.nerd-fonts.jetbrains-mono;
        name = "JetBrainsMono Nerd Font";
      };
      sansSerif = { package = pkgs.noto-fonts-cjk-sans; name = "Noto Sans CJK JP"; };
      serif     = { package = pkgs.noto-fonts-cjk-serif; name = "Noto Serif CJK JP"; };
      sizes = { applications = 11; terminal = 13; popups = 11; };
    };
    cursor = {
      package = pkgs.bibata-cursors;
      name = "Bibata-Modern-Classic";
      size = 24;
    };
    targets = {
      # 自分で書いた設定と衝突するのは無効化する
      # 例: ghostty を自前管理ならここで targets.ghostty.enable = false;
    };
  };
}
```

導入後は `gtk.nix` の theme/iconTheme/cursorTheme、`zathura.nix` のrecolor設定、`ghostty.nix` のtheme/font設定、`vimiv.conf` のスタイル、`fuzzel.ini` のcolors、`yazi/theme.toml` 等が stylix 経由で生成されるようになるので順次削除。

**注意**: 全部一気に切り替えると差分が大きい。最初は `targets.<app>.enable = false` で除外しつつ、1つずつ移行する。

---

### [ ] UDEV Gothic NF — CJK等幅フォント

ターミナルで CJK が綺麗に等幅で並ぶ。

```nix
# nixos/modules/desktop/desktop.nix の fonts.packages に
udev-gothic-nf
```

ghostty/wezterm の `font-family` を `"UDEV Gothic NF"` に変えると CJK混在のレイアウトが綺麗。

---

## P2: システム/セキュリティ

### [ ] trusted-users 設定

Cachix push やローカルリモートビルドで必要。

```nix
# nixos/hosts/ser7/default.nix の nix.settings に
trusted-users = [ "root" "morikawa" ];
```

---

### [ ] systemd-boot 世代数制限

メニューが肥大化しないように。

```nix
boot.loader.systemd-boot.configurationLimit = 20;
```

---

### [ ] fstrim 明示有効化

`common-pc-ssd` で入っている可能性あるが念のため明示。

```nix
services.fstrim.enable = true;
```

---

### [ ] firefox 有効化の見直し

`users.nix` で `programs.firefox.enable = true` しているが、メインは Vivaldi/Zen のはず。
要らないなら削除して `home.packages` 経由に統一。

---

## P2: 周辺機器

### [ ] avahi (mDNS)

LAN 上の `*.local` 名前解決。プリンタ自動発見、Tailscale補助。

```nix
{
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = true;
  };
}
```

---

### [ ] Android連携

実機接続したい場合。

```nix
{
  programs.adb.enable = true;
  services.udev.packages = [ pkgs.android-udev-rules ];
  users.users.morikawa.extraGroups = [ "adbusers" ];
}
```

---

## キーバインド設計の方針案 (CapsLockなし問題)

xremap によるアプリ別 Ctrl⇔Super スワップは Niri (ext-foreign-toplevel-list-v1) と xremap (wlr-foreign-toplevel-management) のプロトコル不一致で破綻している。

### 案: キーボードファーム層 (QMK/VIA) で完結させる

- 自作キーボード前提のバインドが既に niri.nix に多数ある (`semicolon`/`apostrophe`/`equal` 等)
- ハード層で Ctrl/Super を入れ替えるなら OS の認識は1つで済み、Niri/xremap 双方の検出問題が消える
- レイヤー切替 (アプリ起動レイヤー vs Unix Ctrlレイヤー) もファーム側でやれば最も堅い

代替案: ターミナル側で完結。`ghostty` の `keybind` で `super+c` を `copy_to_clipboard` に既に割り当ててあるが、シェル内で本物の Ctrl が必要な操作 (`Ctrl+C` の SIGINT 等) との分離はターミナル設定の `command:`プレフィクス機能でやれる場合あり。

---

## 着手順 推奨

1. **P0 (`nix-ld`, `zramSwap`, `oomd`, `fwupd`)** — 1ファイル追加、リスク低、即効性高
2. **`openssh`** — 他端末からの作業が一気に楽になる
3. **gaming スタック (`gamemode`, `gamescope`, `mangohud`)** — Steam の体感アップ
4. **`backup`** — sops に passphrase 追加 → borg init → 自動化
5. **`stylix`** — 設定が縮む。後の追加で効いてくる (1モジュールずつ移行)
6. **その他 P1/P2** は欲しいタイミングで個別に

---

# 次に試す枠 (実装スニペット決定済み)

「気になる」と判断した4本。家で即追加できる形にしてある。

## [ ] nix-tree — Nix store 依存ツリーを TUI 探検

`/run/current-system` を食わせると「何がなぜ入っているか」を全部追える。
flake.lock の input 由来や、間接依存で引き込まれてる謎パッケージの正体を掴むのに最強。

```nix
# home/modules/cli/tools.nix の home.packages に追加
nix-tree
```

**使い方**:
```bash
nix-tree                                # カレント home-manager profile
nix-tree /run/current-system            # NixOS システム全体
nix-tree --derivation                   # ビルド時依存も含めて
nix-tree $(nix path-info -r /run/current-system | head -1)
```

TUI内で:
- `/` 検索 / `?` ヘルプ / `Enter` 子に潜る / `h` 親へ / `y` whyを表示

---

## [ ] vhs — `.tape` DSL でターミナル操作を GIF/MP4 録画

dotfiles READMEや Obsidian の手順メモに動画が貼れるようになる。
ttyd を内部で起動するので無人実行可能。

```nix
# home/modules/cli/tools.nix の home.packages に追加
vhs
ttyd     # vhs が内部で使う (依存になってるはずだが念のため)
# ffmpeg は既存
```

**最小サンプル** (`~/scratch/demo.tape`):
```
Output demo.gif
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"

Type "ls -la"
Enter
Sleep 1s

Type "nix-tree"
Enter
Sleep 3s
```

```bash
vhs ~/scratch/demo.tape    # demo.gif が生成される
vhs new mydemo.tape        # テンプレ生成
```

**応用**: dotfiles リポジトリの `docs/demos/*.tape` に置いて、CI または手動で `vhs *.tape` を回すと README が華やかになる。

---

## [ ] fastfetch — neofetch の Rust/C 後継

起動が速く、JSON で完全に layout を定義できる。zsh 起動時に毎回出しても重くない。
home-manager に専用モジュールがあるので JSON 直書きせずに済む。

**新規ファイル** `home/modules/cli/fastfetch.nix`:

```nix
{ ... }:
{
  programs.fastfetch = {
    enable = true;
    settings = {
      logo = {
        type = "small";       # 大きい AA が嫌なら small / または "none"
        padding = { right = 2; };
      };
      display = {
        separator = "  ";
      };
      modules = [
        "title"
        "separator"
        "os"
        "host"
        "kernel"
        "uptime"
        "packages"
        "shell"
        "wm"
        "terminal"
        "cpu"
        "gpu"
        "memory"
        "swap"
        "disk"
        "localip"
        "battery"
        "break"
        "colors"
      ];
    };
  };
}
```

`home/home.nix` の imports に `./modules/cli/fastfetch.nix` を追加。

**起動時に毎回出したい場合** (zsh.nix の `initContent` 末尾に):
```bash
# fastfetch を初回ログインのみ表示
if [[ -z "$FASTFETCH_SHOWN" ]] && [[ -o interactive ]]; then
  export FASTFETCH_SHOWN=1
  fastfetch
fi
```

---

## [ ] frogmouth — Markdown TUI ブラウザ

URL も食える。Obsidian ノートや GitHub の README をターミナルで快適に読める。
`glow` よりインタラクティブ (リンクをジャンプできる)。

```nix
# home/modules/cli/tools.nix の home.packages に追加
frogmouth
```

**使い方**:
```bash
frogmouth README.md
frogmouth https://raw.githubusercontent.com/Textualize/frogmouth/main/README.md
frogmouth ~/obsidian_valut/mainValut/04-Permanent/NixOS\ dotfiles\ 改善プラン.md
```

TUI 内で:
- `t` Table of Contents / `b` ブックマーク / `m` history / `/` 検索 / `q` quit

**Obsidian 連携アイデア**: yazi の Markdown プレビューを frogmouth に差し替えると Vault がターミナルから読みやすくなる。

---

## 4本まとめて適用する手順

```bash
# 1. tools.nix と新規 fastfetch.nix を編集
# 2. home.nix の imports に fastfetch.nix を追加
# 3. flake check
nix flake check ~/.dotfiles

# 4. dry-run
home-manager build --flake ~/.dotfiles#morikawa@nixos

# 5. 適用
nh home switch

# 6. 動作確認
nix-tree /run/current-system
vhs new test.tape && vhs test.tape
fastfetch
frogmouth ~/.dotfiles/docs/improvement-plan.md
```

---

# 嗜好分析と追加候補

既存パッケージから検出した嗜好パターンと、それに刺さりそうな未導入ツール。

## 検出された嗜好パターン

| パターン | 根拠 |
|---|---|
| モーダルUI愛好 | yazi / vimiv-qt / zathura / nvim / mpv (h,j,k,l) / lazygit |
| Rust製モダンCLI総入れ替え | bat / eza / ripgrep / zoxide / bottom / atuin / delta / ouch / fzf-tab / sheldon |
| TUI dashboard 好き | ncspot / lazygit / yazi / visidata / bottom / glow |
| Wayland最先端追従 | Niri (scrollable WM) / noctalia-shell (QML) / fuzzel |
| マルチ端末連携 | Tailscale + Syncthing + KDE Connect + Parsec + Remmina + NAS(cifs) |
| AI/LLM ワークフロー組込み | claude-code-nix / MCP / bonsai / rtk |
| メディア・ドキュメント中心 | mpv (gpu-next+vulkan+loudnorm) / yt-dlp / ffmpeg / imagemagick / calibre / zathura |
| podman 派 | dockerCompat |
| オーディオ深掘り | pipewire + alsa32 + jack + mpv loudnorm |
| テーマ統一執念 | Dracula を全アプリにベタ書き同期 |

## 最優先候補 (導入コスト低 × 体感変化大)

### [ ] zellij

Rust製モーダル tmux 代替。Niri と同じ「タイル × モーダル」哲学。
yazi/lazygit/atuin と完全に同じ系譜。

```nix
{
  programs.zellij = {
    enable = true;
    enableZshIntegration = false;  # 自動起動はOFF推奨。手動で `zellij` 起動
    settings = {
      theme = "dracula";
      default_layout = "compact";
      pane_frames = false;
      copy_command = "wl-copy";
      copy_on_select = true;
    };
  };
}
```

### [ ] fd, sd, hexyl, xh

ripgrep/delta を持ってる人が無いのが不自然な定番群。

```nix
# home/modules/cli/tools.nix の home.packages に追加
fd          # find のRust代替
sd          # sed のRust代替 (`s/old/new/` シンプル構文)
hexyl       # xxd の bat 風カラー版
xh          # httpie の Rust 版 (起動速い)
dog         # dig のカラー代替
navi        # 対話型コマンドチートシート (tealdeer の能動版)
```

### [ ] easyeffects + helvum

mpv で loudnorm まで触る耳の人にはマスト。

```nix
{
  services.easyeffects.enable = true;  # PipeWire EQ/compressor/noise-suppression
}

# home.packages
helvum       # PipeWire パッチベイ GUI (JACK enable してるなら必携)
```

---

## モーダル × Rust CLI × TUI

| ツール | 用途 | snippet |
|---|---|---|
| **helix** | Rust製モーダルエディタ。LSP内蔵 | `programs.helix.enable = true;` |
| **broot** | Rust製ツリー+ファジーナビ。`br` でcd | `programs.broot.enable = true;` |
| **ast-grep** | 構文木 grep。Nix/Lua/Rust リファクタで rg より精密 | `home.packages = [ pkgs.ast-grep ];` |
| **fclones** | 重複ファイル検出。Pictures/Videos 整理 | `home.packages = [ pkgs.fclones ];` |
| **jujutsu (jj)** | Rust製 git 互換 VCS。コンフリクト解消が劇的に楽 | `programs.jujutsu.enable = true;` |
| **just** | make のモダン代替。`justfile` で雑用整理 | `home.packages = [ pkgs.just ];` |
| **carapace** | 全コマンド統合補完。fzf-tab と組合せ強力 | `programs.carapace.enable = true;` |
| **monolith** | Webページを1HTML保存 (Obsidian クリップ) | `home.packages = [ pkgs.monolith ];` |

## TUI ダッシュボード追加

| ツール | 用途 |
|---|---|
| **gh-dash** | gh の PR/Issue を lazygit 風に一望 |
| **lazydocker** | podman でも動作。lazygit 愛好家への必然 |
| **serie** | git log を木構造で可視化する TUI |
| **slumber** / **posting** | TUI HTTPクライアント。API テストで Postman 不要に |
| **dive** | コンテナイメージのレイヤー検査 TUI |
| **podman-tui** | コンテナ・Pod 管理を TUI で |

```nix
# 例: home/modules/cli/tui.nix にまとめる場合
{ pkgs, ... }: {
  home.packages = with pkgs; [
    gh-dash
    lazydocker
    serie
    slumber       # or posting
    dive
    podman-tui
  ];
}
```

## Wayland 最先端志向 (Niri/Noctalia の延長)

| ツール | 用途 |
|---|---|
| **swww** | アニメ壁紙デーモン。Noctalia 静止画担当なら subtle motion 用 |
| **anyrun** | プラグイン式ランチャー。fuzzel の補強または置換 |
| **walker** | Go製モダンランチャー。AI/clipboard プラグインあり |
| **wl-mirror** | Wayland 画面ミラー (デモ用) |

## LLM/AI 統合 (claude-code + MCP + rtk の延長)

| ツール | 用途 |
|---|---|
| **aider** | ターミナル pair programming。CLI 単発リファクタで強い |
| **llm** (Simon Willison) | `llm "..." -m claude-4-opus`、SQLite ログ |
| **mods** (charm) | パイプ流し込み LLM (`cat file \| mods "要約"`) |
| **fabric** | プロンプトライブラリ・パッケージマネージャ |
| **aichat** | Rust 製、多 provider 統一クライアント |
| **ollama** | ローカル LLM。AMD APU/dGPU なら ROCm で動く |

```nix
# 例
home.packages = with pkgs; [
  aider-chat
  llm
  mods
  aichat
];
# ollama はサービス化
services.ollama = {
  enable = true;
  acceleration = "rocm";  # AMD GPU の場合
};
```

## マルチ端末・転送 (Tailscale+Syncthing+KDEConnect+NAS の系譜)

| ツール | 用途 |
|---|---|
| **localsend** | KDE Connect+α。スマホ/PC/Linux 横断で雑に送れる GUI |
| **croc** | 一行で端末間ファイル転送、E2E 暗号化 |
| **rclone** | Backblaze/B2/S3/GDrive 同期。borgbackup 外のクラウド層 |
| **sshfs** | LAN 外サーバ mount。Tailscale 経由で軽量 |

## ドキュメント/PKM (Obsidian + glow + zathura + calibre の系譜)

| ツール | 用途 |
|---|---|
| **typst** | LaTeX のモダン代替。Rust 製・即コンパイル。Zathura で PDF 確認の流れに乗る |
| **pandoc** | あらゆる文書形式変換。calibre/Obsidian 横断時に効く |
| **zk** | Zettelkasten CLI。Obsidian Vault を CLI で検索/新規/テンプレ展開 |
| **marp-cli** | Markdown → スライド |
| **marksman** | Markdown LSP。Wikilinks 補完が nvim で効く |

## 日本語環境 (CJK 細指定 + mozc 派)

| ツール | 用途 |
|---|---|
| **mecab** | 形態素解析 CLI。日本語処理の定番 |
| **nkf** | 文字コード変換。古い zip/eml で必要になる |
| **textlint** + prh ルール | 日本語 Lint。Obsidian ノート品質維持 |

## 既存設定で気になった点 (調査メモ)

- `users.nix` で `programs.starship.enable = true` だが、sheldon の `plugins.toml` が `pure` (sindresorhus) を読み込んでいる。二重プロンプトの可能性があるので、どちらかに統一推奨
- `eza`, `bat`, `ripgrep`, `zoxide` を持っているのに `fd` だけ無い → 追加候補の筆頭

---

---

# 棚卸し決定

カテゴリ別の整理結果。家での適用待ち。

## A. ターミナルエミュレータ → Ghostty 主軸 + Alacritty 保険

**決定**: wezterm を撤去し、Ghostty を主軸に。Alacritty は Ghostty が壊れた時の最終フォールバックとして残す (設定なし、素のまま)。

**捨てる機能** (代替を用意しない判断):
- copy mode (vim風スクロール検索)
- QuickSelect (URL/パスピッカー)
- command palette
- leader key (prefix-based bind)
- char select (unicode picker)
- ウィンドウ最小化
- 設定 auto-reload
- tabline の process/cwd 表示
- 内蔵 multi-domain SSH

### 作業手順

```bash
cd ~/.dotfiles

# 1. ghostty.nix を編集 (3点)
#    (a) settings 内の `# font-feature = "zero";` のコメントを外す
#    (b) keybind 配列に `"super+k=clear_screen"` を追加
#    (c) `terminal` shellScriptBin ラッパーを ghostty に向けて先頭 let に追加
#         (wezterm.nix から移植: pkgs.writeShellScriptBin "terminal" "exec ghostty ...")
#         home.packages = [ terminal ]; を追加

# 2. wezterm 削除
git rm home/modules/desktop/wezterm.nix
git rm -r home/modules/desktop/wezterm/

# 3. home.nix の imports から wezterm.nix を削除

# 4. alacritty は残す (ghostty コケた時のフォールバック)
#    apps.nix の "# サブターミナル" コメントを "# フォールバック (ghostty障害時)" に変更推奨

# 5. xremap.nix の application.only から wezterm を削除
#    (org.wezfurlong.wezterm の行を削除、残るのは ghostty のみ)

# 6. 検証
nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos

# 7. 適用
nh home switch

# 8. 動作確認
ghostty --version
which terminal && terminal &
```

### コミット粒度の推奨

1コミットでまとめてOK (関連変更が多い):
```
refactor(desktop): ターミナルを Ghostty 主軸に整理

- wezterm モジュールを削除
- terminal ラッパーを Ghostty 向けに移管
- ghostty に slashed-zero と clear_screen バインドを追加
- xremap の対象アプリから wezterm を除外
- alacritty は ghostty コケた時のフォールバックとして残す
```

### 注意点

- `terminal` コマンドが mimeapps の x-scheme-handler やランチャーから参照されている可能性 → 移管後に `terminal` で ghostty が起動するか必ず確認
- Niri 起動直後の挙動確認 (xremap が ghostty のみ対象になる)
- `xdg.mimeApps.defaultApplications` に `wezterm.desktop` 参照があれば消す

### 後続候補

ターミナル統一後、leader key / copy mode / QuickSelect が欲しくなった場合のみ **zellij** を追加 (「次に試す枠」参照)。
不要なら追加しない。

---

## B. プロンプト → pure 単独に統一

**決定**: starship を撤去し、sheldon 経由の pure 一本化。

### 背景

- `nixos/modules/system/users.nix:15` で `programs.starship.enable = true`
- `home/modules/cli/sheldon/plugins.toml` で pure を後読み
- pure が PROMPT を上書きするので見た目は pure だが、starship の `precmd_functions` が無駄に走り続けている

### 作業手順

```bash
cd ~/.dotfiles

# 1. users.nix を編集
#    nixos/modules/system/users.nix の programs ブロックから
#      starship.enable = true;
#    を削除

# 2. 検証
nix flake check ~/.dotfiles
nh os switch --dry

# 3. 適用
nh os switch

# 4. 確認
exec zsh
print -l $precmd_functions
# → starship_precmd や starship 由来の関数が残っていないことを確認
```

### コミットメッセージ案

```
refactor(shell): プロンプトを pure 単独に統一

users.nix の starship.enable を削除。
sheldon 経由の pure と二重起動になっていた。
```

### (任意) Dracula 色合わせ

`home/modules/shell/zsh.nix` の `initContent` の `eval "$(sheldon source)"` より **前** に追加:

```bash
zstyle :prompt:pure:prompt:success color "#bd93f9"   # Dracula purple
zstyle :prompt:pure:prompt:error   color "#ff5555"   # Dracula red
zstyle :prompt:pure:git:branch     color "#f1fa8c"   # Dracula yellow
zstyle :prompt:pure:git:dirty      color "#ffb86c"   # Dracula orange
zstyle :prompt:pure:path           color "#8be9fd"   # Dracula cyan
```

不要ならデフォルトのまま。

### 完了条件

- [ ] `users.nix` から `programs.starship.enable = true;` 削除
- [ ] `nh os switch` 後、`❯` が pure で表示される
- [ ] `print -l $precmd_functions` に starship 由来関数が無い

---

## C. ブラウザ → 現状維持

**決定**: Vivaldi (メイン) + Zen (体験中) + Firefox (保険) の3軸を維持。
3つで管理方式 (home-manager / flake input / NixOS system) が違うが、それぞれの役割と整合しているため変更しない。

将来検討メモ:
- Vivaldi の `--force-dark-mode` が独自ダークモード持ちサイトで二重反転する場合は外す
- WebRTC IP漏洩対策が必要になったら `--webrtc-ip-handling-policy=default_public_interface_only` を追加

---

## D. リモートデスクトップ → 両方削除

**決定**: parsec-bin + remmina とも削除。初回動作確認以外で使用していないため。
必要時は `nix run nixpkgs#remmina` で取り出し運用に切り替え。

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/desktop/apps.nix から以下2行を削除
#   parsec-bin         # 超速いリモートデスクトップクライアント
#   remmina            # VNCクライアント

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch
```

### コミットメッセージ案

```
chore(apps): 未使用のparsec-bin/remminaを削除

初回動作確認以降使っていない。
必要時は nix run nixpkgs#remmina で代替。
```

### 将来候補 (使いたくなった時のみ)

- **Sunshine + Moonlight** — OSS の Parsec 代替。AMD VAAPI 対応、Tailscale 内完結
- **input-leap** — Windows機が時々起動する用途なら、画面ではなく入力(マウス/キーボード)共有という選択肢
- **freerdp** — CLI で直接 RDP したい時の最軽量解

---

## E. PDF/メディア → 重複ビューア削除

**決定**: evince と totem を削除。zathura/mpv が mime defaults を握っており、これらは死蔵状態だったため。calibre と jellyfin-mpv-shim は役割が独立しているので維持。

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/desktop/apps.nix から以下2行を削除
#   evince             # PDFビューアー（GNOME）
#   totem              # ビデオプレーヤー

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# 動作確認
xdg-open ~/Documents/sample.pdf    # → zathura
xdg-open ~/Videos/sample.mp4       # → mpv
```

### コミットメッセージ案

```
chore(apps): mime defaults と重複する evince/totem を削除

zathura が PDF mime、mpv が video/audio mime のデフォルトを握っており、
evince/totem は手動起動経路でしか使われていなかった。
```

### 完了条件

- [ ] `apps.nix` から evince と totem を削除
- [ ] `xdg-open` で PDF → zathura、動画 → mpv が起動することを確認

### calibre 周り将来検討メモ (任意)

- `electron` を別途 `home.packages` に入れてるが、コメントに「Obsidian CLI 用」
- Obsidian CLI 専用なら別の選択肢 (`obsidian-cli` 自体を直接) も検討余地あり (今は触らない)

---

## F. zsh プラグイン (sheldon) → 死コード除去のみ

**決定**: F1 案。確実に死んでいる2プラグインを削除。Nix declarative 寄せは保留 (F2/F3 として将来余地)。

### 削除対象と根拠

| 削除 | 根拠 |
|---|---|
| `[plugins.zoxide]` | `use` 指定なし。zoxide リポを clone してるだけで何も実行されていない |
| `[plugins.history-search-multi-word]` | atuin が `^R` を奪うため発火しない死コード |

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/cli/sheldon/plugins.toml から以下2ブロックを削除
#
#   [plugins.history-search-multi-word]
#   github = "zdharma/history-search-multi-word"
#
#   [plugins.zoxide]
#   github = "ajeetdsouza/zoxide"
#
# (zoxide-init ブロックは残す。これが本体)

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# 動作確認
exec zsh
# Ctrl+R で atuin の TUI が立ち上がる (history-search-multi-word が無くなっても同じ挙動)
# zoxide も従来通り (`z foo` で動く)
```

### コミットメッセージ案

```
chore(zsh): 死コードな sheldon プラグイン2つを削除

- history-search-multi-word: atuin が Ctrl+R を奪うため発火しない
- zoxide ブロック: use 指定なしで実質クローンのみだった
  (zoxide-init の inline eval が本体)
```

### 完了条件

- [ ] plugins.toml から該当2ブロックを削除
- [ ] `exec zsh` 後、Ctrl+R で atuin TUI が出ること
- [ ] `z` コマンドが従来通り動作すること

### 将来の格上げ余地

- **F2**: zoxide を `programs.zoxide.enable = true` で Nix declarative 化 (zoxide-init ブロック削除 + tools.nix の zoxide パッケージ削除)
- **F3**: autosuggestions / fast-syntax-highlighting も Home Manager 内蔵オプション (`programs.zsh.autosuggestion.enable`, `syntaxHighlighting.enable`) に寄せて sheldon を最小化

---

## G. CLI ツール群 → G2 (atool/htop 削除 + Rust CLI 5本追加)

**決定**: 死蔵ツール削除 + 嗜好高の追加 + bottom 一本化。

### 削除

| ツール | 根拠 |
|---|---|
| **atool** | yazi.toml の archive 処理は `ouch decompress` と `unzip -O cp932` で完結。コメント「aunpack、yaziから使用」は実態と乖離した古い記述だった |
| **htop** | bottom が機能的に上位互換 (CPU/Mem/Net/Disk/Temp 含む)。プロセス kill も bottom 内でできる |

### 追加

| ツール | 用途 |
|---|---|
| **fd** | `find` の Rust 代替。ripgrep持ってる人に欠けていた定番 |
| **sd** | `sed` 代替。`s/old/new/` シンプル構文 |
| **xh** | httpie の Rust 版、起動速い (httpie は当面並行運用) |
| **navi** | 対話型コマンドチートシート (tealdeer の能動版) |
| **hyperfine** | ベンチマーク (`hyperfine 'cmd1' 'cmd2'`) |

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/cli/tools.nix を編集
#
# 削除:
#   atool         # アーカイブ展開（aunpack、yaziから使用）
#   htop          # プロセスモニター
#
# 追加 (home.packages 配列に):
#   fd          # find の Rust 代替
#   sd          # sed の Rust 代替
#   xh          # httpie の Rust 版
#   navi        # 対話型チートシート
#   hyperfine   # ベンチマーク

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# 動作確認
fd .              # find代替が動く
sd 'foo' 'bar' <<< 'foobar'   # sed代替
xh https://httpbin.org/json
hyperfine 'sleep 0.1' 'sleep 0.2'
navi              # チートシート TUI
btm               # bottom 起動 (htop代替確認)
```

### コミットメッセージ案

```
refactor(cli): atool/htop を整理し Rust CLI 5本を追加

- atool: yazi の archive は ouch/unzip で完結しており死蔵
- htop: bottom が機能的に上位互換のため統合
- 追加: fd, sd, xh, navi, hyperfine
```

### 完了条件

- [ ] tools.nix から atool, htop の2行を削除
- [ ] tools.nix の home.packages に fd, sd, xh, navi, hyperfine を追加
- [ ] yazi で zip/rar を展開して動作確認 (ouch + unzip 経路で問題なし)
- [ ] `btm` が起動する (htop からの移行確認)

### 後回し候補 (G3 にした場合の追加分)

`, dust` `, procs` `, hexyl` `, dog` `, bandwhich` `, gping` — comma 経由で取り出す運用にする。
頻度が上がった時に G3 へ格上げ。

---

## H. LSP/言語ランタイム → H3 (Mason 完全停止 + Nix 完全管理)

**優先度: 低**。やる気のある集中ブロック取れる日に一気に進める。
小分けすると中途半端で壊れやすいので **1セッションで完走** を推奨。

### なぜ「ごちゃごちゃ」していたか (背景)

- LazyVim 既定で Mason 有効 → 各言語の LSP/formatter を Mason がインストールしようとする
- NixOS で Mason の pre-built バイナリは glibc/動的リンカ不整合で壊れがち
- `nix-mason.lua` で `nil_ls` と `rust_analyzer` のみ `mason = false` にしている
- → **他の言語は Mason 経由で壊れたまま放置** されている状態
- かつ neovim.extraPackages と tools.nix のhome.packages が二重・重複状態

### 完了後の状態

- Mason 関連プラグインを LazyVim 内で全 disable
- LSP/formatter は **全て Nix で明示インストール**
- 「ごちゃごちゃ」根絶、再現性最強
- 新言語に手を出した日は nix を編集してから (年数回の小コスト)

### 作業手順

#### ステップ 1: nodejs 重複解消 + treesitter 周り整理

```nix
# home/modules/cli/tools.nix home.packages
# 変更:
nodejs       # ← nodejs_22 に
# →
nodejs_22

# home/modules/cli/neovim.nix extraPackages から削除:
tree-sitter   # withAllGrammars があるので不要
gcc           # 同上
nodejs_22     # user PATH の nodejs_22 を借りる
```

#### ステップ 2: dev.nix 新規モジュール作成

`home/modules/cli/dev.nix` を新規作成し、LSP/formatter を集約:

```nix
{ pkgs, ... }: {
  home.packages = with pkgs; [
    # LSP
    nil                            # Nix
    rust-analyzer                  # Rust
    lua-language-server            # Lua
    vscode-json-languageserver     # JSON
    basedpyright                   # Python
    bash-language-server           # Bash
    marksman                       # Markdown (Obsidian Vault 補完)
    yaml-language-server           # YAML
    taplo                          # TOML

    # formatter
    rustfmt
    nixfmt-rfc-style
    shfmt
    stylua                         # Lua
    prettier                       # JS/TS/JSON/MD/YAML
    ruff                           # Python lint+format
  ];
}
```

`home/home.nix` の imports に `./modules/cli/dev.nix` を追加。

#### ステップ 3: neovim.nix を最小化

```nix
# home/modules/cli/neovim.nix
{inputs, config, pkgs, lib, ...}:
{
  # nvim symlink (既存維持)
  home.activation.nvimSymlink = lib.hm.dag.entryAfter ["writeBoundary"] ''
    # ... 既存のまま
  '';

  programs.neovim = {
    enable = true;
    viAlias = true;
    vimAlias = true;
    defaultEditor = true;
    # extraPackages は空にする (dev.nix に移管済み)
  };

  home.packages = with pkgs; [
    (vimPlugins.nvim-treesitter.withAllGrammars)
  ];
}
```

#### ステップ 4: nix-mason.lua を Mason 完全停止に書き換え

```lua
-- home/modules/cli/nvim/lua/plugins/nix-mason.lua
-- Mason 関連を完全に無効化。LSP は Nix で provide される前提。
return {
  { "mason-org/mason.nvim", enabled = false },
  { "mason-org/mason-lspconfig.nvim", enabled = false },
  { "WhoIsSethDaniel/mason-tool-installer.nvim", enabled = false },

  -- LazyVim の各 lang extras が opts.servers に mason=true を入れるのを一括上書き
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
```

#### ステップ 5: 検証

```bash
cd ~/.dotfiles
nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# nvim 起動して :checkhealth で各 LSP の状態確認
nvim +':checkhealth lsp'
nvim +':Lazy' # → Mason 系プラグインが disabled 表示
nvim +':LspInfo' # → 各 LSP が Nix 由来の path を指している

# 各言語ファイルを開いて補完が効くか
nvim sample.py    # → basedpyright が起動
nvim sample.lua   # → lua-language-server
nvim sample.sh    # → bash-language-server
nvim sample.md    # → marksman
nvim sample.nix   # → nil_ls
```

#### ステップ 6: 既存の Mason データ削除 (掃除)

```bash
# Mason がローカルに置いていたバイナリを掃除
rm -rf ~/.local/share/nvim/mason
```

### コミット分割案

3コミットに分けると review しやすい:

```
1. refactor(nvim): nodejs と treesitter 重複を整理
   - tools.nix で nodejs → nodejs_22
   - neovim extraPackages から tree-sitter/gcc/nodejs_22 削除

2. feat(dev): LSP/formatter を dev.nix に集約
   - 新規 home/modules/cli/dev.nix
   - basedpyright, bash-language-server, marksman, yaml-language-server, taplo を追加
   - stylua, prettier, ruff を追加

3. refactor(nvim): Mason を完全停止し Nix 由来 LSP に統一
   - nix-mason.lua を全停止 + opts.servers 一括 mason=false
   - ~/.local/share/nvim/mason は手動削除
```

### 完了条件

- [ ] `:LspInfo` で全 LSP が Nix store path を指している
- [ ] `:Lazy` で Mason 系プラグインが disabled
- [ ] Python/Bash/Markdown/YAML/TOML ファイルで補完が効く
- [ ] `~/.local/share/nvim/mason` 削除済み
- [ ] `nh home switch` がエラー無く通る

### 詰まったときの戻し方

`nix-mason.lua` だけ git revert で復活 → Mason 半停止状態に戻る (元のごちゃごちゃ状態だがとりあえず動く)。
dev.nix と neovim.nix の変更は安全 (壊れない側の整理)。

### 着手の目安

- 集中時間 1〜2時間取れる日
- 直前に LazyVim 自体の更新 (`:Lazy sync`) を済ませておく
- 進めながら Obsidian に作業ログを残すと、詰まった時の戻り先がはっきりする

---

## I. ゲーミング → Bottles/EasyRPG 撤去 + Steam Proton 強化

**決定**: 非 Steam の Windows exe を Steam の Proton (GE-Proton) で一本化する方針。

### 削除

| 対象 | 理由 |
|---|---|
| **easyrpg-player** | RPG Maker 2000/2003 専用で塩漬け。新作は Steam Proton GE で代替 |
| **bottles** | Steam の "Add a Non-Steam Game" + Proton GE で代替可 |
| **`dedicatedServer.openFirewall = true`** | Steam dedicated server を立てた実績なし → デフォルト false に |

### 追加

| 追加 | 役割 |
|---|---|
| **gamemode** | CPU ガバナ昇格 |
| **gamescope** | スケーリング・HDR・フレーム制限 |
| **mangohud** | FPS/温度オーバーレイ |
| **corectrl** | AMD GPU 電力カーブ GUI |
| **proton-up-qt** | GE-Proton 等カスタム Proton 導入 GUI (非 Steam ゲーム代替の要) |
| **protontricks** | 特定 Proton prefix に winetricks 当てる |

### 設定差分

```nix
# nixos/hosts/ser7/default.nix
programs.steam = {
  enable = true;
  remotePlay.openFirewall = true;
  # dedicatedServer.openFirewall = true;   # 削除
  gamescopeSession.enable = true;          # 追加 (任意)
};

programs.gamemode.enable = true;
programs.gamescope = {
  enable = true;
  capSysNice = true;
};
programs.corectrl = {
  enable = true;
  gpuOverclock.enable = true;
};
```

```nix
# nixos/modules/system/users.nix
users.users.morikawa = {
  extraGroups = [ "networkmanager" "wheel" "input" "corectrl" ];  # corectrl 追加
};
```

```nix
# home/modules/desktop/apps.nix
home.packages = with pkgs; [
  # 削除:
  #   bottles
  #   easyrpg-player

  # 追加:
  mangohud
  goverlay         # MangoHud 設定 GUI (任意)
  protonup-qt
  protontricks
];
```

### 作業手順

```bash
cd ~/.dotfiles

# 1〜3. 上記の3ファイルを編集

nix flake check ~/.dotfiles
nh os switch --dry
nh os switch
nh home switch

# 4. GE-Proton 導入
protonup-qt   # GUI で 1〜2 バージョン入れる

# 5. Steam 再起動 → Steam Play 設定で GE-Proton が選択可能
```

### Bottles 撤去後の Windows exe 動作フロー

1. Steam で `Games → Add a Non-Steam Game`
2. ライブラリで該当ゲーム右クリック → Properties → Compatibility → `Force the use of a specific Steam Play compatibility tool` → **GE-Proton** 選択
3. 起動

### コミット分割案

```
1. refactor(gaming): bottles と easyrpg-player を撤去
2. fix(gaming): dedicatedServer.openFirewall を無効化
3. feat(gaming): gamemode/gamescope/corectrl/mangohud 等を追加
```

### 完了条件

- [ ] apps.nix から bottles, easyrpg-player を削除
- [ ] default.nix の dedicatedServer.openFirewall 行を削除
- [ ] gamemode/gamescope/corectrl を default.nix に追加
- [ ] mangohud/protonup-qt/protontricks を apps.nix に追加
- [ ] users.nix の extraGroups に corectrl を追加
- [ ] proton-up-qt で GE-Proton 導入済み
- [ ] 適当な Windows exe を Steam に追加して GE-Proton で動くか確認

### 後日候補

- **heroic-games-launcher** — Epic 無料配布拾いたい時に追加
- **lutris** — Bottles 撤去後 1〜2ヶ月で「やっぱり統合ランチャー欲しい」となったら検討
- **dolphin-emu / rpcs3 / pcsx2 / retroarch** — エミュレータ系。手を出した日に個別追加

---

## J. 認証/シークレット → bitwarden-cli 削除のみ

**決定**: sops + age と lxqt-policykit は維持。bitwarden-cli のみ撤去。

### 削除

| 対象 | 根拠 |
|---|---|
| **bitwarden-cli** | sops 導入後 CLI 経路は実質未使用。Bitwarden vault は維持し、Vivaldi 拡張/web で運用 |

### 維持

- sops-nix + age (中核)
- lxqt-policykit (Qt 系で統一感、Niri spawn-at-startup で確実動作)

### 保留 (現状維持)

- `.smbcredentials` 平文 — ser7 単独ホスト・LAN 内 NAS の前提では sops 化メリットが小さい。マシン増えた日に格上げ候補

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/cli/tools.nix から削除
#   bitwarden-cli # パスワード管理CLI

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch
```

### コミットメッセージ案

```
chore(cli): 未使用の bitwarden-cli を削除

sops 導入後 CLI 経路は実質使われていない。
必要時は nix run nixpkgs#bitwarden-cli または rbw を検討。
```

### 完了条件

- [ ] tools.nix から bitwarden-cli を削除
- [ ] Vivaldi の Bitwarden 拡張が動作することを確認

### 将来候補メモ

- **rbw** — CLI 復活させたくなったら Rust 製の高速代替
- **`.smbcredentials` sops 化** — マシンが増えた日に
- **gpg-agent + ssh-agent 統合** — P0 にある GPG agent 整備時に合わせて

---

## K. xremap / キーリマップ → 未決定 (保留)

**決定**: 一旦保留。現状の xremap (Niri と相性破綻状態) はそのまま残す。

### 検討した選択肢 (将来のため記録)

- **K1**: xremap 撤去 → Linux convention に統一 (推奨だったが見送り)
- **K2**: キーボードファーム (QMK/VIA) で物理層スワップ
- **K3**: 各アプリで Super+C を手動バインド
- **K4**: kanata に移行 (Wayland 対応の代替)
- **K5**: 現状維持

### 既知のリスク

- xremap がアプリ識別失敗で全アプリにスワップ適用されてる可能性あり
- もし Vivaldi/Obsidian で Ctrl+C/V が効かないと感じたらこの問題
- 動作確認: `systemctl --user status xremap` で xremap が走っているか確認、適宜停止して再検証

### 再開時の起点

- CLAUDE.md の「キーバインド方針」セクション
- まず「現状本当に壊れているか」をリプロして確認 → K1 が筆頭候補

---

## L. ノート/PKM → pandoc のみ追加

**決定**: 既存ツール (obsidian + obsidian-cli + electron + calibre + raindrop-to-daily) は全て維持。CLI 経路は obsidian-cli で充足しているので zk は見送り。pandoc のみ追加。

### 追加

| ツール | 用途 |
|---|---|
| **pandoc** | 文書形式変換 (MD ↔ HTML/PDF/docx 等)。calibre / Obsidian export / 将来の typst 連携時に効く |

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/cli/tools.nix の home.packages に追加
#   pandoc       # 文書形式変換

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

pandoc --version
```

### コミットメッセージ案

```
feat(pkm): pandoc を追加

Markdown ↔ HTML/PDF/docx 等の文書変換用。
```

### 完了条件

- [ ] tools.nix に pandoc を追加
- [ ] `pandoc --version` で動作確認

### 将来候補メモ

- **typst** — PDF 綺麗出力が必要になった日
- **marp-cli** — Markdown → スライドの日
- **zk** — Obsidian なしで headless に MD を扱いたくなった日

---

## M. AI/LLM → aider 追加 + bonsai 再挑戦

**決定**: 既存ツール (claude-code / todoist-mcp-server / rtk / bonsai) は維持。aider を追加。bonsai は再検証して撤去を判断する暫定状態。

### 追加

| ツール | 用途 |
|---|---|
| **aider** | ターミナル pair programming。Claude Code とは別アプローチでファイル単位 LLM 編集 |

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/ai/aider.nix を新規作成:
#   { pkgs, ... }: {
#     home.packages = [ pkgs.aider-chat ];
#   }

# home/home.nix の imports に追加
#   ./modules/ai/aider.nix

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# 動作確認 (既存 sops の DEEPSEEK_API_KEY を流用)
aider --model deepseek/deepseek-chat
```

### コミットメッセージ案

```
feat(ai): aider を追加

ターミナル内で git aware なファイル単位 LLM 編集を行うツール。
既存の sops 由来 DEEPSEEK/OPENAI トークンで起動可能。
```

### 完了条件

- [ ] `home/modules/ai/aider.nix` 作成
- [ ] `home.nix` の imports に追加
- [ ] `aider --version` で動作確認

### 後日タスク

- [ ] **bonsai 再挑戦** — 動作確認しなおして使い道見えなければ撤去 (`prismml-llama-cpp` 独自フォーク + npmDepsHash の維持コストが消える)
- [ ] **MCP サーバ棚卸し** — `claude mcp list` 等で他に動いてる MCP がないか確認、あれば mcp.nix に集約候補
- [ ] **`anthropic_api_key` の sops 化** — aider で Claude を使いたくなった日に
  - sops で secrets.yaml に追記 → sops.nix に登録 → zsh.nix で export 追加

---

## N. メディア変換 → exiftool + gallery-dl 追加

**決定**: ffmpeg / imagemagick / yt-dlp は維持。immich → Obsidian ワークフロー支援に exiftool、画像ギャラリー収集に gallery-dl を追加。

### 追加

| ツール | 用途 |
|---|---|
| **exiftool** | EXIF/メタデータ管理。immich 由来写真を Obsidian に入れる前の GPS 削除等 |
| **gallery-dl** | 画像ギャラリーサイト (Twitter/Pixiv 等) からの一括ダウンロード |

### 作業手順

```bash
cd ~/.dotfiles

# home/modules/cli/tools.nix の home.packages に追加
#   exiftool      # EXIF/メタデータ管理
#   gallery-dl    # 画像ギャラリーサイトからの一括ダウンロード

nix flake check ~/.dotfiles
home-manager build --flake ~/.dotfiles#morikawa@nixos
nh home switch

# 動作確認
exiftool -ver
gallery-dl --version
```

### コミットメッセージ案

```
feat(media): exiftool と gallery-dl を追加

- exiftool: immich 由来写真を Obsidian に入れる前の EXIF 削除等
- gallery-dl: 画像ギャラリーサイトの一括 DL (yt-dlp の画像版)
```

### 完了条件

- [ ] tools.nix に exiftool, gallery-dl を追加
- [ ] `exiftool -ver` で動作確認
- [ ] `gallery-dl --version` で動作確認

### immich → Obsidian Tips (将来スクリプト化候補)

EXIF 安全化の運用例:

```bash
# 単一
exiftool -all= photo.jpg
# 一括
exiftool -all= -overwrite_original /path/to/photos/
# 確認 (削除前)
exiftool -GPSLatitude -GPSLongitude photo.jpg
```

将来 `tools.nix` に `immich-to-obsidian` という writeShellScriptBin として組み込み可能 (raindrop-to-daily の流儀)。

### 将来候補メモ

- **oxipng / jpegoptim** — Web 出し画像最適化が必要になった日
- **monolith** — Web ページ→1HTML 保存
- **mat2** — メタデータ匿名化 (exiftool で代用可能なので優先度低)

---

## O. フォント → 現状維持 (migu 検証は見送り)

**決定**: migu を含む現在のフォント構成は維持。Steam webhelper の CJK 描画問題は今のところ症状なしまたは未確認のため、migu 撤去テストは行わない。

### 小さな掃除候補 (任意・低リスク)

#### タイポ修正

`nixos/modules/desktop/desktop.nix:50` の `sansSerif` で:

```nix
sansSerif = ["Noto Sans CJK JP" "Noto ColorEmoji"];   # ← タイポ
# →
sansSerif = ["Noto Sans CJK JP" "Noto Color Emoji"];  # 半角スペース付き
```

他の項目 (`serif`, `monospace`, `emoji`) は正しく `"Noto Color Emoji"` になっている。
これだけ揃ってないので、いつか直すと精神衛生上良い。

### 将来検証メモ

- 新しい Steam バージョンで CJK 描画が改善している可能性あり
- 日本語ゲーム名が豆腐化していないなら **migu 撤去テスト** の好機 (1分で検証可能):
  1. `desktop.nix` で migu と localConf を一時削除
  2. `nh os switch && pkill -f steamwebhelper && steam`
  3. ライブラリ・ストア・設定で日本語表示確認
  4. 問題なければ撤去確定

### 将来候補メモ

- **UDEV Gothic NF** / **PlemolJP NF** — JetBrainsMono + CJK 合成フォント。導入すれば Ghostty の `font-codepoint-map` 行が不要になる (設定スッキリ化)
- ただし現状の Ghostty CJK 表示で困っていないなら無理に乗り換える必要なし

---

## 各項目共通の手順

```bash
# 編集後 必ず flake check
nix flake check /home/morikawa/.dotfiles

# dry-run で適用前確認
nh os switch --dry          # システム側
home-manager build --flake /home/morikawa/.dotfiles#morikawa@nixos  # home側

# 本適用
nh os switch
nh home switch
```
