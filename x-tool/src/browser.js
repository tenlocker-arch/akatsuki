import fs from "node:fs";
import { chromium } from "playwright";
import { PROFILE_DIR } from "./config.js";

/**
 * 実Chromeを永続プロファイル付きで起動する。
 * 一度 login コマンドでログインすれば、以降はセッションが再利用される。
 */
export async function launchBrowser({ headless = false } = {}) {
  fs.mkdirSync(PROFILE_DIR, { recursive: true });
  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "chrome", // Playwright内蔵ChromiumではなくインストールされたChrome本体を使う
    headless,
    viewport: { width: 1280, height: 900 },
    locale: "ja-JP",
    args: ["--disable-blink-features=AutomationControlled"],
  });
  const page = context.pages()[0] ?? (await context.newPage());
  return { context, page };
}

/** 人間っぽい揺らぎを入れるためのランダム待機 */
export function humanDelay(min = 400, max = 1200) {
  const ms = min + Math.random() * (max - min);
  return new Promise((r) => setTimeout(r, ms));
}

/** テキストを1文字ずつタイプ風に入力する(貼り付け検知対策) */
export async function typeLikeHuman(locator, text) {
  await locator.click();
  await locator.pressSequentially(text, { delay: 30 + Math.random() * 40 });
}
