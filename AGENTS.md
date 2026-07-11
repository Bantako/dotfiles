# .dotfiles プロジェクトコンテキスト

NixOS + Home Manager を Nix Flakes で管理した dotfiles リポジトリ。

## 適用コマンド

変更後は必ず dry-run で確認してから適用する。

- システム設定の変更後:
  - dry-run: `nh os switch --dry`
  - 適用: `nh os switch`
- Home Manager の変更後:
  - dry-run: `nh home switch --dry`
  - 適用: `nh home switch`

## ディレクトリ構成

- `nixos/` — システムレベル設定（hosts/ser7/, modules/system/, modules/desktop/）
- `home/` — Home Manager 設定（home.nix がエントリポイント）

## 重要なパターン

**Neovim**: `mkOutOfStoreSymlink` で `~/.config/nvim` にリンク。Nix ストアに入らないためリビルド不要で即反映。

**シークレット**: SOPS + age キー管理。`nixos/hosts/ser7/secrets/*.yaml` → 実行時 `/run/secrets/` へ復号。

**シェルエイリアス**: `cat`→`bat`、`grep`→`rg`、`ls`/`ll`/`la`→`eza`、`cd`→`zoxide`。ターミナルコマンド実行時はこのエイリアスが有効。

**yazi プラグイン**: `cx.active` は `ya.sync()` 内のみ有効。blocking TUI は `ya.mgr_emit("shell", { cmd, block = true })`。新規 Lua ファイルは `git add` 必須（Nix store に入らないため）。

## Nix LSP

`nil` を使用（`home/modules/cli/dev.nix`）。Nix ファイル編集時は nil の補完・診断が有効。

## Nix 運用方針

- フォーマッタは `nixfmt`（`nixfmt-rfc-style` ではない）
- LSP は Nix 管理に統一。Neovim の Mason は使わない
- 外部ツール依存は原則 Nix に引き取る方針

## noctalia-shell

就寝時間ロックスケジューラ。`loginctl` ではなく noctalia-shell の IPC 経由でロックする（`bedtime.nix` 参照）。

## NAS

`ssh nas`（192.168.11.9）。git 未インストールのため compose 管理は `nas-git` コマンド経由。ser7 の CIFS マウント `/mnt/ugreen` と SSH の `~/services` / `~/data` は別パス——NAS 上のファイル操作は必ず `ssh nas` 経由で行う。

## キーバインド方針

物理 Ctrl = アプリ修飾、物理 Win = Super = Unix Control。全 OS で同一物理キー → 同一操作が目標。

**未解決**: xremap が evdev レベルで動作するため、ghostty フォーカス中の Ctrl↔Super スワップが Niri のスクリーンショットショートカット（Ctrl+Shift+3/4/5）を壊す。
