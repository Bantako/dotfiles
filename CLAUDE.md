# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 概要

Nix Flakes で管理された NixOS + Home Manager のdotfilesリポジトリ。従来のインストールスクリプトはなく、すべて宣言的なNixで記述されている。

## 設定の適用

```bash
# NixOSシステム設定を適用
sudo nixos-rebuild switch --flake /home/morikawa/.dotfiles#myNixOS

# Home Managerユーザー設定を適用
home-manager switch --flake /home/morikawa/.dotfiles#myHome
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

## 重要なパターン

**Neovimの設定**は `home/modules/cli/nvim/` に実ファイルとして置かれ、`mkOutOfStoreSymlink` で `~/.config/nvim` にシンボリックリンクされている（Nixストアにコピーされない）。そのため編集はリビルドなしに即反映される。

**シークレット**はSOPS + ageキーで管理（`.sops.yaml` 参照）。暗号化済みファイルは `nixos/hosts/ser7/secrets/*.yaml` にあり、実行時に `/run/secrets/` へ復号される。

**Flakeの依存関係**（nixpkgs-unstable、home-manager、niri-flake、noctalia-shell、sops-nix、claude-code-nix等）はすべてpinされている。更新は `nix flake update`。

**シェルエイリアス**でよく使うコマンドを置き換えている：`cat`→`bat`、`grep`→`rg`、`ls`/`ll`/`la`→`eza`系、`cd`→`zoxide`。
