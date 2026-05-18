# borgbackup 導入プラン

ser7 (NixOS, 唯一のホスト) → UGreen NAS (`/mnt/ugreen`) へのスナップショットバックアップを `services.borgbackup` で構築するための設計メモ。
`docs/improvement-plan.md` の「未着手 P0」に書いてある borgbackup を、現状認識を踏まえて具体化する。

---

## 1. 何を守る/守らないかの基本方針

### 設定・パッケージは守らない（既に守られている）

| カテゴリ | どこで永続化 | 復旧コマンド |
|---|---|---|
| dotfiles・設定 | `~/.dotfiles` → GitHub | `git clone` |
| パッケージ選択 | `flake.nix` + `flake.lock` | `nh os switch && nh home switch` |
| Home Manager 配下の `~/.config/*` | HM が宣言的に生成 | `nh home switch` |
| Nix Store | substituter から再取得 | 自動 |
| 暗号化済み secrets ファイル | git に乗っている | `git pull` |

→ borg の対象に**含めない**。

### データ層は守る（Nix では復元不可）

「環境引っ越しを繰り返してきた経験から、可搬性のないものはそもそも持っていない」という現状認識のもと、守る対象は思ったより小さい。

---

## 2. 守る対象（Tier 分け）

### Tier 1: 失うと復旧不可（必ず守る）

| パス | 内容 | サイズ感 |
|---|---|---|
| **age 秘密鍵** | sops の復号鍵。これが無いと暗号化済み secrets が全部死ぬ | 数 KB |
| `~/.ssh/` | GitHub・他マシン・NAS への鍵 | ~10 KB |
| `~/.gnupg/` | GPG 鍵 | ~MB |
| **Obsidian vault** | PKM。手書きの知識は再生成不可。**ローカル管理が決定済み** | 数百 MB〜数 GB |
| **~/Assets**（新規）| アイコン・素材ストック。詳細は §4 | 要確認 |

### Tier 2: 失うと痛いが時間で復旧可能

| パス | 備考 |
|---|---|
| `~/Documents` | テキスト中心。`Documents` 配下に vault がある場合は Tier 1 と統合 |
| `~/.local/share/*` | アプリ固有データ（Telegram 履歴、Signal DB 等）を面でカバー |

### Tier 3: 守らない（明示）

| 対象 | 理由 |
|---|---|
| 未 push の git 作業 | **ポリシーで除外。push してないものは存在しないものとして扱う** |
| ブラウザ設定 (Vivaldi/Zen) | クラウド sync で逃している |
| パスワード | Bitwarden |
| `~/Pictures` の写真・スクショ | **Immich (NAS) が一次保存**。§4 でディレクトリ分離する |
| Steam ライブラリ | 再 DL 可 |
| `~/.cache`、`~/.local/share/Trash` | キャッシュ・ゴミ箱 |
| `Downloads/` | 再 DL 可 |
| ビルド成果物 (`node_modules` / `target` / `.venv` / `dist`) | 再生成可 |

---

## 3. NAS データ自体は borg では守れない（重要）

`repo = /mnt/ugreen/borg/ser7` は **ser7 → NAS の片方向**。

- NAS の HDD が死ぬと、borg リポジトリも Immich 写真も Paperless 文書も**同時に全滅**
- borg は「ser7 のローカル消失」には強いが、「NAS 消失」には**完全に無力**

→ NAS のデータを守る層は別途必要（本プランのスコープ外、`improvement-plan.md` の将来候補:）

| 候補 | 役割 |
|---|---|
| UGreen 内蔵スナップショット | NAS 機種が対応していれば最低限の誤削除復旧用 |
| **rclone で NAS → Backblaze B2 等** | オフサイトミラー。安価 |
| borg の方向反転 (NAS → ser7) | ser7 ストレージに余裕があれば |

**現状の冗長度は 1**。borg を入れても NAS データの冗長度は変わらない。これは別タスクとして認識しておく。

---

## 4. `~/Pictures` のディレクトリ規約変更（前提作業）

### 現状の問題

`~/Pictures` が 2 役を兼用している：

```
~/Pictures/
├── スクショ・写真   ← immich-go で NAS へ流す（一時置き）
└── アイコン・素材   ← 作業用ストック（永続ローカル）
```

そのままだと:
- immich-go が素材まで誤アップロードするリスク
- borg の include/exclude を素材だけに絞れない

### 採用方針（案A）

ディレクトリで責務分離する：

```
~/Pictures/         ← immich-go の対象。アップロード後は削除する一時置き場
~/Assets/           ← 永続ローカル。アイコン・素材。borg の対象
```

- immich-go は `~/Pictures` だけ見る
- borg は `~/Assets` を含める、`~/Pictures` は除外
- アップロード規律: immich-go の `--delete` で自動削除、または `~/Pictures/inbox/` 規約で「アップロード後は inbox から消える」運用

### サイズ確認後の代替案（案B）

`~/Pictures` 内の写真と素材を分離するのが面倒すぎる場合は、`~/Pictures` 丸ごと borg に乗せて Immich と二重保管を許容する。素材が数百 MB 未満なら気にならない。

---

## 5. 暫定の borg 設定（机上案）

```nix
# nixos/modules/system/backup.nix（新規）
{ config, ... }:
{
  services.borgbackup.jobs.home = {
    paths = [
      "/home/morikawa/.ssh"
      "/home/morikawa/.gnupg"
      "/home/morikawa/.config/sops"     # age 鍵がここなら（§6 で確認）
      "/home/morikawa/Documents"        # Obsidian vault が中にあるなら一網打尽
      "/home/morikawa/Assets"           # §4 で新設
      "/home/morikawa/.local/share"     # アプリ固有データを面でカバー
    ];
    exclude = [
      "**/.cache"
      "**/Steam"
      "**/node_modules"
      "**/target"
      "**/.venv"
      "**/dist"
      "**/Trash"
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

### NAS マウント依存（重要）

`/mnt/ugreen` がマウントされる前に borg ジョブが走ると失敗する。systemd 側で依存を明示する必要がある：

```nix
systemd.services.borgbackup-job-home = {
  requires = [ "mnt-ugreen.mount" ];
  after = [ "mnt-ugreen.mount" ];
};
```

（`/mnt/ugreen` を fstab/systemd.mounts どちらで定義しているか実機で確認する）

---

## 6. 次回マシン作業時の確認コマンド

paths/exclude を確定する前に、以下を実機で取る。

```bash
# 1. age 秘密鍵のパス確定（最重要）
find ~ -name "keys.txt" -path "*sops*" 2>/dev/null
find ~ -name "*.txt" -path "*age*" 2>/dev/null
sudo find /var/lib/sops* /etc/sops* 2>/dev/null

# 2. Obsidian vault の実パス
find ~ -maxdepth 5 -name ".obsidian" -type d 2>/dev/null

# 3. ~/Pictures の中身とサイズ（§4 案A/B 判断材料）
du -sh ~/Pictures
du -sh ~/Pictures/* 2>/dev/null | sort -h
ls ~/Pictures

# 4. アプリ固有データの顔ぶれとサイズ
du -sh ~/.local/share/* 2>/dev/null | sort -h
du -sh ~/.local/state/* 2>/dev/null | sort -h

# 5. システム側に永続データを置いてるアプリがあるか
sudo du -sh /var/lib/* 2>/dev/null | sort -h

# 6. NAS マウント方式の確認
cat /etc/fstab | grep ugreen
systemctl list-units --type=mount | grep ugreen
mount | grep ugreen

# 7. immich-go の現運用（--delete 使ってるか等）
grep -r "immich-go" ~/.dotfiles/ 2>/dev/null
which immich-go && immich-go --help 2>&1 | head -30
```

### 取った結果から確定する項目

- [ ] age 鍵のパス → §5 の `paths` に確実に入れる
- [ ] Obsidian vault が `~/Documents/` 内 / `~/Obsidian/` / 他 のどれか
- [ ] `~/Pictures` のサイズと内訳 → §4 案A or 案B 確定
- [ ] `~/.local/share` の中で巨大かつ不要なディレクトリ → `exclude` に追加
- [ ] `/var/lib/` に守るべきものが居るか（普通は無いはず）
- [ ] `/mnt/ugreen` のマウント名 → systemd 依存の `requires` に書く正式名

---

## 7. 実装ステップ

### Step 1: 前提作業

1. **age 鍵のバックアップを物理的に別の場所にも置く**（紙印刷 or 別ストレージ）
   - これだけは borg では守れない（borg を復号するのに age 鍵が必要、という鶏卵）
2. **`~/Assets` ディレクトリ作成**（§4）、素材を `~/Pictures` から移動
3. **immich-go の運用見直し** — `--delete` か `inbox/` 規約か決める

### Step 2: sops に borg passphrase を追加

paperless_token を追加した時と同じパターン：

```bash
# 1. パスフレーズ生成
openssl rand -base64 32

# 2. secrets.yaml に追加
sops nixos/hosts/ser7/secrets/secrets.yaml
# borg_passphrase: <生成したやつ> を追記

# 3. nixos/modules/system/sops.nix に borg_passphrase エントリを追加
```

### Step 3: NAS 側に borg リポジトリ初期化

```bash
# /mnt/ugreen が読み書き可能になっていることを確認
ls /mnt/ugreen/

# borg リポジトリ作成（初回のみ手動）
mkdir -p /mnt/ugreen/borg
BORG_PASSPHRASE="$(cat /run/secrets/borg_passphrase)" \
  borg init --encryption=repokey-blake2 /mnt/ugreen/borg/ser7
```

### Step 4: NixOS モジュール追加

`nixos/modules/system/backup.nix` を §5 の内容で新規作成し、`nixos/hosts/ser7/default.nix` でインポート。
systemd の `requires`/`after` でマウント依存を入れる。

### Step 5: 動作確認

```bash
# dry-run
nh os switch --dry

# 適用
nh os switch

# 即時実行
systemctl start borgbackup-job-home

# ジャーナル確認
journalctl -u borgbackup-job-home -f

# リポジトリ内容確認
BORG_PASSPHRASE="$(cat /run/secrets/borg_passphrase)" \
  borg list /mnt/ugreen/borg/ser7
```

### Step 6: 復元テスト（**必須**）

「動いてるつもり」を避けるため、最低 1 回は復元する：

```bash
# 適当なディレクトリで
mkdir /tmp/borg-restore-test && cd /tmp/borg-restore-test

# 最新スナップショットから .ssh/config を 1 個だけ取り出す
BORG_PASSPHRASE="$(cat /run/secrets/borg_passphrase)" \
  borg extract /mnt/ugreen/borg/ser7::<snapshot名> home/morikawa/.ssh/config

# 中身が現物と一致しているか diff
diff /tmp/borg-restore-test/home/morikawa/.ssh/config ~/.ssh/config
```

### Step 7: improvement-plan.md 更新

完了テーブルに行を追加：

```
| **borgbackup** | `~/.ssh` `~/.gnupg` `~/Documents` `~/Assets` `~/.local/share` を NAS にスナップショット |
```

---

## 8. このプランのオープン項目

- [ ] age 鍵の物理オフライン保管をどうするか（紙 / USB / 別マシン）
- [ ] NAS のオフサイトミラー (rclone → B2 等) — 別タスク、`improvement-plan.md` で追跡
- [ ] immich-go の `--delete` を使うか `inbox/` 規約にするか
- [ ] `~/Documents` 内に vault がある場合の exclude（vault 内の `.obsidian/workspace*.json` 等は不要かも）
