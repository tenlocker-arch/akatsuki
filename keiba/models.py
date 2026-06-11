"""データモデル。

netkeiba スクレイプ結果・JSON 入力の両方をこの形に正規化してから
分析エンジンに渡す。すべての分析結果(Finding)は必ず出典(Evidence)を持つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_t
from datetime import datetime
from typing import Optional


# ──────────────────────────── 入力データ ────────────────────────────

@dataclass
class PastRace:
    """1頭の過去走1レース分。netkeiba 馬柱(db.netkeiba.com/horse/)の1行に相当。"""

    date: date_t
    place: str                      # 競馬場 (中山/東京/阪神…)
    race_name: str
    clazz: str                      # クラス表記 (G1/G3/3勝クラス/未勝利…)
    surface: str                    # 芝 / ダ / 障
    distance: int                   # メートル
    going: str                      # 良 / 稍重 / 重 / 不良
    field_size: int
    finish: int                     # 着順 (0 = 取消/除外/中止)
    margin_sec: float               # 勝ち馬とのタイム差(秒)。勝った場合は0以下
    passing: list[int] = field(default_factory=list)   # 通過順 例 [3,3,4,5]
    pace: Optional[tuple[float, float]] = None          # レースの (テン3F, 上がり3F)
    agari: Optional[float] = None   # この馬自身の上がり3F
    draw: Optional[int] = None      # 馬番
    popularity: Optional[int] = None
    odds: Optional[float] = None
    weight_carried: Optional[float] = None   # 斤量
    jockey: str = ""
    horse_weight: Optional[int] = None
    time: str = ""
    comment: str = ""               # 備考 (出遅れ/不利 など)
    netkeiba_race_id: Optional[str] = None

    @property
    def url(self) -> Optional[str]:
        if self.netkeiba_race_id:
            return f"https://db.netkeiba.com/race/{self.netkeiba_race_id}/"
        return None

    def label(self) -> str:
        """出典表示用の短いラベル。"""
        return (
            f"{self.date.strftime('%Y/%m/%d')} {self.place} {self.race_name}"
            f" ({self.surface}{self.distance}m {self.going}) {self.finish}着"
        )

    # ペース判定: 正の値 = 前半が速い(ハイ寄り)
    def pace_gap(self) -> Optional[float]:
        if not self.pace:
            return None
        first, last = self.pace
        return last - first

    def pace_label(self) -> Optional[str]:
        gap = self.pace_gap()
        if gap is None:
            return None
        if gap >= 1.5:
            return "ハイ"
        if gap >= 0.5:
            return "ややハイ"
        if gap > -0.5:
            return "ミドル"
        return "スロー"


@dataclass
class Entry:
    """今走の出走馬1頭。"""

    number: int                     # 馬番
    draw: int                       # 枠番
    name: str
    sex_age: str                    # 牡5 / 牝4 …
    weight_carried: float
    jockey: str
    trainer: str = ""
    odds: Optional[float] = None
    popularity: Optional[int] = None
    horse_weight: Optional[int] = None
    horse_weight_diff: Optional[int] = None
    horse_id: Optional[str] = None  # netkeiba horse id
    past_races: list[PastRace] = field(default_factory=list)

    @property
    def url(self) -> Optional[str]:
        if self.horse_id:
            return f"https://db.netkeiba.com/horse/{self.horse_id}/"
        return None


@dataclass
class Race:
    """今走のレース情報。"""

    race_id: str
    name: str
    date: date_t
    place: str
    surface: str
    distance: int
    going: str
    clazz: str
    entries: list[Entry] = field(default_factory=list)
    direction: str = ""             # 右 / 左
    grade: Optional[str] = None

    @property
    def field_size(self) -> int:
        return len(self.entries)

    @property
    def url(self) -> Optional[str]:
        if self.race_id and self.race_id.isdigit():
            return f"https://race.netkeiba.com/race/shutuba.html?race_id={self.race_id}"
        return None


# ──────────────────────────── 分析結果 ────────────────────────────

@dataclass
class Evidence:
    """Finding の根拠となる出典。必ずどのデータから言っているかを示す。"""

    description: str                # 例: "2026/05/10 東京 〇〇S 7着 通過2-2-3"
    url: Optional[str] = None


@dataclass
class Finding:
    """1つの分析所見。本文と根拠と穴度への寄与点を持つ。"""

    category: str                   # excuse / factor / pace / fit / ability / risk
    text: str                       # 日本語の所見文
    impact: float                   # 穴度スコアへの寄与 (負もあり)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class HorseAnalysis:
    """1頭分の分析サマリ。"""

    entry: Entry
    running_style: str = "不明"     # 逃げ / 先行 / 差し / 追込 / 不明
    ability: float = 0.0            # 推定能力 (クラス換算スコア)
    fit: float = 0.0                # 今回条件への適性加点
    pace_advantage: float = 0.0     # 展開利
    findings: list[Finding] = field(default_factory=list)
    expected_rank: int = 0          # 総合力での想定順位
    ana_score: float = 0.0          # 穴度 (人気と実力の乖離+好転材料)
    mark: str = ""                  # ◎ ○ ▲ ☆ △ 注
    story: str = ""                 # ナラティブ本文

    @property
    def strength(self) -> float:
        bonus = sum(f.impact for f in self.findings if f.category in ("excuse", "factor"))
        return self.ability + self.fit + self.pace_advantage * 0.8 + bonus * 0.5

    def findings_by(self, *categories: str) -> list[Finding]:
        return [f for f in self.findings if f.category in categories]


@dataclass
class PaceScenario:
    """レース全体の展開予測。"""

    label: str                      # スロー / ミドル / ややハイ / ハイ
    description: str = ""
    front_runners: list[str] = field(default_factory=list)   # 逃げ候補の馬名
    stalkers: list[str] = field(default_factory=list)        # 先行勢


@dataclass
class Ticket:
    """買い目1種。"""

    bet_type: str                   # 三連単 / 三連複 / 馬連 / ワイド…
    formation: str                  # 表示用 例 "7 → 1,3,7 → 1,3,5,11"
    points: int                     # 点数
    amount_per_point: int           # 1点あたり金額(円)
    note: str = ""                  # 狙いの説明
    est_payout: str = ""            # 想定配当レンジの表示

    @property
    def total(self) -> int:
        return self.points * self.amount_per_point


@dataclass
class Prediction:
    """レース1件の最終予想。"""

    race: Race
    analyses: list[HorseAnalysis]
    pace: PaceScenario
    tickets: list[Ticket] = field(default_factory=list)
    budget: int = 10000
    headline: str = ""              # 予想全体の見出しストーリー


# ──────────────────────────── JSON 変換 ────────────────────────────

def _parse_date(v) -> date_t:
    if isinstance(v, date_t):
        return v
    return datetime.strptime(str(v), "%Y-%m-%d").date()


def past_race_from_dict(d: dict) -> PastRace:
    pace = d.get("pace")
    return PastRace(
        date=_parse_date(d["date"]),
        place=d["place"],
        race_name=d.get("race_name", ""),
        clazz=d.get("clazz", ""),
        surface=d.get("surface", "芝"),
        distance=int(d["distance"]),
        going=d.get("going", "良"),
        field_size=int(d.get("field_size", 0) or 0),
        finish=int(d.get("finish", 0) or 0),
        margin_sec=float(d.get("margin_sec", 0.0) or 0.0),
        passing=[int(x) for x in d.get("passing", [])],
        pace=(float(pace[0]), float(pace[1])) if pace else None,
        agari=float(d["agari"]) if d.get("agari") is not None else None,
        draw=d.get("draw"),
        popularity=d.get("popularity"),
        odds=d.get("odds"),
        weight_carried=d.get("weight_carried"),
        jockey=d.get("jockey", ""),
        horse_weight=d.get("horse_weight"),
        time=d.get("time", ""),
        comment=d.get("comment", ""),
        netkeiba_race_id=d.get("netkeiba_race_id"),
    )


def entry_from_dict(d: dict) -> Entry:
    return Entry(
        number=int(d["number"]),
        draw=int(d.get("draw", d["number"])),
        name=d["name"],
        sex_age=d.get("sex_age", ""),
        weight_carried=float(d.get("weight_carried", 56.0)),
        jockey=d.get("jockey", ""),
        trainer=d.get("trainer", ""),
        odds=d.get("odds"),
        popularity=d.get("popularity"),
        horse_weight=d.get("horse_weight"),
        horse_weight_diff=d.get("horse_weight_diff"),
        horse_id=d.get("horse_id"),
        past_races=[past_race_from_dict(p) for p in d.get("past_races", [])],
    )


def race_from_dict(d: dict) -> Race:
    if "race" in d:
        d = d["race"]
    course = d.get("course", {})
    return Race(
        race_id=str(d.get("race_id", "")),
        name=d.get("name", ""),
        date=_parse_date(d["date"]),
        place=d["place"],
        surface=course.get("surface", d.get("surface", "芝")),
        distance=int(course.get("distance", d.get("distance", 0))),
        going=d.get("going", "良"),
        clazz=d.get("clazz", ""),
        direction=course.get("direction", d.get("direction", "")),
        grade=d.get("grade"),
        entries=[entry_from_dict(e) for e in d.get("entries", [])],
    )
