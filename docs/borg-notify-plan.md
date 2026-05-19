# borgbackup ジョブ失敗通知プラン

`30244d1 feat(system): borgbackup を追加` で `/mnt/ugreen/borg/ser7` への日次バックアップを入れたが、
**ジョブが失敗した時にそれを知る経路がない**。NAS が落ちてた / passphrase が読めなかった /
mount unit が遅延した日に静かに失敗してサイレントデータロス候補になる。

このファイルは Mac 側で書いた設計メモ。家のマシン (ser7) で取り込み・実装する。

---

## 現状の前提（リポを確認した結果）

| 項目 | 状態 |
|---|---|
| borgbackup unit 名 | `borgbackup-job-home.service`（attrset key が `home`） |
| repo mount | `mnt-ugreen.mount` を `requires` + `after` で順序保証済 |
| 通知デーモン | **noctalia が libnotify をホスト**（`home/modules/desktop/noctalia.nix` 冒頭コメント）。mako/dunst は不要 |
| ntfy / healthchecks / OnFailure | **リポ内に既存実装ゼロ**（grep で確認） |
| Tailscale | 既に CGNAT 帯 `100.64.0.0/10` を fail2ban で扱う設定があり、デバイス間 push の素地はある |

---

## 通知経路の選択肢

| 案 | 即時性 | 「実行されてない」を検知 | 外部依存 | 実装コスト | コメント |
|---|---|---|---|---|---|
| **A** systemd OnFailure → noctalia (libnotify) | ◎ デスクトップで即座 | ✕（マシン稼働中限定） | なし | 小 | デスクのときだけ見える。root→user セッション越境が要注意 |
| **B** OnFailure → curl ntfy.sh | ◎ スマホまで届く | ✕ | ntfy.sh（公開 or 自前） | 小 | 外出中も気づける。トピック URL を sops に入れるだけ |
| **C** ExecStartPost → healthchecks.io heartbeat | △ 遅延あり（猶予時間後） | **◎ これが本命** | healthchecks.io | 小 | "ping が届かない" を検知。マシン off の日でも気づける |
| **D** OnFailure → ローカル mail (msmtp→Gmail) | △ メール経由 | ✕ | SMTP セットアップ | 中 | smartd 系と統合できるが重め |
| **E** systemd-cat → journal だけ | ✕ 自分で見にいかないと無理 | ✕ | なし | ゼロ | 既存。これだけだと届かない |

### 推奨組み合わせ

**A + C の二段構え**。理由：

- **A**（noctalia 通知）で「**今日のジョブが落ちた**」を即気づける。在宅率が高いマシンなので大半のケースをカバー。
- **C**（healthchecks heartbeat）で「**そもそも実行されてない**」を補完。
  borgbackup は ser7 が off のとき走らない＝失敗イベントすら出ないので、
  A だけだと「マシン off で 5 日連続バックアップが走ってない」に気づけない。
  健康チェックは逆向きの検知（無音 = 異常）なので borgbackup と相性が良い。

B（ntfy）は外出中も気にしたくなった段階で C と置き換える or 追加する。最初は不要。

---

## A: 詳細設計（OnFailure → noctalia）

### 越境問題

`borgbackup-job-home.service` は **system unit (root)**。
noctalia は **user session (morikawa)** で動く。`notify-send` は user DBus に喋るので、
root から直接呼んでも noctalia に届かない。

### 解決パターン（3 つ）

#### パターン 1: `systemd-run --machine=morikawa@.host --user`（推奨）

```nix
# nixos/modules/system/backup.nix の borgbackup ブロックと同ファイル
systemd.services.borg-notify-failure = {
  description = "Notify desktop session of borg failure";
  serviceConfig = {
    Type = "oneshot";
    ExecStart = "${pkgs.systemd}/bin/systemd-run --machine=morikawa@.host --user --collect ${pkgs.libnotify}/bin/notify-send -u critical 'borgbackup failed' 'home job failed at %i'";
  };
};

systemd.services.borgbackup-job-home = {
  # 既存の requires/after は維持
  unitConfig.OnFailure = [ "borg-notify-failure.service" ];
};
```

- `--machine=morikawa@.host` で user session に橋渡し
- `notify-send -u critical` で noctalia に critical 重要度として届く
- `lingering` が有効でないと user session が起きていない瞬間は届かない → 後述

#### パターン 2: 専用 user service を作って system 側からトリガ

`systemd.user.services.borg-notify-failure` を作って、root unit の OnFailure から
`systemctl --machine=morikawa@.host --user start borg-notify-failure.service` を呼ぶ。
パターン 1 より明示的だが unit が増える。

#### パターン 3: wall + journal だけにする

cron mail スタイル。シンプルだが見落とす。**却下**。

### 推奨：パターン 1

最小行数で済み、libnotify → noctalia 経由が標準ルート。

### 副次的にいる設定

```nix
# users.users.morikawa あたりに（未設定なら）
users.users.morikawa.linger = true;
```

→ `loginctl enable-linger morikawa` 相当。GUI に未ログインの時間帯（早朝の `startAt = "daily"` 発火）でも user manager が動いていて bridge が届くようになる。**現状の挙動を要確認**（既に linger 済かどうか）。

---

## C: 詳細設計（healthchecks heartbeat）

### コンセプト

- healthchecks.io 側に「daily ping、grace 6h」のチェックを作成 → UUID 発行
- borgbackup ジョブが**成功して終了した時に**`curl https://hc-ping.com/<uuid>` を打つ
- 24h + grace の間に ping が来ないと healthchecks 側がメール / Slack / ntfy で通知

borgbackup ジョブの実行可否そのものを外部から見張る形なので
「machine off で走らなかった」「systemd timer が壊れて起動してない」も拾える。

### 実装

```nix
# nixos/modules/system/backup.nix の services.borgbackup.jobs.home に追記
services.borgbackup.jobs.home = {
  # …既存…
  postHook = ''
    ${pkgs.curl}/bin/curl -fsS --retry 3 \
      "$(cat ${config.sops.secrets.healthchecks_url.path})" \
      > /dev/null
  '';
};
```

- `postHook` は **borg ジョブが成功した時だけ**実行される（NixOS borgbackup モジュールの仕様）
- `preHook` / `failHook` も使えるので、開始通知 / 失敗時の追加処理も書ける
- URL を sops 経由にすれば UUID が repo に露出しない

### sops エントリ追加

```yaml
# nixos/hosts/ser7/secrets/secrets.yaml に追加（暗号化前のキー）
healthchecks_url: https://hc-ping.com/<uuid>
```

```nix
# nixos/modules/system/sops.nix
sops.secrets.healthchecks_url = { mode = "0444"; };
```

`borg_passphrase` と違って owner は root 既定でよい（borgbackup ジョブが root 実行）。
mode は 0444 で誰でも読める（URL なので機微性低い）。

### healthchecks ホスティング

- **公開 SaaS** healthchecks.io 無料プランで 20 check まで持てる → **これで十分**
- 自前ホスト (NAS compose に乗せる) はやり過ぎ。**保留**

---

## 段階導入の手順

実装は **A → C** の順がよい（A の方が依存ゼロで止まりにくい）。

### Phase 1: A だけ入れる（同日中）

1. `nixos/modules/system/backup.nix` に `borg-notify-failure` user service 橋を追加
2. `borgbackup-job-home` に `unitConfig.OnFailure` を追加
3. `users.users.morikawa.linger` を確認 / 必要なら設定
4. **検証**: `systemctl start borg-notify-failure.service` を直接叩いて noctalia に通知が出るか
5. **検証**: borgbackup を一時的に壊して（例: repo パスを存在しないものに）失敗 → 通知が出るか

### Phase 2: C を追加（後日 / 翌週）

1. healthchecks.io アカウント作成、check 作成、UUID 取得
2. `secrets.yaml` に `healthchecks_url` を追加 → re-encrypt
3. `sops.nix` に entry 追加
4. `backup.nix` の `postHook` に curl 追加
5. **検証**: 手動で borgbackup ジョブ起動 → healthchecks ダッシュボードで ping 受領を確認
6. **検証**: 24h 放置で「missed」アラートが届くか

---

## 注意点 / 落とし穴

- `notify-send` の通知に `-u critical` をつけると noctalia は手動で閉じるまで消えない（デフォルト動作）。バックアップ失敗は critical 相当でよい
- `borg-notify-failure.service` は `Type = "oneshot"` にする（systemd-run が即終了するため）
- borgbackup の `postHook` は ジョブ成功時のみ実行。失敗時は `failHook` を別途用意（A で十分なので追加不要）
- 起動直後 / suspend 復帰直後で `mnt-ugreen.mount` がまだ来てない瞬間に発火する事故は既に `requires` でケア済み
- healthchecks の grace は `startAt = "daily"` + α で **6h くらい余裕を持たせる**（depsleep / kernel update でズレることがある）

---

## オープン項目

- [ ] `linger` の現状確認（`loginctl show-user morikawa | grep Linger`）
- [ ] healthchecks.io アカウントを作るか NAS 自前ホストにするか（→ 当面 SaaS 推奨）
- [ ] 通知文面に grow すべき情報（journal 末尾 5 行 / 失敗 unit 名 / NAS reachable かどうか）
- [ ] `borgbackup-job-home` 以外のジョブ（将来追加するなら）にも同じ通知を共有テンプレ化するか
- [ ] **次の話**: borg list / borg check を**月次 systemd timer** で動かして「壊れてないか」も自動検査するか

---

## improvement-plan.md への追記候補（ser7 で取り込み時）

完了済テーブルに追加：

```markdown
| **borgbackup 通知** | OnFailure → noctalia 通知 + healthchecks heartbeat（"動いてない" の検知）|
```

未着手側からは「borgbackup」関連項目を消す（既に完了テーブルに入っている）。
