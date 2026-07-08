ギャップと指摘 — 重要度順

1. hermes 自身を見張るものがいない
 ntfy は「hermes が異常を検知して通知する」向きですが、hermes 自身が死んだときは誰も通知しません。Restart=on-failure はありますが、StartLimit 到達で諦めたら無音で止まります。NAS 分析で出た「止まっても気づかない」構造がそのまま hermes に当てはまります。borg で使っている OnFailure= → 通知のパターンを hermes-discord / hermes-webui ユニットに移植して ntfy に流すのが最小手です（数行で済みます）。

2. NAS 操作能力と web 取り込みの組み合わせが攻撃面になっている
 今の hermes は「exa/firecrawl で外部コンテンツを読む」×「シェル + NAS 操作」を同時に持っています。プロンプトインジェクション（読んだ web ページが指示を偽装する）が成立すると被害半径が NAS 全体に及びます。特にメインモデルが DeepSeek flash という軽量級なので、指示偽装への耐性は高くない前提で設計すべきです。対策の方向は能力側の制限で、NAS へ渡す ssh 鍵を専用ユーザー + command= 制限にする、あるいは破壊系操作（down -v、ボリューム削除、restic 系）だけ承認必須にする、など。approval.py に自前パッチを当てているくらいなので、この延長で仕込めるはずです。

3. シークレットが増える一方で二体系のまま（P9 未解決）
 codex / DeepSeek / Anthropic とキーが増えていますが、Discord token だけ SOPS で残りは ~/.hermes/.env 平文のままです。ユビキタス化 = キーがさらに増える方向なので、SOPS から .env を生成する形に早めに一本化しておくと後が楽です。

4. 「生活サポート」への実体はまだ細い
 現状の hermes のツール面は シェル + web 検索 + NAS 操作で、生活データへの接続がまだありません。一方で素材はすでに揃っています: Todoist（MCP wrapper 済み、ただし Claude Code 用）、カレンダー（vdirsyncer/khal）、Miniflux/iris-news（フィード）、Paperless（書類）、Immich(写真)。ユビキタス化の本丸は新コンポーネントの追加ではなく、この既存資産を hermes のツールとして配線することです。順序をつけるなら Todoist + カレンダーが最初（「今日何やるんだっけ」に答えられるようになる）で、これは todoist-mcp-server の流用でコストが小さいです。

5. 小さめの留意点
 - DeepSeek flash に個人データが渡る: memories/state.db の内容がプロンプト経由で DeepSeek の API に流れます。生活データが濃くなるほど効いてくるので、「生活系の文脈は codex/GPT 側、使い捨てタスクは DeepSeek」のようなモデル振り分けは意識しておく価値があります
 - 非公式 2 フロントの維持費: hermes-webui は rev 固定 + 書き込み可能領域へのコピー運用、herdr は自前パッチ持ちで、どちらも upstream 更新のたびに手がかかります。研究段階の今は両輪でよく、どちらが日常に残るか使用実績で決めれば十分です
 - safe-tmp-deletes パッチ（P8）: 105 行を flake input に当て続けるのは更新ごとの衝突リスクなので、upstream に PR を出せるならそれが最安です
