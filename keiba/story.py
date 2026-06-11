"""ストーリー生成。

腕のいい予想屋がやること —— 一頭一頭について、前走・前々走で何が起きたか、
なぜ負けたか(あるいはなぜ勝てたか)、今回は何が変わるのか、どんなレースを
するのか —— を、データの出典を添えた日本語の読み物に組み立てる。
"""

from __future__ import annotations

from .analyzer import _valid_pasts, jockey_tier
from .models import HorseAnalysis, PaceScenario, Race

STYLE_ACTION = {
    "逃げ": "ハナを切って自分の形に持ち込む",
    "先行": "好位のインで脚をためる",
    "差し": "中団で折り合い、直線で外に持ち出す",
    "追込": "後方でじっと我慢し、直線一気に賭ける",
    "不明": "ゲート次第で位置を取りにいく",
}


def build_story(a: HorseAnalysis, race: Race, scenario: PaceScenario) -> str:
    """1頭分のナラティブを組み立てる。"""
    e = a.entry
    pasts = _valid_pasts(e)
    paras: list[str] = []

    # ── 導入: この馬は何者か
    pop = f"{e.popularity}番人気" if e.popularity else "人気不明"
    odds = f"単勝{e.odds}倍" if e.odds else ""
    intro = f"{e.number}番 {e.name}({e.sex_age}・{e.jockey})。{pop}{'・' + odds if odds else ''}。"
    if a.mark == "☆":
        intro += "この人気は明らかに見落とされている——今回いちばん拾いたい一頭だ。"
    elif a.mark == "注":
        intro += "☆に次ぐ二の矢。人気の盲点になっており、ここも見逃せない。"
    elif a.expected_rank <= 3:
        intro += f"総合力はメンバー中{a.expected_rank}番手と評価した。"
    paras.append(intro)

    # ── 近走の振り返り(言い訳=excuse を物語に織り込む)
    excuses = a.findings_by("excuse")
    if excuses:
        lines = ["近走を一走ずつ巻き戻すと、負けには全部「理由」がある。"]
        for f in excuses:
            src = "/".join(ev.description for ev in f.evidence[:1])
            lines.append(f"{f.text}〔根拠: {src}〕")
        paras.append("".join(lines))
    elif pasts:
        last = pasts[0]
        paras.append(
            f"前走は{last.label()}。"
            + ("順調に走れており、大きな減点材料はない。" if last.finish <= 3 else
               "敗因にこれといった言い訳は見当たらず、地力どおりの結果と見る。")
        )

    # ── 今回の好転材料
    factors = a.findings_by("factor")
    if factors:
        lines = ["そして今回、条件が動く。"]
        for f in factors:
            src = "/".join(ev.description for ev in f.evidence[:1])
            lines.append(f"{f.text}〔根拠: {src}〕")
        paras.append("".join(lines))

    # ── 展開の中でどう動くか
    pace_para = (
        f"展開面。今回は「{scenario.label}」想定で、この馬は{a.running_style}。"
        f"{STYLE_ACTION[a.running_style]}競馬になる。"
    )
    pace_f = a.findings_by("pace")
    if pace_f:
        pace_para += pace_f[0].text
    tier = jockey_tier(e.jockey)
    if tier == "S":
        pace_para += f"鞍上{e.jockey}なら展開の綾を逃さず最善手を打ってくる。"
    paras.append(pace_para)

    # ── リスクも正直に
    risks = a.findings_by("risk")
    if risks:
        paras.append("不安材料も書いておく。" + "".join(f.text for f in risks))

    # ── 結論
    if a.mark == "◎":
        concl = "結論、本命。能力・展開・人気のバランスがいちばん取れている。"
    elif a.mark == "☆":
        concl = (
            f"結論、大穴の☆。{pop}でこの内容なら、馬券的な妙味は全馬で最大。"
            "頭まで突き抜けて帯を狙う一撃候補として軸に据える。"
        )
    elif a.mark == "注":
        concl = (
            "結論、二番手の穴。☆と並べて買い目の軸格に組み込み、"
            "2・3着候補の中心に据える。"
        )
    elif a.mark in ("○", "▲"):
        concl = "結論、相手筆頭格。崩れるシーンが想像しにくい。"
    elif a.mark == "△":
        concl = "結論、ヒモで押さえる。展開ひとつで馬券圏内まである。"
    else:
        concl = "結論、今回は見送り。条件が好転したときに改めて狙いたい。"
    paras.append(concl)

    return "\n".join(paras)


def build_headline(analyses: list[HorseAnalysis], race: Race, scenario: PaceScenario) -> str:
    """予想全体の見出しストーリー。"""
    star = next((a for a in analyses if a.mark == "☆"), None)
    honmei = next((a for a in analyses if a.mark == "◎"), None)
    parts = [
        f"{race.place}{race.surface}{race.distance}m・{race.going}。"
        f"展開は「{scenario.label}」を想定。{scenario.description}"
    ]
    if star is not None:
        parts.append(
            f"狙いは{star.entry.popularity}番人気の{star.entry.name}。"
            f"穴度スコア{star.ana_score:.1f}はメンバー最大で、ここから帯を獲りにいく。"
        )
    elif honmei is not None:
        parts.append(
            f"今回は明確な妙味の穴馬が見当たらず、{honmei.entry.name}を軸に手堅く組み立てる。"
        )
    return "".join(parts)


def attach_stories(analyses: list[HorseAnalysis], race: Race, scenario: PaceScenario) -> None:
    for a in analyses:
        a.story = build_story(a, race, scenario)
