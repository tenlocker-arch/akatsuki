import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const TOOL_ROOT = path.resolve(__dirname, "..");
export const DATA_DIR = path.join(TOOL_ROOT, "data");
// Chromeのログイン状態(Cookie等)を保存する永続プロファイル
export const PROFILE_DIR = path.join(DATA_DIR, "chrome-profile");
// analyze コマンドが生成する文体ガイド
export const STYLE_FILE = path.join(DATA_DIR, "style.md");

export const CLAUDE_MODEL = "claude-opus-4-8";
