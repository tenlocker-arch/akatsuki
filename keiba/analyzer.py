"""分析エンジン。

予想屋の思考をコード化したもの:
  1. 脚質判定        — 通過順から逃げ/先行/差し/追込を判定
  2. 展開シミュレーション — 逃げ・先行勢の数からペースを予測し、脚質ごとの展開利を算出
  3. 敗因エクスキューズ検出 — 近走の負けに「度外視できる言い訳」があるかをデータから拾う
  4. 条件好転・適性    — 騎手強化、格落ち、斤量減、コース実績など今回のプラス材料
  5. 能力推定        — クラス×着差×鮮度で実力をスコア化
  6. 穴度算出        — 「実力順位と人気順位の乖離」+「言い訳」+「好転材料」+「展開利」

すべての所見(Finding)は出典(どのレースのどのデータか)を必ず持つ。
"""

from __future__ import annotations

from .models import (
    Entry,
    Evidence,
    Finding,
    HorseAnalysis,
    PaceScenario,
    PastRace,
    Race,
)

# ──────────────────────────── 定数 ────────────────────────────

# クラスの格をスコア化(能力推定・格上挑戦判定に使う)
CLASS_VALUES: list[tuple[str, float]] = [
    ("G1", 11.0), ("GI", 11.0),
    ("G2", 10.0), ("GII", 10.0),
    ("G3", 9.0), ("GIII", 9.0),
    ("リステッド", 8.2), ("(L)", 8.2), ("L", 8.2),
    ("オープン", 8.0), ("OP", 8.0),
    ("3勝", 7.0), ("1600万", 7.0),
    ("2勝", 6.0), ("1000万", 6.0),
    ("1勝", 5.0), ("500万", 5.0),
    ("未勝利", 3.5),
    ("新馬", 3.5),
]

# 騎手ランク(静的ヒューリスティック。config で上書き可能にする想定)
# S: リーディング上位・G1 常連 / A: 中央で十分上位 / それ以外: B 扱い
JOCKEY_TIERS: dict[str, str] = {
    "ルメール": "S", "C.ルメール": "S", "川田将雅": "S", "川田": "S",
    "モレイラ": "S", "J.モレイラ": "S", "戸崎圭太": "S", "戸崎": "S",
    "横山武史": "S", "坂井瑠星": "S",
    "松山弘平": "A", "岩田望来": "A", "武豊": "A", "西村淳也": "A",
    "菅原明良": "A", "鮫島克駿": "A", "M.デムーロ": "A", "デムーロ": "A",
    "横山和生": "A", "北村友一": "A", "田辺裕信": "A", "三浦皇成": "A",
    "池添謙一": "A", "岩田康誠": "A", "浜中俊": "A", "吉田隼人": "A",
    "佐々木大輔": "A", "団野大成": "A", "藤岡佑介": "A", "松若風馬": "A",
}

STYLE_ORDER = ["逃げ", "先行", "差し", "追込"]

# 展開利マトリクス: ペース → 脚質 → 加点
PACE_ADVANTAGE: dict[str, dict[str, float]] = {
    "スロー":   {"逃げ": 2.0, "先行": 1.3, "差し": -0.6, "追込": -1.5, "不明": 0.0},
    "ミドル":   {"逃げ": 0.3, "先行": 0.5, "差し": 0.3, "追込": -0.3, "不明": 0.0},
    "ややハイ": {"逃げ": -0.7, "先行": -0.2, "差し": 0.8, "追込": 0.8, "不明": 0.0},
    "ハイ":     {"逃げ": -1.5, "先行": -0.7, "差し": 1.2, "追込": 2.0, "不明": 0.0},
}


def class_value(clazz: str) -> float:
    for key, val in CLASS_VALUES:
        if key in clazz:
            return val
    return 5.0  # 不明はだいたい条件戦相当とみなす


def jockey_tier(name: str) -> str:
    if name in JOCKEY_TIERS:
        return JOCKEY_TIERS[name]
    # 「C.ルメール」「ルメール」など表記ゆれを部分一致で救う
    for key, tier in JOCKEY_TIERS.items():
        if len(key) >= 2 and (key in name or name in key):
            return tier
    return "B"


def _ev(past: PastRace, extra: str = "") -> Evidence:
    desc = past.label() + (f" — {extra}" if extra else "")
    return Evidence(description=desc, url=past.url)


def _valid_pasts(entry: Entry) -> list[PastRace]:
    """取消・除外などを除いた過去走(新しい順)。"""
    pasts = [p for p in entry.past_races if p.finish > 0]
    return sorted(pasts, key=lambda p: p.date, reverse=True)


# ──────────────────────────── 1. 脚質判定 ────────────────────────────

def detect_running_style(entry: Entry) -> str:
    pasts = [p for p in _valid_pasts(entry)[:5] if p.passing and p.field_size > 0]
    if not pasts:
        return "不明"
    ratios = []
    lead_count = 0
    for p in pasts:
        first_corner = p.passing[0]
        ratios.append(first_corner / p.field_size)
        if first_corner == 1:
            lead_count += 1
    avg = sum(ratios) / len(ratios)
    if lead_count >= max(2, len(pasts) // 2 + 1) or (lead_count >= 1 and avg <= 0.18):
        return "逃げ"
    if avg <= 0.35:
        return "先行"
    if avg <= 0.65:
        return "差し"
    return "追込"


# ──────────────────────────── 2. 展開シミュレーション ────────────────────────────

def simulate_pace(race: Race, styles: dict[int, str]) -> PaceScenario:
    front = [e.name for e in race.entries if styles.get(e.number) == "逃げ"]
    stalkers = [e.name for e in race.entries if styles.get(e.number) == "先行"]
    n_front, n_stalk = len(front), len(stalkers)

    if n_front == 0:
        label = "スロー"
        desc = (
            "明確な逃げ馬が不在。先行勢の出方次第だが、誰かが押し出されて"
            "緩い流れになる公算が大きい。前で運べる馬の残り目に警戒したい。"
        )
        if n_stalk >= max(3, race.field_size // 3):
            label = "ミドル"
            desc = (
                "逃げ馬不在だが先行勢が多く、先手の取り合いで結果的に淀みない"
                "ミドルペースになりそう。"
            )
    elif n_front == 1:
        if n_stalk <= 2:
            label = "スロー"
            desc = (
                f"{front[0]}の単騎逃げが濃厚で、番手も薄い。マイペースの逃げ"
                "粘り込みが十分に考えられる隊列。"
            )
        else:
            label = "ミドル"
            desc = (
                f"{front[0]}が単騎で行くが、先行勢{n_stalk}頭がプレッシャーを"
                "かける形でミドルペース想定。"
            )
    elif n_front == 2:
        label = "ややハイ"
        desc = (
            f"{front[0]}と{front[1]}の先手争いが見込まれ、流れは緩まない。"
            "前は楽をできず、中団以降の差し馬に出番が回る展開。"
        )
    else:
        label = "ハイ"
        desc = (
            f"逃げたい馬が{n_front}頭({'、'.join(front)})と多く、テンから"
            "激流必至。前崩れで追込馬まで台頭する波乱含みの展開を想定する。"
        )
    return PaceScenario(label=label, description=desc, front_runners=front, stalkers=stalkers)


def pace_advantage(entry: Entry, style: str, scenario: PaceScenario, race: Race) -> tuple[float, list[Finding]]:
    adv = PACE_ADVANTAGE[scenario.label].get(style, 0.0)
    findings: list[Finding] = []
    # 枠順の微調整: 先行馬の内枠は楽、大外は脚を使わされる
    if style in ("逃げ", "先行") and race.field_size >= 10:
        if entry.number <= 4:
            adv += 0.3
        elif entry.number >= race.field_size - 2:
            adv -= 0.3
    if abs(adv) >= 0.8:
        direction = "向く" if adv > 0 else "向かない"
        findings.append(
            Finding(
                category="pace",
                text=(
                    f"想定ペースは「{scenario.label}」。{style}脚質のこの馬には展開が"
                    f"{direction}({adv:+.1f})。"
                ),
                impact=adv,
                evidence=[Evidence(description=f"展開シミュレーション: 逃げ{len(scenario.front_runners)}頭・先行{len(scenario.stalkers)}頭")],
            )
        )
    return adv, findings


# ──────────────────────────── 3. 敗因エクスキューズ検出 ────────────────────────────

def detect_excuses(entry: Entry, race: Race) -> list[Finding]:
    """近3走の敗戦から「度外視できる言い訳」をデータで拾う。これが穴狙いの心臓部。"""
    findings: list[Finding] = []
    pasts = _valid_pasts(entry)
    today_class = class_value(race.clazz if not race.grade else race.grade)

    for i, p in enumerate(pasts[:3]):
        if p.finish <= 3 and p.margin_sec <= 0.4:
            continue  # 好走しているレースに言い訳は不要

        # (a) ハイペースを前で受けて失速 → 度外視
        gap = p.pace_gap()
        early_pos = p.passing[0] if p.passing else None
        if gap is not None and gap >= 1.0 and early_pos is not None and early_pos <= 3 and p.finish >= 5:
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前はテン{p.pace[0]:.1f}-上がり{p.pace[1]:.1f}の"
                    f"消耗戦を{early_pos}番手で受けて{p.finish}着。前にいた馬が"
                    "総崩れする流れで、着順ほど悪い内容ではなく度外視できる。"
                ),
                impact=1.5,
                evidence=[_ev(p, f"通過{'-'.join(map(str, p.passing))} ペース{p.pace[0]:.1f}-{p.pace[1]:.1f}")],
            ))
            continue

        # (b) スロー前残りを豪脚で追い込むも届かず → 展開負け
        if (
            gap is not None and gap <= -0.5
            and p.agari is not None and p.pace is not None
            and p.agari <= p.pace[1] - 0.4
            and p.finish >= 4 and p.margin_sec <= 0.8
        ):
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前はスローの前残り決着を、メンバー上位の上がり"
                    f"{p.agari:.1f}秒で{p.margin_sec:.1f}秒差まで詰めて{p.finish}着。"
                    "完全な展開負けで、脚力では負けていない。"
                ),
                impact=1.3,
                evidence=[_ev(p, f"上がり{p.agari:.1f}(レース上がり{p.pace[1]:.1f}) 着差{p.margin_sec:.1f}秒")],
            ))
            continue

        # (c) 格上挑戦で負けた → 今回のクラスなら通用
        past_class = class_value(p.clazz)
        if past_class >= today_class + 0.9:
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前は{p.clazz}への格上挑戦で{p.finish}着"
                    f"({p.margin_sec:.1f}秒差)。相手が強すぎただけで、"
                    f"今回の{race.clazz}なら相手関係は一気に楽になる。"
                ),
                impact=1.2 if p.margin_sec <= 1.0 else 0.8,
                evidence=[_ev(p, f"クラス格差 {p.clazz} → 今回{race.clazz}")],
            ))
            continue

        # (d) 出遅れ・不利の記録
        if any(k in p.comment for k in ("出遅", "躓", "不利", "挟", "ぶつ", "落鉄")):
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前({p.race_name})は「{p.comment}」の記録があり、"
                    f"{p.finish}着は参考外。スムーズなら結果は違っていた。"
                ),
                impact=1.0,
                evidence=[_ev(p, f"備考: {p.comment}")],
            ))
            continue

        # (e) 道悪での敗戦 → 今回良馬場(またはその逆)
        if p.going in ("重", "不良") and race.going in ("良", "稍重") and _better_on(pasts, "良"):
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前は{p.going}馬場で{p.finish}着も、この馬の好走は"
                    f"良馬場に集中している。今回{race.going}に戻るのは明確なプラス。"
                ),
                impact=0.8,
                evidence=[_ev(p, f"馬場 {p.going}")],
            ))
            continue

        # (f) 距離不適 → 今回はベスト距離に戻る
        if abs(p.distance - race.distance) >= 400 and _best_distance_near(pasts, race.distance):
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前は{p.surface}{p.distance}mで{p.finish}着だが、"
                    f"好走実績は{race.distance}m前後に集中。距離が合わなかった"
                    "だけで、今回の距離替わりで見直せる。"
                ),
                impact=0.8,
                evidence=[_ev(p, f"距離 {p.distance}m → 今回{race.distance}m")],
            ))
            continue

        # (g) 馬体重の激変 → 体調面の言い訳
        prev = pasts[i + 1] if i + 1 < len(pasts) else None
        if (
            p.horse_weight is not None and prev is not None
            and prev.horse_weight is not None
            and abs(p.horse_weight - prev.horse_weight) >= 12
        ):
            diff = p.horse_weight - prev.horse_weight
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前は馬体重{diff:+d}kgと明らかに本調子を欠いた状態"
                    f"での{p.finish}着。体調が戻れば評価は変わる。"
                ),
                impact=0.6,
                evidence=[_ev(p, f"馬体重 {prev.horse_weight}kg → {p.horse_weight}kg")],
            ))
            continue

        # (h) 休み明けの凡走 → 叩いて変わり身
        if prev is not None and (p.date - prev.date).days >= 180 and p.finish >= 5 and i == 1:
            findings.append(Finding(
                category="excuse",
                text=(
                    f"{i + 1}走前は{(p.date - prev.date).days // 30}か月の休み明けで"
                    f"{p.finish}着。叩かれた上積みが今回見込める。"
                ),
                impact=0.7,
                evidence=[_ev(p, f"前走から{(p.date - prev.date).days}日ぶりの実戦")],
            ))

    return findings


def _better_on(pasts: list[PastRace], going: str) -> bool:
    """指定馬場での成績がそれ以外より明確に良いか。"""
    on = [p for p in pasts if p.going == going]
    off = [p for p in pasts if p.going != going]
    if not on or not off:
        return False
    avg = lambda xs: sum(p.finish for p in xs) / len(xs)  # noqa: E731
    return avg(on) + 1.5 <= avg(off)


def _best_distance_near(pasts: list[PastRace], distance: int) -> bool:
    """好走(3着内 or 0.3秒差内)が今回距離±200mに集中しているか。"""
    good = [p for p in pasts if p.finish <= 3 or p.margin_sec <= 0.3]
    if not good:
        return False
    near = [p for p in good if abs(p.distance - distance) <= 200]
    return len(near) >= max(1, len(good) // 2 + (len(good) % 2))


# ──────────────────────────── 4. 条件好転・適性 ────────────────────────────

def detect_factors(entry: Entry, race: Race) -> tuple[float, list[Finding]]:
    findings: list[Finding] = []
    fit = 0.0
    pasts = _valid_pasts(entry)
    last = pasts[0] if pasts else None

    # 騎手強化(乗り替わり)
    tier_rank = {"S": 0, "A": 1, "B": 2}
    today_tier = jockey_tier(entry.jockey)
    if last is not None and last.jockey and last.jockey != entry.jockey:
        last_tier = jockey_tier(last.jockey)
        if tier_rank[today_tier] < tier_rank[last_tier]:
            boost = 0.8 if today_tier == "S" else 0.4
            findings.append(Finding(
                category="factor",
                text=(
                    f"鞍上が{last.jockey}から{entry.jockey}に強化。陣営の勝負気配が"
                    "うかがえる乗り替わりで、ここを獲りにきている。"
                ),
                impact=boost,
                evidence=[_ev(last, f"前走騎手: {last.jockey} → 今回: {entry.jockey}")],
            ))
    elif last is not None and last.jockey == entry.jockey:
        rode_well = [p for p in pasts if p.jockey == entry.jockey and p.finish <= 3]
        if rode_well:
            findings.append(Finding(
                category="factor",
                text=(
                    f"{entry.jockey}騎手とは{len(rode_well)}度の馬券内コンビ実績が"
                    "あり、手の内に入れている。継続騎乗は素直にプラス。"
                ),
                impact=0.3,
                evidence=[_ev(rode_well[0], f"{entry.jockey}騎乗時 {rode_well[0].finish}着")],
            ))

    # コース実績(同場・同表面・同距離で馬券内)
    course_good = [
        p for p in pasts
        if p.place == race.place and p.surface == race.surface
        and abs(p.distance - race.distance) <= 100 and p.finish <= 3
    ]
    if course_good:
        fit += 0.8
        findings.append(Finding(
            category="factor",
            text=(
                f"{race.place}{race.surface}{race.distance}m前後では"
                f"[{len(course_good)}回馬券内]のコース巧者。舞台替わりの不安がない。"
            ),
            impact=0.8,
            evidence=[_ev(p) for p in course_good[:2]],
        ))

    # 距離適性(今回距離±200mでの好走)
    dist_good = [p for p in pasts if abs(p.distance - race.distance) <= 200 and p.finish <= 3]
    if dist_good and not course_good:
        fit += 0.4

    # 斤量減
    if last is not None and last.weight_carried and entry.weight_carried <= last.weight_carried - 1.5:
        diff = last.weight_carried - entry.weight_carried
        findings.append(Finding(
            category="factor",
            text=f"前走から斤量{diff:.1f}kg減。ハンデ頭で恵まれた一頭と見る。",
            impact=0.5,
            evidence=[_ev(last, f"斤量 {last.weight_carried}kg → {entry.weight_carried}kg")],
        ))

    # 道悪巧者が道悪に当たる
    if race.going in ("重", "不良"):
        wet_good = [p for p in pasts if p.going in ("重", "不良") and p.finish <= 3]
        if wet_good:
            fit += 0.7
            findings.append(Finding(
                category="factor",
                text=f"道悪({race.going})は【{len(wet_good)}回馬券内】の鬼。馬場悪化はこの馬の味方。",
                impact=0.7,
                evidence=[_ev(p) for p in wet_good[:2]],
            ))

    # 昇級初戦などのリスク(マイナス材料も正直に出す)
    if last is not None and last.finish == 1 and class_value(last.clazz) < class_value(race.clazz) - 0.5:
        findings.append(Finding(
            category="risk",
            text=f"前走{last.clazz}を勝っての昇級初戦。相手強化への対応が課題。",
            impact=-0.5,
            evidence=[_ev(last)],
        ))
    if last is not None and (race.date - last.date).days >= 180:
        findings.append(Finding(
            category="risk",
            text=f"{(race.date - last.date).days // 30}か月の休み明けで、仕上がりには注文が付く。",
            impact=-0.6,
            evidence=[_ev(last, "前走日付より")],
        ))

    return fit, findings


# ──────────────────────────── 5. 能力推定 ────────────────────────────

def estimate_ability(entry: Entry) -> float:
    """クラス × 着差 × 鮮度 で能力をスコア化(おおむね 0〜11)。"""
    pasts = _valid_pasts(entry)
    if not pasts:
        return 4.0
    newest = pasts[0].date
    scores = []
    weights = []
    for p in pasts[:6]:
        base = class_value(p.clazz)
        if p.finish == 1:
            credit = 1.0
        else:
            credit = max(0.0, 1.0 - p.margin_sec * 0.45 - (p.finish - 1) * 0.015)
        months = max(0, (newest - p.date).days) / 30.0
        w = 0.88 ** months
        scores.append(base * credit)
        weights.append(w)
    weighted = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
    best = max(scores)
    return 0.45 * best + 0.55 * weighted


# ──────────────────────────── 6. 穴度算出と総合 ────────────────────────────

def analyze_race(race: Race) -> tuple[list[HorseAnalysis], PaceScenario]:
    styles = {e.number: detect_running_style(e) for e in race.entries}
    scenario = simulate_pace(race, styles)

    analyses: list[HorseAnalysis] = []
    for e in race.entries:
        a = HorseAnalysis(entry=e, running_style=styles[e.number])
        a.ability = estimate_ability(e)
        a.pace_advantage, pace_f = pace_advantage(e, a.running_style, scenario, race)
        a.findings.extend(pace_f)
        a.findings.extend(detect_excuses(e, race))
        fit, factor_f = detect_factors(e, race)
        a.fit = fit
        a.findings.extend(factor_f)
        analyses.append(a)

    # 総合力で想定順位を付ける
    by_strength = sorted(analyses, key=lambda a: a.strength, reverse=True)
    for rank, a in enumerate(by_strength, start=1):
        a.expected_rank = rank

    # 穴度 = 人気と想定順位の乖離 + 言い訳・好転材料 + 展開利
    for a in analyses:
        pop = a.entry.popularity or a.expected_rank
        value_gap = pop - a.expected_rank
        excuse_sum = sum(f.impact for f in a.findings_by("excuse"))
        factor_sum = sum(f.impact for f in a.findings_by("factor", "risk"))
        a.ana_score = (
            value_gap * 0.55
            + excuse_sum
            + factor_sum
            + max(a.pace_advantage, 0.0) * 0.6
        )

    _assign_marks(analyses)
    return analyses, scenario


def _assign_marks(analyses: list[HorseAnalysis]) -> None:
    """印を打つ。先に☆(穴軸)と注(二番手の穴)を確定させ、残りに◎○▲△△を振る。

    ☆は買い目の軸になるため、総合力上位でも人気薄なら◎ではなく☆を優先する。
    """
    longshots = [
        a for a in analyses
        if (a.entry.popularity or 99) >= 6 and a.ana_score >= 1.5
    ]
    if longshots:
        star = max(longshots, key=lambda a: a.ana_score)
        star.mark = "☆"
        rest = [a for a in longshots if a is not star]
        if rest:
            max(rest, key=lambda a: a.ana_score).mark = "注"
    remaining = sorted(
        (a for a in analyses if a.mark == ""),
        key=lambda a: a.strength,
        reverse=True,
    )
    for a, m in zip(remaining[:5], ["◎", "○", "▲", "△", "△"]):
        a.mark = m


def longshot_picks(analyses: list[HorseAnalysis], min_popularity: int = 6) -> list[HorseAnalysis]:
    """推奨穴馬(人気薄×穴度順)。"""
    picks = [
        a for a in analyses
        if (a.entry.popularity or 99) >= min_popularity and a.ana_score > 0.5
    ]
    return sorted(picks, key=lambda a: a.ana_score, reverse=True)
