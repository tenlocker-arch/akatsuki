"""CLI エントリポイント。

使い方:
    # 同梱サンプルレースで試す(ネット不要)
    python -m keiba demo

    # netkeiba のレースIDを指定して予想(日本国内のネットワークから)
    python -m keiba predict --race-id 202506030811 --budget 20000

    # 自分で用意した JSON から予想
    python -m keiba predict --json data/myrace.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyzer import analyze_race
from .bets import build_prediction
from .models import race_from_dict
from .report import print_terminal, save_html

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_race.json"


def run(race, budget: int, out_dir: str, no_html: bool = False) -> None:
    analyses, scenario = analyze_race(race)
    pred = build_prediction(race, analyses, scenario, budget)
    print_terminal(pred)
    if not no_html:
        path = save_html(pred, out_dir)
        print(f"\n  HTMLレポート: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="keiba",
        description="アカツキ競馬 — 穴狙い・帯封特化の競馬予想エンジン",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="同梱サンプルレースで予想を実行(ネット不要)")
    p_pred = sub.add_parser("predict", help="netkeiba または JSON から予想を実行")
    p_pred.add_argument("--race-id", help="netkeiba のレースID (例 202506030811)")
    p_pred.add_argument("--json", dest="json_path", help="レースデータ JSON のパス")
    p_pred.add_argument("--no-cache", action="store_true", help="netkeiba キャッシュを使わない")

    for p in (p_demo, p_pred):
        p.add_argument("--budget", type=int, default=10000, help="馬券予算(円, 既定10000)")
        p.add_argument("--out", default="reports", help="HTMLレポート出力先ディレクトリ")
        p.add_argument("--no-html", action="store_true", help="HTMLレポートを出力しない")

    args = ap.parse_args(argv)

    if args.cmd == "demo":
        race = race_from_dict(json.loads(SAMPLE.read_text(encoding="utf-8")))
    else:
        if args.json_path:
            race = race_from_dict(json.loads(Path(args.json_path).read_text(encoding="utf-8")))
        elif args.race_id:
            from .netkeiba import NetkeibaError, fetch_race

            print(f"netkeiba からレース {args.race_id} を取得中(全頭の戦績も取るので数十秒かかります)…")
            try:
                race = fetch_race(args.race_id, use_cache=not args.no_cache)
            except NetkeibaError as e:
                print(f"取得エラー: {e}", file=sys.stderr)
                return 1
        else:
            p_pred.error("--race-id か --json のどちらかを指定してください")
            return 2

    run(race, args.budget, args.out, args.no_html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
