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
