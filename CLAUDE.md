# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

Nix Flakes で管理された NixOS + Home Manager のdotfilesリポジトリ。従来のインストールスクリプトはなく、すべて宣言的なNixで記述されている。

## 設定の適用

`nh` コマンドで適用する（`NH_FLAKE` は `programs.nh` で `/home/morikawa/.dotfiles` に設定済み）。

```bash
# NixOSシステム設定を適用
nh os switch        # または nos

# Home Managerユーザー設定を適用
nh home switch      # または nhs
```

直接叩く場合（フォールバック用）：

```bash
sudo nixos-rebuild switch --flake /home/morikawa/.dotfiles#nixos
home-manager switch --flake /home/morikawa/.dotfiles#morikawa@nixos
```

## アーキテクチャ

リポジトリは2つの設定ツリーに分かれている：

- **`nixos/`** — システムレベル（root）の設定
  - `hosts/ser7/` — ハードウェアおよびホスト固有の設定（唯一のホスト）
  - `modules/system/` — ネットワーク、ユーザー、ロケール、シークレット（sops-nix）
  - `modules/desktop/` — デスクトップポータルとシステムレベルのデスクトップ設定

- **`home/`** — Home Manager によるユーザーレベルの設定
  - `home.nix` — エントリーポイント。全homeモジュールをimport
  - `modules/ai/` — Claude Code の設定
  - `modules/cli/` — Git、Neovim（LazyVim）、sheldon（zshプラグイン）、yazi
  - `modules/desktop/` — Niri（Wayland WM）、Ghostty、GTK、アプリ設定
  - `modules/nas/` — Ugreen NAS 連携クライアントツール（immich-go など）
  - `modules/programs/` — ブラウザ
  - `modules/shell/` — Zshのエイリアス、ヒストリ設定

## テスト

設定を変更したあとは必ず以下を実行してビルドエラーがないか確認する。

```bash
# Flake全体の構文・依存関係チェック（ビルドは行わない）
nix flake check /home/morikawa/.dotfiles

# NixOSシステム設定のdry-run（実際には切り替えない）
nh os switch --dry   # または sudo nixos-rebuild dry-build --flake /home/morikawa/.dotfiles#nixos

# Home Manager設定のdry-run
home-manager build --flake /home/morikawa/.dotfiles#morikawa@nixos
```

`nix flake check` はモジュールの型チェックや未定義オプションの検出もするため、`switch` 前に必ず通す。

## 重要なパターン

**Neovimの設定**は `home/modules/cli/nvim/` に実ファイルとして置かれ、`mkOutOfStoreSymlink` で `~/.config/nvim` にシンボリックリンクされている（Nixストアにコピーされない）。そのため編集はリビルドなしに即反映される。

**シークレット**はSOPS + ageキーで管理（`.sops.yaml` 参照）。暗号化済みファイルは `nixos/hosts/ser7/secrets/*.yaml` にあり、実行時に `/run/secrets/` へ復号される。

**Flakeの依存関係**（nixpkgs-unstable、home-manager、niri-flake、noctalia-shell、sops-nix、claude-code-nix等）はすべてpinされている。更新は `nix flake update`。

**シェルエイリアス**でよく使うコマンドを置き換えている：`cat`→`bat`、`grep`→`rg`、`ls`/`ll`/`la`→`eza`系、`cd`→`zoxide`。

**yazi プラグイン**を追加・編集するときは既存プラグイン（`chmod.yazi/main.lua` 等）と公式ドキュメントを先に読む。`cx.active` は `ya.sync()` 内でしか使えない。blocking TUI は `ya.mgr_emit("shell", { cmd, block = true })`。新しい Lua ファイルは `git add` しないと Nix store に入らない。

## キーバインド方針

**物理キーボードに CapsLock キーはない**。CapsLock を修飾キーとして転用する手法は使わない。

**目標**: **Mac / Windows / Linux で同一の物理キーボードを使い、同じ物理キー → 同じ操作**を全 OS で成立させる（環境ごとに操作が異なるのは不可）。物理キーの意味付けは固定済み:

- **物理 Ctrl 位置キー = アプリ修飾**（copy/paste/tab 等。Mac では Cmd）
- **物理 Win 位置キー = Super = Unix Control**（シェル制御コード。SIGINT 等）
- Mac 側は Karabiner で発火を固定済み。キーボードは QMK/VIA。

**構造的な核心**: Mac は (Cmd vs Control) で app 修飾と Unix-ctrl を別キーに分離できるが、Win/Linux には Cmd が無く app 修飾 = Control に落ちる。よって物理 Ctrl キーは「**ターミナルでは Super 相当**（ghostty が Super-C=copy）／**GUI では Control 相当**（ブラウザ Ctrl-C=copy）」と**文脈で別キーコードを出す必要**がある。これは firmware では原理的に不可能（フォーカス中アプリを知らない）で、**compositor 側のアプリ検出付き remap が必須**。

**解ける見込みあり（旧「未解決」を更新）**: 旧記述の「Niri は `ext-foreign-toplevel-list-v1` なので xremap (`wlr-foreign-toplevel-management`) のアプリ検出が効かない」は古い。**xremap は現在 Niri ネイティブ対応（`NIRI_SOCKET` でアプリ検出）**。これにより `application.not`/`only` が Niri で機能するなら、文脈出し分けが成立する。

**確定した構成**（役割分離）:

| 層 | 役割 | 中身 |
|---|---|---|
| QMK firmware | OS 横断の静的正規化 | 物理 Ctrl位置→**Super(LGUI)** / 物理 Win位置→**Control(LCtrl)**。別キーコードに分けるのが肝。Mac は Karabiner で Cmd/Control |
| ghostty | ターミナルの app 修飾 | Super=copy/paste/tab（設定済み）。Control は素通り=SIGINT |
| xremap (niri feature) | GUI だけの文脈例外 | `Super→Control` を `application.not: ghostty` で。GUI は物理 Ctrl でネイティブ copy、ターミナルは除外で ghostty の Super を温存 |
| Niri | WM | `mod-key = "Alt"` なので全修飾に無干渉 |

→ 物理 Ctrl = copy/app 修飾（ターミナルも GUI も）、物理 Win = Unix Control、が Mac と完全一致（Shift 差なし）。

**唯一の実証ポイント**: xremap の niri feature は nix-flake で "implemented, not tested" 扱い。**Niri 上で `application.not`/`only` が実際に効くか**を ser7 で実証する必要（`NIRI_SOCKET` 込みで `pkgs.xremap` を niri ビルドに替え、ghostty とブラウザで挙動確認）。通れば全部繋がる。通らなければ keyd 等のアプリ検出付き remap にフォールバック検討。

**現状の `home/modules/desktop/xremap.nix`** は `application.only: ghostty` で Ctrl↔Super を全アプリにスワップしてしまう旧構成（wlroots ビルドで Niri 検出不可のため leak）。上記構成へ:
- firmware が物理 Ctrl→Super を出す前提に変更（xremap でのスワップは廃止）
- xremap は niri feature ビルドに替え、modmap を `Super→Control` + `application.not: ghostty` に書き換え
