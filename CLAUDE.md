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

## NAS 操作

**接続**: `ssh nas`（`192.168.0.222`、ユーザー `morikawa`、鍵認証済み）

**ディレクトリ構造**（NAS 上 `~/`）:
- `~/data/` — コンテンツ（music / photos / adult / books / documents / games / media / pictures / projects）
- `~/services/` — compose スタック（calibre / homepage / immich / lanraragi / navidrome / ntfy / paperless / stash）

**コンテナ管理**:
```bash
lzd   # DOCKER_HOST=ssh://nas lazydocker（NAS コンテナの TUI 管理）
```

**compose の git 管理**（NAS に git が未インストールのため Docker 経由）:
```bash
nas-git status
nas-git log --oneline
nas-git diff
# commit はメッセージに空白が入るため ssh 直接入力を推奨
ssh nas "docker run --rm --user \$(id -u):\$(id -g) --entrypoint sh \
  -v /home/morikawa/services:/repo -w /repo alpine/git \
  -c 'git commit -m \"message\"'"
```

`.gitignore` は allowlist 方式（全無視 → compose ファイルのみ許可）。`.env` は原理的に追跡されない。

**重要**: ser7 の CIFS マウント `/mnt/ugreen` は `personal_folder` 共有で、SSH の `~/services` / `~/data` とは**別パス**。ser7 からマウント越しに `~/services` は触れない。NAS 上のファイル操作は必ず `ssh nas` 経由。

## キーバインド方針

**物理キーボードに CapsLock キーはない**。CapsLock を修飾キーとして転用する手法は使わない。

**目標**: **Mac / Windows / Linux で同一の物理キーボードを使い、同じ物理キー → 同じ操作**を全 OS で成立させる（環境ごとに操作が異なるのは不可）。物理キーの意味付けは固定済み:

- **物理 Ctrl 位置キー = アプリ修飾**（copy/paste/tab 等。Mac では Cmd）
- **物理 Win 位置キー = Super = Unix Control**（シェル制御コード。SIGINT 等）
- Mac 側は Karabiner で発火を固定済み。キーボードは QMK/VIA。

**構造的な核心**: Mac は (Cmd vs Control) で app 修飾と Unix-ctrl を別キーに分離できるが、Win/Linux には Cmd が無く app 修飾 = Control に落ちる。よって物理 Ctrl キーは「**ターミナルでは Super 相当**（ghostty が Super-C=copy）／**GUI では Control 相当**（ブラウザ Ctrl-C=copy）」と**文脈で別キーコードを出す必要**がある。これは firmware では原理的に不可能（フォーカス中アプリを知らない）。xremap 等の remap ツールはアプリ検出できるが、evdev レベル（コンポジター以前）で動作するため compositor のショートカットも影響を受ける。完全な解決策は未発見。

**既知の問題（未解決）**: xremap は evdev レベル（コンポジター以前）でキーを書き換えるため、ghostty フォーカス中の Ctrl↔Super スワップが Niri の `Ctrl+Shift+3/4/5`（スクリーンショット）ショートカットを壊す。「アプリ側だけ制御」は xremap では原理的に不可能。解決策は検討したが現状は手つかず。
