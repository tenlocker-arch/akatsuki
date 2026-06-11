"""分析エンジン・買い目・レポートのテスト。"""

import json
from datetime import date
from pathlib import Path

import pytest

from keiba.analyzer import (
    analyze_race,
    class_value,
    detect_excuses,
    detect_running_style,
    jockey_tier,
    simulate_pace,
)
from keiba.bets import build_prediction, summarize_total
from keiba.models import Entry, PastRace, Race, race_from_dict
from keiba.report import render_html

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_race.json"


@pytest.fixture
def sample_race() -> Race:
    return race_from_dict(json.loads(SAMPLE.read_text(encoding="utf-8")))


def _past(**kw) -> PastRace:
    base = dict(
        date=date(2026, 5, 10), place="東京", race_name="テスト", clazz="3勝クラス",
        surface="芝", distance=1600, going="良", field_size=14, finish=5,
        margin_sec=0.5, passing=[7, 7, 7],
    )
    base.update(kw)
    return PastRace(**base)


def _entry(number=1, pasts=None, **kw) -> Entry:
    base = dict(
        number=number, draw=number, name=f"馬{number}", sex_age="牡4",
        weight_carried=56.0, jockey="テスト騎手",
    )
    base.update(kw)
    e = Entry(**base)
    e.past_races = pasts or []
    return e


# ──────────────────────────── 単体 ────────────────────────────

def test_class_value_order():
    assert class_value("G1") > class_value("G3") > class_value("3勝クラス")
    assert class_value("メイステークス(L)") > class_value("3勝クラス")
    assert class_value("2勝クラス") > class_value("未勝利")


def test_jockey_tier():
    assert jockey_tier("ルメール") == "S"
    assert jockey_tier("C.ルメール") == "S"
    assert jockey_tier("武豊") == "A"
    assert jockey_tier("無名騎手") == "B"


def test_running_style_front():
    e = _entry(pasts=[_past(passing=[1, 1, 1]), _past(passing=[1, 1, 2]), _past(passing=[2, 2, 3])])
    assert detect_running_style(e) == "逃げ"


def test_running_style_closer():
    e = _entry(pasts=[_past(passing=[12, 12, 10]), _past(passing=[13, 13, 11])])
    assert detect_running_style(e) == "追込"


def test_pace_lone_front_runner_is_slow():
    race = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
        entries=[_entry(1), _entry(2), _entry(3)],
    )
    scenario = simulate_pace(race, {1: "逃げ", 2: "差し", 3: "追込"})
    assert scenario.label == "スロー"
    assert scenario.front_runners == ["馬1"]


def test_pace_many_front_runners_is_high():
    race = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
        entries=[_entry(i) for i in range(1, 5)],
    )
    scenario = simulate_pace(race, {1: "逃げ", 2: "逃げ", 3: "逃げ", 4: "差し"})
    assert scenario.label == "ハイ"


def test_excuse_high_pace_victim():
    today = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
    )
    e = _entry(pasts=[
        _past(finish=9, margin_sec=1.2, passing=[2, 2, 8], pace=(34.0, 35.8)),
    ])
    excuses = detect_excuses(e, today)
    assert any("消耗戦" in f.text for f in excuses)
    assert all(f.evidence for f in excuses), "全所見に出典が必要"


def test_excuse_slow_pace_closer():
    today = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
    )
    e = _entry(pasts=[
        _past(finish=4, margin_sec=0.3, passing=[12, 12, 8], pace=(36.2, 34.5), agari=33.4),
    ])
    excuses = detect_excuses(e, today)
    assert any("展開負け" in f.text for f in excuses)


def test_excuse_class_drop():
    today = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
    )
    e = _entry(pasts=[_past(clazz="G3", finish=8, margin_sec=0.9)])
    excuses = detect_excuses(e, today)
    assert any("格上挑戦" in f.text for f in excuses)


def test_no_excuse_for_good_run():
    today = Race(
        race_id="t", name="t", date=date(2026, 6, 14), place="中山",
        surface="芝", distance=1600, going="良", clazz="3勝クラス",
    )
    e = _entry(pasts=[_past(finish=2, margin_sec=0.1)])
    assert detect_excuses(e, today) == []


# ──────────────────────────── サンプルレース E2E ────────────────────────────

def test_sample_race_loads(sample_race):
    assert sample_race.field_size == 12
    assert sample_race.distance == 1600


def test_analysis_finds_longshot_star(sample_race):
    analyses, scenario = analyze_race(sample_race)
    star = [a for a in analyses if a.mark == "☆"]
    assert len(star) == 1
    assert (star[0].entry.popularity or 0) >= 6, "☆は6番人気以下の穴馬であること"
    # ◎は別の馬に付いている
    assert any(a.mark == "◎" for a in analyses)
    # 全所見に出典がある
    for a in analyses:
        for f in a.findings:
            assert f.evidence, f"出典なしの所見: {f.text}"


def test_prediction_tickets_within_budget(sample_race):
    analyses, scenario = analyze_race(sample_race)
    pred = build_prediction(sample_race, analyses, scenario, budget=10000)
    assert pred.tickets, "買い目が生成されること"
    total = summarize_total(pred.tickets)
    assert 0 < total <= 11000, f"予算1万円に対し合計{total}円"
    # ☆軸の三連単が本線にあること
    star = next(a for a in pred.analyses if a.mark == "☆")
    main = pred.tickets[0]
    assert main.bet_type.startswith("三連単")
    assert main.formation.startswith(str(star.entry.number))


def test_stories_have_sources(sample_race):
    analyses, scenario = analyze_race(sample_race)
    pred = build_prediction(sample_race, analyses, scenario)
    star = next(a for a in pred.analyses if a.mark == "☆")
    assert "根拠" in star.story
    assert pred.headline


def test_html_report_renders(sample_race):
    analyses, scenario = analyze_race(sample_race)
    pred = build_prediction(sample_race, analyses, scenario)
    html_text = render_html(pred)
    assert "<!DOCTYPE html>" in html_text
    for a in pred.analyses:
        if a.mark:
            assert a.entry.name in html_text
    assert "買い目" in html_text
