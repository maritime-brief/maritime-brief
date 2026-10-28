# SHIPSHIFT（シップシフト）

海外の海事当局・事故調査機関などの公開情報から事実だけを取り出し、AIが日本語の短い記事にして、
1日3回自動で更新するニュースサイトです。サーバーは不要です。

## しくみ

| 時刻（日本時間） | 担当 | やること |
| --- | --- | --- |
| 6:40 / 11:40 / 17:40 | GitHub Actions（AIなし） | 許可したソースから新着を集め、`data/queue/` に置く |
| 7:00 / 12:00 / 18:00 | Claudeのスケジュールされたタスク | `CLAUDE_TASK.md` の手順で、選別 → 事実抽出 → 執筆 → 検証 → 保存 |
| 記事が届いた直後 | GitHub Actions | サイトを作り直して公開 |

- 執筆の担当には原文を渡さず、抽出した「事実のリスト」だけを渡します（翻訳にならないための仕組み）。
- 検証で基準を超えた記事は自動公開せず `content/pending/` に保留します。
- 最初は **試験運用モード**（すべての記事が保留）で始まります。
- 記事作成はClaudeのプランの利用枠で行うため、**APIキーやAPI料金は不要**です（`config/settings.yaml` の `engine: api` に切り替えると、Claude API で動かすこともできます）。

---

## はじめての設定

1. GitHub アカウントと、空のリポジトリ `maritime-brief`（Public）を作る
2. claude.ai でGitHubを接続し、Claude GitHub App にこのリポジトリへのアクセスを許可する
3. ファイルの配置と、スケジュールされたタスクの作成はClaudeが行います
4. リポジトリの「Settings」→「Pages」→ Source を **GitHub Actions** にする
5. `config/settings.yaml` の `base_url` と `contact_url` を書き換える

### API方式で動かす場合（任意）

`config/settings.yaml` を `engine: api` にし、[Claude Console](https://console.anthropic.com/) で作ったAPIキーを
「Settings」→「Secrets and variables」→「Actions」に `ANTHROPIC_API_KEY` という名前で登録します。
この場合はGitHub Actionsだけで記事作成まで完結し、AI利用料は月3,000〜5,000円程度です。
Claudeのスケジュールされたタスクは止めてください。

---

## 毎日の運用

### 保留記事を確認して公開する（週2〜3回、10分程度）

1. リポジトリの `content/pending/` を開き、記事ファイルをクリックします。
2. 先頭の `check:` 欄に、保留になった理由が書かれています。本文と出典（`source:` の url）を見比べてください。
3. 鉛筆アイコンで編集し、2行目の
   - `status: pending` → `status: approved` にすると **公開**
   - `status: rejected` にすると **却下**（`content/rejected/` に移動）
4. 「Commit changes」で保存すると、数分でサイトに反映されます。
   本文や見出しを直したいときも、同じ画面で書き換えてから保存すれば反映されます。

### 試験運用から自動公開へ切り替える

1か月ほど試験運用し、保留になる記事が2割以下・事実の誤りがない状態になったら、
`config/settings.yaml` の `mode: trial` を `mode: auto` に書き換えます。
以後、検証に合格した記事は自動で公開され、不合格の記事だけが保留に入ります。

### 誤りの指摘や削除依頼が来たら

- 訂正：記事ファイルを書き換え、`corrections:` に履歴を追加します。
  ```yaml
  corrections:
  - date: "2026-11-02"
    note: "発効日を2027年1月1日から2027年7月1日に訂正しました"
  ```
- 削除：記事ファイルを `content/rejected/` に移動するか、ファイルを削除します。

---

## ソースを追加する

`config/sources.yaml` に項目を足し、`enabled: true` にします。

1. 相手のサイトで **RSS**（オレンジ色のアイコン、または「RSS」「Feed」のリンク）を探し、そのURLを `feed:` に記入します。
2. **利用規約を必ず確認**し、`tier`（1〜3）と `license`、確認日の `license_checked` を書きます。
   - 再利用が明示的に許されている公的機関 → `tier: 1`
   - 非商用に限るなど制限がある → `tier: 2`（事実の抽出とリンクのみ）
   - 業界メディア → `tier: 3`（見出しを `data/state.json` の話題メモに残すだけ。記事化しません）
3. Actions の「Run workflow」で試します。

> 初期状態で有効なのは英国 MAIB だけです。米国沿岸警備隊、EMSA、ATSB、国交省などは RSS の URL を記入してから有効にしてください。

---

## 収益化（アフィリエイト）

`config/settings.yaml` の `affiliate:` で `enabled: true` にし、カテゴリごとに紹介したい商品のリンクを書きます。
記事の末尾に「PR」表示付きで表示されます（景品表示法のステルスマーケティング規制への対応）。

---

## 費用と利用枠

- `engine: claude-app`（標準）：追加料金なし。記事作成はClaudeのプランの利用枠を使います。
  普段のチャットと枠を共有するので、多すぎると感じたら `articles_per_run`（1回に記事化する最大本数）を減らしてください。
- `engine: api`：AI利用料が月3,000〜5,000円程度（1日15本前後の場合）。

---

## うまく動かないとき

| 症状 | 確認すること |
| --- | --- |
| Actions が赤い × で失敗する | 失敗した実行を開き、赤いステップのログを見てください |
| 記事が作られない | claude.ai のスケジュールされたタスクの実行履歴を確認。キューが空なら新着がなかっただけです |
| サイトが表示されない | Settings → Pages の Source が「GitHub Actions」か確認 |
| 記事が全く増えない | 試験運用モードでは `content/pending/` に入ります。承認すると公開されます |
| ソースから取得できない | RSS の URL が正しいか、相手サイトの robots.txt で禁止されていないか |

---

## （任意）パソコンで動作確認する

Python 3.11 以上が入っていれば、APIキーなしでデモを動かせます。架空のデータで、公開と保留の両方の流れを確認できます。

```bash
pip install -r requirements.txt
python -m pipeline.main run --demo --mode auto   # demo/site/index.html をブラウザで開く
python -m pipeline.main check-sources            # 各ソースのRSSが読めるか確認
```

## フォルダの構成

| 場所 | 中身 |
| --- | --- |
| `config/settings.yaml` | サイト名、公開モード、AIモデル、検証の基準、アフィリエイト |
| `config/sources.yaml` | 情報ソースの一覧と利用条件 |
| `content/published/` | 公開中の記事 |
| `content/pending/` | 確認待ちの記事 |
| `content/rejected/` | 却下した記事 |
| `data/state.json` | 処理済みURL、業界メディアの話題メモ、実行の記録 |
| `CLAUDE_TASK.md` | 記事作成タスクの手順書（書き換えると次回から反映） |
| `prompts/` | 各AI担当への指示文（両方式で共通） |
| `data/queue/` | 記事化待ちの新着 |
| `pipeline/` | プログラム本体 |
| `templates/`, `static/` | サイトのデザイン |
