# dotfiles

NixOS 設定管理リポジトリ。Nix Flakes + Home Manager で管理。

## スタック

- **OS**: NixOS (unstable)
- **WM**: Niri (scrollable-tiling Wayland compositor)
- **ロックスクリーン**: Noctalia (就寝時間スケジューラ連携)
- **ユーザー環境**: Home Manager
- **シークレット**: SOPS + age

## 構成

```
nixos/     — システムレベル設定（hosts/ser7/, modules/system/, modules/desktop/）
home/      — Home Manager 設定（home.nix がエントリポイント）
```

## 適用

```bash
# システム
nh os switch --dry    # 確認
sudo nh os switch      # 適用

# ユーザー環境
nh home switch --dry   # 確認
nh home switch         # 適用
```

シークレットパスを含む一部設定は `--impure` が必要。

## Game Library の更新

Noctalia launcher向けのGame Libraryは、ローカルGitリポジトリ `/home/morikawa/Projects/game-library` のcommitをflake input `game-library`として固定している。Game Library側のworking treeを変更しただけではHome Managerへ反映されない。

Game Libraryの変更を検証・commitした後、dotfiles側のlockを更新し、dry-runを確認してから適用する。

```bash
cd /home/morikawa/Projects/game-library
git status --short
git commit  # 検証済みの変更をstageした後

cd /home/morikawa/.dotfiles
nix flake update game-library
git diff -- flake.lock
nh home switch --dry --impure
nh home switch --impure  # dry-run確認後のみ
```

`game-library` inputはdotfiles側のNixpkgsへ追従させず、Game Library自身のlockを維持する。Python・PySide6・Shiboken6・Qtの検証済みABI境界を保つため。
