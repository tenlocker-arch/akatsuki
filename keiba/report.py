"""レポート出力 —— ターミナル要約と HTML レポート(アカツキの世界観)。"""

from __future__ import annotations

import html
from pathlib import Path

from .bets import summarize_total
from .models import HorseAnalysis, Prediction

MARK_ORDER = {"◎": 0, "○": 1, "▲": 2, "☆": 3, "注": 4, "△": 5, "": 9}


def _sorted_for_display(analyses: list[HorseAnalysis]) -> list[HorseAnalysis]:
    return sorted(analyses, key=lambda a: (MARK_ORDER.get(a.mark, 9), a.expected_rank))


# ──────────────────────────── ターミナル ────────────────────────────

def print_terminal(pred: Prediction) -> None:
    r = pred.race
    line = "─" * 60
    print(line)
    print(f"  {r.date} {r.place} {r.name} ({r.surface}{r.distance}m・{r.going}・{r.clazz})")
    print(line)
    print(f"\n■ 見立て\n{pred.headline}\n")
    print(f"■ 展開予測: {pred.pace.label}")
    if pred.pace.front_runners:
        print(f"  逃げ候補: {'、'.join(pred.pace.front_runners)}")
    if pred.pace.stalkers:
        print(f"  先行勢  : {'、'.join(pred.pace.stalkers)}")
    print()

    print("■ 印・穴度ランキング")
    print(f"  {'印':<2} {'馬番':>2}  {'馬名':<12} {'人気':>3} {'脚質':<3} {'能力':>5} {'穴度':>5}")
    for a in _sorted_for_display(pred.analyses):
        if a.mark == "" and a.ana_score < 0.5:
            continue
        pop = f"{a.entry.popularity}人" if a.entry.popularity else "-"
        print(
            f"  {a.mark or '・':<2} {a.entry.number:>3}  {a.entry.name:<12} "
            f"{pop:>4} {a.running_style:<3} {a.ability:>5.1f} {a.ana_score:>+5.1f}"
        )

    print("\n■ 注目穴馬のストーリー")
    for a in pred.analyses:
        if a.mark in ("☆", "注"):
            print(f"\n--- {a.mark} {a.entry.number} {a.entry.name} ---")
            print(a.story)

    print("\n■ 買い目(予算 {:,}円)".format(pred.budget))
    for t in pred.tickets:
        pay = f"  {t.est_payout}" if t.est_payout else ""
        print(f"  [{t.bet_type}] {t.formation}")
        print(f"     {t.points}点 × {t.amount_per_point}円 = {t.total:,}円{pay}")
        print(f"     {t.note}")
    print(f"\n  合計 {summarize_total(pred.tickets):,}円")
    print("\n  ※ 本予想はデータに基づくヒューリスティックであり的中を保証しません。馬券は余裕資金で。")


# ──────────────────────────── HTML ────────────────────────────

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#03060e;--gold:#d4a84b;--gold-light:#f0d080;--text:#f5ead8;
--sub:#8fa0b8;--border:rgba(212,168,75,.22);--card:rgba(212,168,75,.05)}
body{background:var(--bg);color:var(--text);font-family:'Noto Serif JP','Hiragino Mincho ProN',serif;
line-height:1.9;padding:40px 20px 80px}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:clamp(24px,5vw,38px);letter-spacing:.12em;color:#fff;
text-shadow:0 0 60px rgba(212,168,75,.25)}
.sub{color:var(--gold);letter-spacing:.4em;font-size:12px;text-transform:uppercase;margin-bottom:6px}
.meta{color:var(--sub);font-size:14px;margin-top:8px}
.vline{width:1px;height:42px;background:linear-gradient(to bottom,transparent,var(--gold),transparent);margin:28px auto}
h2{font-size:18px;color:var(--gold-light);letter-spacing:.18em;margin:48px 0 16px;
border-bottom:1px solid var(--border);padding-bottom:8px}
.card{border:1px solid var(--border);background:var(--card);padding:20px 22px;margin:14px 0}
.headline{font-size:15px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:8px 10px;border-bottom:1px solid rgba(212,168,75,.12);text-align:left}
th{color:var(--gold);font-weight:400;letter-spacing:.1em;font-size:12px}
.mark{font-size:18px;color:var(--gold-light)}
.ana-hot{color:#ff9a5a;font-weight:600}
.story-name{font-size:16px;color:#fff;margin-bottom:6px}
.story-name .mark{margin-right:8px}
.story p{margin:10px 0;font-size:14px}
.ev{color:var(--sub);font-size:12px}
.ticket{margin:12px 0;padding:14px 16px;border-left:2px solid var(--gold)}
.ticket .tt{color:var(--gold-light)}
.ticket .fm{font-size:16px;letter-spacing:.06em;margin:4px 0}
.ticket .nt{color:var(--sub);font-size:13px}
.pay{color:#ff9a5a;font-size:13px}
.total{text-align:right;color:var(--gold-light);margin-top:10px;font-size:15px}
.disclaimer{margin-top:60px;color:var(--sub);font-size:12px;border-top:1px solid var(--border);padding-top:16px}
a{color:var(--gold)}
"""


def render_html(pred: Prediction) -> str:
    r = pred.race
    esc = html.escape
    parts: list[str] = []
    parts.append(
        "<!DOCTYPE html><html lang='ja'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
        f"<title>アカツキ競馬 — {esc(r.name)}</title><style>{_CSS}</style></head><body><div class='wrap'>"
    )
    parts.append(
        "<div style='text-align:center'>"
        "<div class='sub'>Akatsuki Keiba — Longshot Hunter</div>"
        f"<h1>{esc(r.name)}</h1>"
        f"<div class='meta'>{r.date} {esc(r.place)} {esc(r.surface)}{r.distance}m"
        f"({esc(r.direction)}) 馬場:{esc(r.going)} {esc(r.clazz)} {r.field_size}頭</div>"
        "<div class='vline'></div></div>"
    )

    parts.append(f"<div class='card headline'>{esc(pred.headline)}</div>")

    # 展開
    parts.append("<h2>展開予測</h2><div class='card'>")
    parts.append(f"<p>想定ペース: <b>{esc(pred.pace.label)}</b> — {esc(pred.pace.description)}</p>")
    if pred.pace.front_runners:
        parts.append(f"<p class='ev'>逃げ候補: {esc('、'.join(pred.pace.front_runners))}</p>")
    if pred.pace.stalkers:
        parts.append(f"<p class='ev'>先行勢: {esc('、'.join(pred.pace.stalkers))}</p>")
    parts.append("</div>")

    # 印と穴度
    parts.append("<h2>印・穴度ランキング</h2><table>")
    parts.append(
        "<tr><th>印</th><th>馬番</th><th>馬名</th><th>騎手</th><th>人気</th>"
        "<th>脚質</th><th>能力</th><th>展開</th><th>穴度</th></tr>"
    )
    for a in _sorted_for_display(pred.analyses):
        hot = " class='ana-hot'" if a.ana_score >= 2.0 else ""
        pop = f"{a.entry.popularity}人気" if a.entry.popularity else "-"
        name = esc(a.entry.name)
        if a.entry.url:
            name = f"<a href='{esc(a.entry.url)}' target='_blank'>{name}</a>"
        parts.append(
            f"<tr><td class='mark'>{a.mark}</td><td>{a.entry.number}</td>"
            f"<td>{name}</td><td>{esc(a.entry.jockey)}</td><td>{pop}</td>"
            f"<td>{a.running_style}</td><td>{a.ability:.1f}</td>"
            f"<td>{a.pace_advantage:+.1f}</td><td{hot}>{a.ana_score:+.1f}</td></tr>"
        )
    parts.append("</table>")

    # ストーリー
    parts.append("<h2>一頭ずつのストーリー</h2>")
    for a in _sorted_for_display(pred.analyses):
        if a.mark == "" and a.ana_score < 0.5:
            continue
        parts.append("<div class='card story'>")
        parts.append(
            f"<div class='story-name'><span class='mark'>{a.mark or '・'}</span>"
            f"{a.entry.number} {esc(a.entry.name)}</div>"
        )
        for para in a.story.split("\n"):
            parts.append(f"<p>{esc(para)}</p>")
        evs = [ev for f in a.findings for ev in f.evidence]
        if evs:
            parts.append("<p class='ev'>出典: " + " ／ ".join(
                (f"<a href='{esc(ev.url)}' target='_blank'>{esc(ev.description)}</a>"
                 if ev.url else esc(ev.description))
                for ev in evs[:6]
            ) + "</p>")
        parts.append("</div>")

    # 買い目
    parts.append(f"<h2>買い目(予算 {pred.budget:,}円)</h2><div class='card'>")
    for t in pred.tickets:
        parts.append("<div class='ticket'>")
        parts.append(f"<div class='tt'>{esc(t.bet_type)}</div>")
        parts.append(f"<div class='fm'>{esc(t.formation)}</div>")
        parts.append(f"<div>{t.points}点 × {t.amount_per_point:,}円 = <b>{t.total:,}円</b>")
        if t.est_payout:
            parts.append(f" <span class='pay'>{esc(t.est_payout)}</span>")
        parts.append("</div>")
        parts.append(f"<div class='nt'>{esc(t.note)}</div></div>")
    parts.append(f"<div class='total'>合計 {summarize_total(pred.tickets):,}円</div></div>")

    parts.append(
        "<div class='disclaimer'>本レポートは過去走データに基づくヒューリスティック予想であり、"
        "的中・回収を保証するものではありません。想定配当は単勝オッズからの粗い概算です。"
        "馬券の購入は20歳以上、余裕資金の範囲で。<br>データ出典: "
        + (f"<a href='{html.escape(pred.race.url)}'>netkeiba 出馬表</a> および各馬の戦績ページ"
           if pred.race.url else "入力された戦績データ")
        + "</div>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def save_html(pred: Prediction, out_dir: str = "reports") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pred.race.race_id or 'race'}.html"
    path.write_text(render_html(pred), encoding="utf-8")
    return path
