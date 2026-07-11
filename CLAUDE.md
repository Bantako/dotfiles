# CLAUDE.md

Nix Flakes で管理された NixOS + Home Manager のdotfiles。`nh os switch` / `nh home switch` で適用。

## アーキテクチャ

- `nixos/` — システムレベル設定（hosts/ser7/, modules/system/, modules/desktop/）
- `home/` — Home Manager設定（home.nix がエントリポイント）

## 重要なパターン

**Neovim** は `mkOutOfStoreSymlink` で `~/.config/nvim` にリンク。Nixストアに入らないためリビルド不要で即反映。

**シークレット** は SOPS + age キー管理。`nixos/hosts/ser7/secrets/*.yaml` → 実行時 `/run/secrets/` へ復号。

**シェルエイリアス**: `cat`→`bat`、`grep`→`rg`、`ls`/`ll`/`la`→`eza`、`cd`→`zoxide`。

**yazi プラグイン**: `cx.active` は `ya.sync()` 内のみ有効。blocking TUI は `ya.mgr_emit("shell", { cmd, block = true })`。新規 Lua ファイルは `git add` 必須（Nix store に入らないため）。

## NAS

`ssh nas`（192.168.11.9）。git 未インストールのため compose 管理は Docker 経由（`nas-git` コマンド）。ser7 の CIFS マウント `/mnt/ugreen` は SSH の `~/services` / `~/data` とは別パスなので NAS 上のファイル操作は `ssh nas` 経由で行う。

## キーバインド方針

物理 Ctrl = アプリ修飾（Mac では Cmd）、物理 Win = Super = Unix Control。全 OS で同一物理キー → 同一操作が目標。

**未解決**: xremap は evdev レベル（コンポジター以前）で動作するため、ghostty フォーカス中の Ctrl↔Super スワップが Niri のスクリーンショットショートカット（Ctrl+Shift+3/4/5）を壊す。
