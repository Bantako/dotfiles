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
  - `modules/desktop/` — Niri（Wayland WM）、WezTerm、GTK、アプリ設定
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

## キーバインド方針

**物理キーボードに CapsLock キーはない**。CapsLock を修飾キーとして転用する手法は使わない。

**目標**: macOS に近いキーバインド体系。具体的には「アプリショートカット用修飾キー」と「Unix Ctrl（シェル制御コード）用修飾キー」を分離すること。

**現状の問題**: `xremap` で Ctrl↔Super をターミナルアプリ限定でスワップする設定を入れているが、Niri が `ext-foreign-toplevel-list-v1`（標準化プロトコル）を使うのに対し xremap は `wlr-foreign-toplevel-management`（wlroots 専用）でアプリ検出するため、`application.only` フィルタが機能せずスワップが全アプリに適用されてしまう。

**未解決**。ターミナルエミュレータ側で完結させる案（アプリ検出不要）と、Niri IPC を使ったデーモンによる動的制御案がある。
