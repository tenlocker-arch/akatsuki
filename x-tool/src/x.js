import { humanDelay, typeLikeHuman } from "./browser.js";

// ─────────────────────────────────────────────────────────────
// X (x.com) のDOM操作。data-testid はX側のUI変更で変わることが
// あるため、動かなくなったらここのセレクタを更新する。
// ─────────────────────────────────────────────────────────────

const SEL = {
  composeTextarea: '[data-testid="tweetTextarea_0"]',
  composePostButton: '[data-testid="tweetButton"]',
  inlineReplyButton: '[data-testid="tweetButtonInline"]',
  replyAction: '[data-testid="reply"]',
  retweetAction: '[data-testid="retweet"]',
  tweetText: '[data-testid="tweetText"]',
  tweetArticle: 'article[data-testid="tweet"]',
  sideNavCompose: '[data-testid="SideNav_NewTweet_Button"]',
  scheduleOption: '[data-testid="scheduleOption"]',
  scheduleConfirm: '[data-testid="scheduledConfirmationPrimaryAction"]',
};

/** ログイン済みかどうかを確認する */
export async function isLoggedIn(page) {
  await page.goto("https://x.com/home", { waitUntil: "domcontentloaded" });
  try {
    await page.waitForSelector(SEL.sideNavCompose, { timeout: 8000 });
    return true;
  } catch {
    return false;
  }
}

/** プロフィールページから最近のポスト本文を収集する(文体分析用) */
export async function scrapeProfilePosts(page, handle, { limit = 30 } = {}) {
  const url = handle.startsWith("http")
    ? handle
    : `https://x.com/${handle.replace(/^@/, "")}`;
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(SEL.tweetArticle, { timeout: 15000 });

  const seen = new Set();
  const posts = [];
  for (let i = 0; i < 20 && posts.length < limit; i++) {
    const texts = await page.$$eval(SEL.tweetText, (els) =>
      els.map((el) => el.innerText)
    );
    for (const t of texts) {
      const trimmed = t.trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        posts.push(trimmed);
      }
    }
    await page.mouse.wheel(0, 1800);
    await humanDelay(800, 1600);
  }
  return posts.slice(0, limit);
}

/** ポストURLを開いて本文を取得する(引用・リプの文脈用) */
export async function getTweetText(page, tweetUrl) {
  await page.goto(tweetUrl, { waitUntil: "domcontentloaded" });
  const article = page.locator(SEL.tweetArticle).first();
  await article.waitFor({ timeout: 15000 });
  const text = await article.locator(SEL.tweetText).first().innerText().catch(() => "");
  return text.trim();
}

/** 通常ポスト。scheduleAt (Date) を渡すとXの予約投稿機能を使う */
export async function postTweet(page, text, { scheduleAt = null } = {}) {
  await page.goto("https://x.com/compose/post", { waitUntil: "domcontentloaded" });
  const textarea = page.locator(SEL.composeTextarea);
  await textarea.waitFor({ timeout: 15000 });
  await humanDelay();
  await typeLikeHuman(textarea, text);
  await humanDelay();

  if (scheduleAt) {
    await setSchedule(page, scheduleAt);
  }

  await page.locator(SEL.composePostButton).click();
  await humanDelay(1500, 2500);
}

/** Xの予約投稿ダイアログを操作して日時を設定する */
async function setSchedule(page, date) {
  await page.locator(SEL.scheduleOption).click();
  // 予約ダイアログのセレクトボックス: 月/日/年/時/分/AMPM
  // (UI変更で並びが変わる可能性あり)
  const month = String(date.getMonth() + 1);
  const day = String(date.getDate());
  const year = String(date.getFullYear());
  const hour24 = date.getHours();
  const minute = String(date.getMinutes());
  const isPM = hour24 >= 12;
  const hour12 = String(hour24 % 12 === 0 ? 12 : hour24 % 12);

  await page.locator("#SELECTOR_1").selectOption(month);
  await page.locator("#SELECTOR_2").selectOption(day);
  await page.locator("#SELECTOR_3").selectOption(year);
  await page.locator("#SELECTOR_4").selectOption(hour12);
  await page.locator("#SELECTOR_5").selectOption(minute);
  // 24時間表記のロケールではAM/PMセレクタが存在しない場合がある
  const ampm = page.locator("#SELECTOR_6");
  if (await ampm.count()) {
    await ampm.selectOption(isPM ? "PM" : "AM");
  }
  await page.locator(SEL.scheduleConfirm).click();
  await humanDelay();
}

/** 指定ポストへのリプライ */
export async function replyToTweet(page, tweetUrl, text) {
  await page.goto(tweetUrl, { waitUntil: "domcontentloaded" });
  const article = page.locator(SEL.tweetArticle).first();
  await article.waitFor({ timeout: 15000 });
  await humanDelay();
  await article.locator(SEL.replyAction).click();
  const textarea = page.locator(SEL.composeTextarea);
  await textarea.waitFor({ timeout: 10000 });
  await typeLikeHuman(textarea, text);
  await humanDelay();
  await page.locator(SEL.composePostButton).click();
  await humanDelay(1500, 2500);
}

/** 指定ポストの引用ポスト */
export async function quoteTweet(page, tweetUrl, text) {
  await page.goto(tweetUrl, { waitUntil: "domcontentloaded" });
  const article = page.locator(SEL.tweetArticle).first();
  await article.waitFor({ timeout: 15000 });
  await humanDelay();
  await article.locator(SEL.retweetAction).click();
  // メニューから「引用」を選ぶ(日英両対応)
  const quoteItem = page
    .locator('[role="menuitem"]')
    .filter({ hasText: /引用|Quote/ })
    .first();
  await quoteItem.waitFor({ timeout: 10000 });
  await quoteItem.click();
  const textarea = page.locator(SEL.composeTextarea);
  await textarea.waitFor({ timeout: 10000 });
  await typeLikeHuman(textarea, text);
  await humanDelay();
  await page.locator(SEL.composePostButton).click();
  await humanDelay(1500, 2500);
}

/** 自分宛てのリプライ(メンション通知)一覧を取得する */
export async function fetchMentions(page, { limit = 10 } = {}) {
  await page.goto("https://x.com/notifications/mentions", {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector(SEL.tweetArticle, { timeout: 15000 });
  await humanDelay(1000, 2000);

  return page.$$eval(
    SEL.tweetArticle,
    (articles, max) =>
      articles.slice(0, max).map((a) => {
        const textEl = a.querySelector('[data-testid="tweetText"]');
        const userEl = a.querySelector('[data-testid="User-Name"]');
        const linkEl = a.querySelector('a[href*="/status/"]');
        return {
          user: userEl ? userEl.innerText.replace(/\n/g, " ") : "",
          text: textEl ? textEl.innerText.trim() : "",
          url: linkEl ? new URL(linkEl.getAttribute("href"), "https://x.com").href : "",
        };
      }),
    limit
  );
}
