"""買い目構築 —— 帯封(配当100万円超)を狙う穴軸フォーメーション。

考え方:
  * ☆(大穴)を3連系の軸に据える。人気薄を1着候補に置くのが帯への最短距離。
  * 相手は◎○▲の実力上位 + 穴度のあるヒモで構成し、ガチガチ決着は捨てる。
  * 予算は 三連単(勝負) 6割 / 三連複(中間) 3割 / ワイド(保険) 1割 に配分。

想定配当は単勝オッズの積からの粗い概算(実際の配当は売れ方で大きくぶれる)。
"""

from __future__ import annotations

from itertools import permutations

from .models import HorseAnalysis, Prediction, Race, Ticket


def _fmt(nums: list[int]) -> str:
    return ",".join(str(n) for n in sorted(nums))


def _odds_of(race: Race, n: int) -> float:
    e = next((x for x in race.entries if x.number == n), None)
    return e.odds if e and e.odds else 10.0


def _est_trifecta(race: Race, first: list[int], second: list[int], third: list[int]) -> str:
    """三連単フォーメーションの想定配当レンジ表示。

    単勝オッズ積からの粗い概算(経験的に 配当/100円 ≈ オッズ積 × 0.7〜1.5 × 100円)。
    実際の配当は売れ方次第で大きくぶれるため、あくまで「狙いの規模感」の目安。
    """
    prods = [
        _odds_of(race, c[0]) * _odds_of(race, c[1]) * _odds_of(race, c[2])
        for c in permutations(set(first) | set(second) | set(third), 3)
        if c[0] in first and c[1] in second and c[2] in third
    ]
    if not prods:
        return ""
    lo = int(min(prods) * 0.7) * 100
    hi = int(max(prods) * 1.5) * 100

    def fmt(v: int) -> str:
        return f"{v / 10000:.1f}万円" if v >= 10000 else f"{v:,}円"

    note = "(上限は帯射程圏)" if hi >= 1_000_000 else ""
    return f"想定 {fmt(lo)}〜{fmt(hi)}/100円{note}"


def build_tickets(analyses: list[HorseAnalysis], race: Race, budget: int = 10000) -> list[Ticket]:
    marked = {a.mark: a for a in analyses if a.mark in ("◎", "○", "▲", "☆", "注")}
    sub = [a for a in analyses if a.mark == "△"]

    star = marked.get("☆")
    honmei = marked.get("◎")
    second = marked.get("○")
    third = marked.get("▲")
    note = marked.get("注")

    tops = [a for a in (honmei, second, third) if a is not None]
    tickets: list[Ticket] = []

    if star is not None and tops:
        n_star = star.entry.number
        n_tops = [a.entry.number for a in tops]
        n_subs = [a.entry.number for a in sub]
        n_note = [note.entry.number] if note else []

        # ── 本線: 三連単フォーメーション(穴1着固定で帯を獲る)
        first = [n_star]
        second_row = n_tops + n_note
        third_row = n_tops + n_note + n_subs
        pts = _formation_points(first, second_row, third_row)
        tickets.append(Ticket(
            bet_type="三連単(帯狙い本線)",
            formation=f"{n_star} → {_fmt(second_row)} → {_fmt(third_row)}",
            points=pts,
            amount_per_point=100,
            note=(
                f"☆{star.entry.name}の1着固定。人気薄の頭で配当は跳ね、"
                "ここが刺されば帯が見える。"
            ),
            est_payout=_est_trifecta(race, first, second_row, third_row),
        ))

        # ── 押さえ: 三連単 穴2着付け(頭まで来なくても獲る)
        pts2 = _formation_points(n_tops[:2], [n_star], second_row + n_subs)
        tickets.append(Ticket(
            bet_type="三連単(穴2着付け)",
            formation=f"{_fmt(n_tops[:2])} → {n_star} → {_fmt(second_row + n_subs)}",
            points=pts2,
            amount_per_point=100,
            note="☆が突き抜けきれず2着まで、のパターンを拾う保険ライン。",
            est_payout=_est_trifecta(race, n_tops[:2], [n_star], second_row + n_subs),
        ))

        # ── 中間: 三連複(穴軸1頭流し)
        others = n_tops + n_note + n_subs
        pts3 = len(others) * (len(others) - 1) // 2
        tickets.append(Ticket(
            bet_type="三連複(穴軸1頭)",
            formation=f"{n_star} — {_fmt(others)}",
            points=pts3,
            amount_per_point=100,
            note="☆が3着内に来れば獲れる中間ライン。的中率と配当のバランス枠。",
            est_payout="",
        ))

        # ── 保険: ワイド 穴-実力上位
        for a in tops[:2]:
            tickets.append(Ticket(
                bet_type="ワイド(保険)",
                formation=f"{n_star} — {a.entry.number}",
                points=1,
                amount_per_point=100,
                note=f"☆と{a.mark}{a.entry.name}の組み合わせ。当日まで残す最低限の保険。",
                est_payout="",
            ))
    elif tops:
        # 穴馬不在の日は手を広げない(これも穴党の規律)
        n_tops = [a.entry.number for a in tops]
        n_subs = [a.entry.number for a in sub]
        others = n_tops[1:] + n_subs
        pts = len(others) * (len(others) - 1) // 2
        tickets.append(Ticket(
            bet_type="三連複(◎軸・縮小)",
            formation=f"{n_tops[0]} — {_fmt(others)}",
            points=max(pts, 1),
            amount_per_point=100,
            note="妙味のある穴馬が不在のため点数を絞る。無理に穴を作らないのも帯への近道。",
            est_payout="",
        ))

    _allocate_budget(tickets, budget)
    return tickets


def _formation_points(first: list[int], second: list[int], third: list[int]) -> int:
    pts = 0
    for combo in permutations(set(first) | set(second) | set(third), 3):
        if combo[0] in first and combo[1] in second and combo[2] in third:
            pts += 1
    return pts


def _allocate_budget(tickets: list[Ticket], budget: int) -> None:
    """予算配分: 三連単6割 / 三連複3割 / ワイド1割 を目安に1点あたり金額を調整。"""
    groups = {
        "三連単": [t for t in tickets if t.bet_type.startswith("三連単")],
        "三連複": [t for t in tickets if t.bet_type.startswith("三連複")],
        "ワイド": [t for t in tickets if t.bet_type.startswith("ワイド")],
    }
    ratios = {"三連単": 0.6, "三連複": 0.3, "ワイド": 0.1}
    for key, ts in groups.items():
        if not ts:
            continue
        pool = budget * ratios[key]
        pts = sum(t.points for t in ts)
        if pts == 0:
            continue
        per = max(100, int(pool / pts / 100) * 100)
        for t in ts:
            t.amount_per_point = per


def summarize_total(tickets: list[Ticket]) -> int:
    return sum(t.total for t in tickets)


def build_prediction(race: Race, analyses, scenario, budget: int = 10000) -> Prediction:
    from .story import attach_stories, build_headline

    attach_stories(analyses, race, scenario)
    tickets = build_tickets(analyses, race, budget)
    return Prediction(
        race=race,
        analyses=analyses,
        pace=scenario,
        tickets=tickets,
        budget=budget,
        headline=build_headline(analyses, race, scenario),
    )
