#!/usr/bin/env node
import fs from "node:fs";
import readline from "node:readline/promises";
import { Command } from "commander";
import { launchBrowser } from "./browser.js";
import {
  isLoggedIn,
  scrapeProfilePosts,
  getTweetText,
  postTweet,
  replyToTweet,
  quoteTweet,
  fetchMentions,
} from "./x.js";
import { analyzeStyle, draftPost, loadStyle } from "./claude.js";
import { STYLE_FILE, DATA_DIR } from "./config.js";

const program = new Command();
program
  .name("x-tool")
  .description("Chrome経由でXを操作するツール(文体分析・投稿・引用・リプ・予約投稿)");

// ── 共通ヘルパー ─────────────────────────────────────────────

async function withBrowser(fn) {
  const { context, page } = await launchBrowser();
  try {
    if (!(await isLoggedIn(page))) {
      console.error("ログインしていません。先に `x-tool login` を実行してください。");
      process.exitCode = 1;
      return;
    }
    await fn(page);
  } finally {
    await context.close();
  }
}

/**
 * 下書きを表示して y(投稿) / r(修正指示を出して再生成) / n(キャンセル) を選ばせる。
 * 確定した本文を返す。キャンセル時は null。
 */
async function confirmDraft(makeDraft, { skipConfirm = false } = {}) {
  let draft = await makeDraft({});
  if (skipConfirm) return draft;

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    while (true) {
      console.log("\n─── 下書き ───────────────────────");
      console.log(draft);
      console.log("──────────────────────────────────");
      const answer = (
        await rl.question("投稿しますか? [y=投稿 / r=修正して再生成 / n=キャンセル] ")
      )
        .trim()
        .toLowerCase();
      if (answer === "y") return draft;
      if (answer === "n") return null;
      if (answer === "r") {
        const feedback = await rl.question("修正指示: ");
        console.log("再生成中...");
        draft = await makeDraft({ feedback, previousDraft: draft });
      }
    }
  } finally {
    rl.close();
  }
}

function parseScheduleAt(value) {
  // "2026-06-13 09:00" 形式
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})$/);
  if (!m) {
    console.error('予約日時は "YYYY-MM-DD HH:mm" 形式で指定してください。');
    process.exit(1);
  }
  const date = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  if (date.getTime() < Date.now() + 5 * 60 * 1000) {
    console.error("予約日時は5分以上先を指定してください。");
    process.exit(1);
  }
  return date;
}

// ── コマンド定義 ─────────────────────────────────────────────

program
  .command("login")
  .description("Chromeを開いてXに手動ログインする(セッションは保存される)")
  .action(async () => {
    const { context, page } = await launchBrowser();
    await page.goto("https://x.com/login");
    console.log("開いたChromeでXにログインしてください。");
    console.log("ログインが完了したら、このターミナルで Enter を押してください。");
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    await rl.question("");
    rl.close();
    if (await isLoggedIn(page)) {
      console.log("✅ ログイン状態を保存しました。");
    } else {
      console.log("⚠️ ログインを確認できませんでした。もう一度試してください。");
    }
    await context.close();
  });

program
  .command("analyze")
  .argument("<account>", "@ハンドル名 または プロフィールURL")
  .option("-n, --limit <number>", "収集するポスト数", "30")
  .description("アカウントのポストを収集してClaudeで文体分析し、文体ガイドを保存する")
  .action(async (account, opts) => {
    await withBrowser(async (page) => {
      console.log(`${account} のポストを収集中...`);
      const posts = await scrapeProfilePosts(page, account, { limit: +opts.limit });
      if (posts.length === 0) {
        console.error("ポストを取得できませんでした。");
        return;
      }
      console.log(`${posts.length}件のポストを取得。Claudeで文体分析中...`);
      const guide = await analyzeStyle(posts, account);
      fs.mkdirSync(DATA_DIR, { recursive: true });
      fs.writeFileSync(STYLE_FILE, guide);
      console.log(`✅ 文体ガイドを保存しました: ${STYLE_FILE}`);
      console.log("\n" + guide);
    });
  });

program
  .command("post")
  .argument("[text]", "投稿する本文(--ai 使用時は省略可)")
  .option("--ai <instruction>", "Claudeに指示を出して本文を生成させる")
  .option("--at <datetime>", '予約投稿 "YYYY-MM-DD HH:mm"')
  .option("-y, --yes", "確認をスキップして即投稿")
  .description("通常ポスト(予約投稿対応)")
  .action(async (text, opts) => {
    const scheduleAt = opts.at ? parseScheduleAt(opts.at) : null;
    let body;
    if (opts.ai) {
      checkStyleWarning();
      body = await confirmDraft(
        ({ feedback, previousDraft }) =>
          draftPost({ kind: "post", instruction: opts.ai, feedback, previousDraft }),
        { skipConfirm: opts.yes }
      );
    } else if (text) {
      body = text;
    } else {
      console.error("本文を指定するか --ai で指示を出してください。");
      process.exit(1);
    }
    if (!body) return console.log("キャンセルしました。");

    await withBrowser(async (page) => {
      await postTweet(page, body, { scheduleAt });
      console.log(scheduleAt ? `✅ 予約投稿しました(${opts.at})` : "✅ 投稿しました。");
    });
  });

program
  .command("quote")
  .argument("<url>", "引用するポストのURL")
  .argument("[instruction]", "Claudeへの指示(例: 共感しつつ自分の経験を添えて)")
  .option("--text <text>", "生成せずこの本文をそのまま使う")
  .option("-y, --yes", "確認をスキップして即投稿")
  .description("引用ポスト")
  .action(async (url, instruction, opts) => {
    await withBrowser(async (page) => {
      let body = opts.text;
      if (!body) {
        checkStyleWarning();
        console.log("対象ポストを読み込み中...");
        const targetText = await getTweetText(page, url);
        body = await confirmDraft(
          ({ feedback, previousDraft }) =>
            draftPost({ kind: "quote", instruction, targetText, feedback, previousDraft }),
          { skipConfirm: opts.yes }
        );
      }
      if (!body) return console.log("キャンセルしました。");
      await quoteTweet(page, url, body);
      console.log("✅ 引用ポストしました。");
    });
  });

program
  .command("reply")
  .argument("<url>", "リプライ先ポストのURL")
  .argument("[instruction]", "Claudeへの指示")
  .option("--text <text>", "生成せずこの本文をそのまま使う")
  .option("-y, --yes", "確認をスキップして即投稿")
  .description("リプライ(リプ返にも使う)")
  .action(async (url, instruction, opts) => {
    await withBrowser(async (page) => {
      let body = opts.text;
      if (!body) {
        checkStyleWarning();
        console.log("対象ポストを読み込み中...");
        const targetText = await getTweetText(page, url);
        body = await confirmDraft(
          ({ feedback, previousDraft }) =>
            draftPost({ kind: "reply", instruction, targetText, feedback, previousDraft }),
          { skipConfirm: opts.yes }
        );
      }
      if (!body) return console.log("キャンセルしました。");
      await replyToTweet(page, url, body);
      console.log("✅ リプライしました。");
    });
  });

program
  .command("inbox")
  .option("-n, --limit <number>", "取得件数", "10")
  .description("自分宛てのリプライ(メンション)一覧を表示する。リプ返は表示されたURLに reply コマンド")
  .action(async (opts) => {
    await withBrowser(async (page) => {
      const mentions = await fetchMentions(page, { limit: +opts.limit });
      if (mentions.length === 0) return console.log("メンションはありません。");
      for (const m of mentions) {
        console.log("─".repeat(50));
        console.log(`👤 ${m.user}`);
        console.log(m.text);
        console.log(`🔗 ${m.url}`);
      }
      console.log("─".repeat(50));
      console.log('リプ返するには: x-tool reply <URL> "返信の方向性"');
    });
  });

function checkStyleWarning() {
  if (!loadStyle()) {
    console.log(
      "ℹ️ 文体ガイドが未作成です。`x-tool analyze @自分のハンドル` を実行すると、" +
        "自分の文体でポストが生成されるようになります。"
    );
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error("ANTHROPIC_API_KEY が設定されていません。");
    process.exit(1);
  }
}

program.parseAsync();
