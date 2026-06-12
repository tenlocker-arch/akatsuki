# x-tool

Chromeブラウザを自動操作してX(旧Twitter)を操作するCLIツール。
自分のアカウントの文体をClaudeに分析させ、その文体で **通常ポスト・引用・リプ・リプ返・予約投稿** を行えます。

> ⚠️ **注意**: ブラウザ自動操作によるXの利用はXの利用規約に抵触する可能性があり、アカウントが制限されるリスクがあります。自己責任で、自分のアカウントに対してのみ使用してください。短時間に大量の投稿をするとスパム判定されやすくなります。

## 仕組み

- **Playwright + 実Chrome**: インストール済みのChrome本体を永続プロファイル付きで起動。一度ログインすればセッションが保存され、以降は自動でログイン状態になります。
- **Claude API** (`claude-opus-4-8`): 文体分析とポスト文の生成に使用。
- **予約投稿**: Xの公式予約投稿機能(コンポーズ画面のカレンダーアイコン)をブラウザ操作で設定します。ツールを常駐させる必要はありません。

## セットアップ

ローカルPC(Chromeがインストールされた環境)で実行してください。

```bash
cd x-tool
npm install

# Claude APIキーを設定(https://platform.claude.com で取得)
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使い方

### 1. ログイン(初回のみ)

```bash
node src/cli.js login
```

Chromeが開くので手動でXにログインし、完了したらターミナルでEnter。セッションは `data/chrome-profile/` に保存されます。

### 2. 文体分析

自分のアカウントのポストをブラウザで収集し、Claudeが文体ガイドを生成します。

```bash
node src/cli.js analyze @your_handle
# または URL でも可
node src/cli.js analyze https://x.com/your_handle
```

生成された文体ガイドは `data/style.md` に保存され、以降のポスト生成で自動的に使われます。手で編集して微調整してもOKです。

### 3. ポスト

```bash
# そのまま投稿
node src/cli.js post "今日もいい天気"

# Claudeに指示して生成(下書き確認 → y/r/n)
node src/cli.js post --ai "新しいツールが完成したことを嬉しそうに報告"

# 予約投稿(X公式の予約機能を使用)
node src/cli.js post --ai "朝の挨拶" --at "2026-06-13 08:00"
```

生成された下書きは投稿前に必ず確認画面が出ます:

- `y` = 投稿する
- `r` = 修正指示を出して再生成(例:「もっと短く」「絵文字なしで」)
- `n` = キャンセル

`-y` を付けると確認をスキップします。

### 4. 引用・リプ

```bash
# 引用ポスト
node src/cli.js quote "https://x.com/someone/status/123..." "共感しつつ自分の意見を添えて"

# リプライ
node src/cli.js reply "https://x.com/someone/status/123..." "丁寧にお礼を伝えて"

# 生成せず自分で書いた本文を使う場合
node src/cli.js reply "https://x.com/..." --text "ありがとうございます!"
```

### 5. リプ返(自分宛てのリプを確認して返信)

```bash
# 自分宛てのメンション一覧を表示
node src/cli.js inbox

# 表示されたURLに対してリプ返
node src/cli.js reply "<表示されたURL>" "フレンドリーにお礼"
```

## ファイル構成

```
x-tool/
├── src/
│   ├── cli.js       # CLIコマンド定義
│   ├── browser.js   # Chrome起動(永続プロファイル)
│   ├── x.js         # XのDOM操作(セレクタはここ)
│   ├── claude.js    # Claude API(文体分析・文章生成)
│   └── config.js    # パス・モデル設定
└── data/
    ├── chrome-profile/  # ログインセッション(gitignore済み)
    └── style.md         # 文体ガイド(gitignore済み)
```

## トラブルシューティング

- **セレクタエラーで失敗する**: XのUI変更で `data-testid` が変わった可能性があります。`src/x.js` の `SEL` を更新してください。
- **予約投稿の日時設定に失敗する**: 予約ダイアログのセレクトボックスID(`#SELECTOR_1`〜`#SELECTOR_6`)はX側の実装依存です。変わっていたら `src/x.js` の `setSchedule` を修正してください。
- **ログインが切れた**: もう一度 `login` を実行してください。

## 今後の予定

- Threads対応(`src/threads.js` として追加予定。CLI・Claude連携部分は共通化済み)
