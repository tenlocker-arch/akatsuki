import fs from "node:fs";
import Anthropic from "@anthropic-ai/sdk";
import { CLAUDE_MODEL, STYLE_FILE } from "./config.js";

// ANTHROPIC_API_KEY 環境変数からキーを読み込む
const client = new Anthropic();

function extractText(response) {
  return response.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("")
    .trim();
}

/**
 * 収集したポスト一覧から文体ガイド(Markdown)を生成する。
 * 生成結果は post/quote/reply の下書き時にシステムプロンプトとして使う。
 */
export async function analyzeStyle(posts, handle) {
  const response = await client.messages.create({
    model: CLAUDE_MODEL,
    max_tokens: 8000,
    thinking: { type: "adaptive" },
    system:
      "あなたはSNSの文体分析の専門家です。与えられたXのポスト群を分析し、" +
      "その人の文体を再現するためのガイドをMarkdownで作成してください。",
    messages: [
      {
        role: "user",
        content:
          `以下は ${handle} の最近のポストです。文体を分析して、` +
          "この人になりきってポストを書くための「文体ガイド」を作成してください。\n\n" +
          "ガイドには以下を含めてください:\n" +
          "- 口調・語尾の特徴(です/ます、だ/である、タメ口 など)\n" +
          "- よく使う言い回し・口癖・絵文字・記号の使い方\n" +
          "- 文の長さ・改行・ハッシュタグの傾向\n" +
          "- 話題の傾向とスタンス(断定的/控えめ、ユーモアの種類 など)\n" +
          "- 避けるべき表現(この人が使わなそうな言葉)\n" +
          "- 実際のポストを模した例文を3つ\n\n" +
          "--- ポスト一覧 ---\n" +
          posts.map((p, i) => `${i + 1}. ${p}`).join("\n\n"),
      },
    ],
  });
  return extractText(response);
}

/** 保存済みの文体ガイドを読み込む(なければnull) */
export function loadStyle() {
  try {
    return fs.readFileSync(STYLE_FILE, "utf8");
  } catch {
    return null;
  }
}

/**
 * ポスト/引用/リプの下書きを生成する。
 * @param {object} opts
 * @param {"post"|"quote"|"reply"} opts.kind
 * @param {string} opts.instruction - ユーザーからの指示
 * @param {string} [opts.targetText] - 引用/リプ対象のポスト本文
 * @param {string} [opts.feedback] - 再生成時の修正指示
 * @param {string} [opts.previousDraft] - 再生成時の前回の下書き
 */
export async function draftPost({ kind, instruction, targetText, feedback, previousDraft }) {
  const style = loadStyle();
  const kindLabel = { post: "通常ポスト", quote: "引用ポスト", reply: "リプライ" }[kind];

  let system =
    "あなたはユーザー本人になりきってXのポストを書くゴーストライターです。\n" +
    "出力はポスト本文のみ。前置き・説明・引用符は一切付けないでください。\n" +
    "文字数はX の制限(全角140字 / 半角280字)に収めてください。\n";
  if (style) {
    system += "\n以下はユーザーの文体ガイドです。必ずこの文体に従ってください。\n\n" + style;
  }

  let prompt = `${kindLabel}を書いてください。\n指示: ${instruction || "(特になし。自然な内容で)"}\n`;
  if (targetText) {
    prompt += `\n対象のポスト本文:\n"""\n${targetText}\n"""\n`;
  }
  if (previousDraft && feedback) {
    prompt +=
      `\n前回の下書き:\n"""\n${previousDraft}\n"""\n` +
      `この下書きへの修正指示: ${feedback}\n修正版を書いてください。\n`;
  }

  const response = await client.messages.create({
    model: CLAUDE_MODEL,
    max_tokens: 2000,
    thinking: { type: "adaptive" },
    system,
    messages: [{ role: "user", content: prompt }],
  });
  return extractText(response);
}
