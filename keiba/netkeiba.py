"""netkeiba スクレイパー。

出馬表 (race.netkeiba.com/race/shutuba.html?race_id=…) と
各馬の戦績ページ (db.netkeiba.com/horse/…) を取得して Race モデルに正規化する。

注意:
  * netkeiba は日本国外の IP をブロックすることがある(403)。日本国内から実行すること。
  * 連続アクセスは迷惑になるため、リクエスト間に必ずウェイトを入れ、
    取得結果は .cache/ にキャッシュして再利用する。
  * ページ構造の変更で取れない項目が出ても落ちないよう、列名ベースで防御的にパースする。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .models import Entry, PastRace, Race

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
WAIT_SEC = 1.0
CACHE_DIR = Path(".cache/netkeiba")


class NetkeibaError(RuntimeError):
    pass


def _get(url: str, session: requests.Session, use_cache: bool = True) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("//", 1)[-1])
    cache = CACHE_DIR / f"{key}.html"
    if use_cache and cache.exists():
        return cache.read_text(encoding="utf-8")
    time.sleep(WAIT_SEC)
    res = session.get(url, headers={"User-Agent": UA}, timeout=20)
    if res.status_code == 403:
        raise NetkeibaError(
            f"netkeiba が 403 を返しました ({url})。国外 IP はブロックされるため、"
            "日本国内のネットワークから実行してください。"
        )
    res.raise_for_status()
    res.encoding = res.apparent_encoding  # netkeiba は EUC-JP
    cache.write_text(res.text, encoding="utf-8")
    return res.text


def _soup(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml")


# ──────────────────────────── 出馬表 ────────────────────────────

def fetch_race(race_id: str, max_past: int = 6, use_cache: bool = True) -> Race:
    """race_id (例 202506030811) から出馬表+全頭の過去走を取得する。"""
    session = requests.Session()
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    soup = _soup(_get(url, session, use_cache))

    name_el = soup.select_one(".RaceName")
    data1 = soup.select_one(".RaceData01")
    data2 = soup.select_one(".RaceData02")
    name = name_el.get_text(strip=True) if name_el else race_id
    d1 = data1.get_text(" ", strip=True) if data1 else ""
    d2 = data2.get_text(" ", strip=True) if data2 else ""

    m = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", d1)
    surface = m.group(1) if m else "芝"
    distance = int(m.group(2)) if m else 0
    m = re.search(r"馬場\s*[::]?\s*(良|稍重|重|不良)", d1)
    going = m.group(1) if m else "良"
    direction = "右" if "右" in d1 else ("左" if "左" in d1 else "")

    m = re.search(r"(G[I1]{1,3}|G[123]|リステッド|オープン|3勝クラス|2勝クラス|1勝クラス|未勝利|新馬)", d2)
    clazz = m.group(1) if m else d2[:20]
    grade = clazz if clazz.startswith("G") else None

    place = ""
    m = re.search(r"(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)", d2 + d1)
    if m:
        place = m.group(1)

    # 開催日は race_id からは年しか確実に取れないので、ページ内の日付 or 今日
    date = datetime.now().date()
    title = soup.select_one("title")
    if title:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title.get_text())
        if m:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()

    race = Race(
        race_id=race_id, name=name, date=date, place=place,
        surface=surface, distance=distance, going=going,
        clazz=clazz, direction=direction, grade=grade,
    )

    odds_map = _fetch_odds(race_id, session)

    for tr in soup.select("tr.HorseList"):
        entry = _parse_entry_row(tr)
        if entry is None:
            continue
        if entry.number in odds_map:
            entry.odds = odds_map[entry.number]
        race.entries.append(entry)

    # オッズから人気を補完
    with_odds = [e for e in race.entries if e.odds]
    for rank, e in enumerate(sorted(with_odds, key=lambda x: x.odds), start=1):
        if e.popularity is None:
            e.popularity = rank

    if not race.entries:
        raise NetkeibaError(f"出馬表から馬を読み取れませんでした: {url}")

    # 各馬の過去走
    for e in race.entries:
        if e.horse_id:
            try:
                e.past_races = fetch_horse_results(e.horse_id, session, max_past, use_cache)
            except Exception as ex:  # 1頭失敗しても全体は続行
                print(f"  [warn] {e.name} の戦績取得に失敗: {ex}")
    return race


def _parse_entry_row(tr) -> Optional[Entry]:
    tds = tr.select("td")
    if len(tds) < 8:
        return None

    def txt(sel: str) -> str:
        el = tr.select_one(sel)
        return el.get_text(strip=True) if el else ""

    name_a = tr.select_one(".HorseName a, .HorseInfo a")
    if not name_a:
        return None
    horse_id = None
    m = re.search(r"/horse/(\w+)", name_a.get("href", ""))
    if m:
        horse_id = m.group(1)

    number = _int(txt("[class*=Umaban]"))
    draw = _int(txt("[class*=Waku]")) or number
    if not number:
        return None

    weight_txt = txt(".Weight")
    horse_weight = horse_weight_diff = None
    m = re.search(r"(\d{3})\(([+-]?\d+)\)", weight_txt)
    if m:
        horse_weight, horse_weight_diff = int(m.group(1)), int(m.group(2))

    pop = _int(txt(".Popular_Ninki, [class*=Ninki]"))

    return Entry(
        number=number,
        draw=draw,
        name=name_a.get_text(strip=True),
        sex_age=txt(".Barei, [class*=Barei]"),
        weight_carried=_float(txt(".Txt_C + td")) or _float(tds[5].get_text(strip=True)) or 56.0,
        jockey=txt(".Jockey a, .Jockey"),
        trainer=txt(".Trainer a, .Trainer"),
        popularity=pop or None,
        horse_weight=horse_weight,
        horse_weight_diff=horse_weight_diff,
        horse_id=horse_id,
    )


def _fetch_odds(race_id: str, session: requests.Session) -> dict[int, float]:
    """単勝オッズ API(取れなければ空 dict)。"""
    url = (
        "https://race.netkeiba.com/api/api_get_jra_odds.html"
        f"?race_id={race_id}&type=1&action=init"
    )
    try:
        time.sleep(WAIT_SEC)
        res = session.get(url, headers={"User-Agent": UA}, timeout=15)
        data = json.loads(res.text.lstrip("﻿"))
        odds_obj = data.get("data", {}).get("odds", {}).get("1", {})
        out = {}
        for k, v in odds_obj.items():
            try:
                out[int(k)] = float(v[0])
            except (ValueError, TypeError, IndexError):
                continue
        return out
    except Exception:
        return {}


# ──────────────────────────── 馬の戦績 ────────────────────────────

def fetch_horse_results(
    horse_id: str, session: requests.Session, max_past: int = 6, use_cache: bool = True
) -> list[PastRace]:
    url = f"https://db.netkeiba.com/horse/{horse_id}/"
    soup = _soup(_get(url, session, use_cache))
    table = soup.select_one("table.db_h_race_results")
    if table is None:
        return []

    headers = [th.get_text(strip=True) for th in table.select("tr th")]

    def col(row_tds, *names) -> str:
        for nm in names:
            if nm in headers:
                i = headers.index(nm)
                if i < len(row_tds):
                    return row_tds[i].get_text(strip=True)
        return ""

    results: list[PastRace] = []
    for tr in table.select("tr")[1:]:
        tds = tr.select("td")
        if len(tds) < 10:
            continue
        try:
            past = _parse_result_row(tds, col, tr)
            if past is not None:
                results.append(past)
        except Exception:
            continue
        if len(results) >= max_past:
            break
    return results


def _parse_result_row(tds, col, tr) -> Optional[PastRace]:
    date_s = col(tds, "日付")
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_s)
    if not m:
        return None
    date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()

    kaisai = col(tds, "開催")
    place = re.sub(r"\d", "", kaisai)

    race_name = col(tds, "レース名")
    race_id = None
    a = tr.select_one("a[href*='/race/']")
    if a:
        mm = re.search(r"/race/(\d+)", a.get("href", ""))
        if mm:
            race_id = mm.group(1)

    dist_s = col(tds, "距離")
    mm = re.match(r"(芝|ダ|障)(\d{3,4})", dist_s)
    surface = mm.group(1) if mm else "芝"
    distance = int(mm.group(2)) if mm else 0

    finish_s = col(tds, "着順")
    finish = _int(finish_s)
    if finish == 0 and finish_s not in ("中", "取", "除", "降"):
        return None

    passing = [
        _int(x) for x in col(tds, "通過").split("-") if _int(x)
    ]
    pace = None
    mm = re.match(r"([\d.]+)-([\d.]+)", col(tds, "ペース"))
    if mm:
        pace = (float(mm.group(1)), float(mm.group(2)))

    hw = None
    mm = re.match(r"(\d{3})", col(tds, "馬体重"))
    if mm:
        hw = int(mm.group(1))

    margin = _float(col(tds, "着差"))

    return PastRace(
        date=date,
        place=place,
        race_name=race_name,
        clazz=race_name,  # 条件戦はレース名がクラス表記、重賞は (G1) 等を含む
        surface=surface,
        distance=distance,
        going=col(tds, "馬場") or "良",
        field_size=_int(col(tds, "頭数")),
        finish=finish,
        margin_sec=max(margin or 0.0, 0.0),
        passing=passing,
        pace=pace,
        agari=_float(col(tds, "上り")) or None,
        draw=_int(col(tds, "馬番")) or None,
        popularity=_int(col(tds, "人気")) or None,
        odds=_float(col(tds, "オッズ")) or None,
        weight_carried=_float(col(tds, "斤量")) or None,
        jockey=col(tds, "騎手"),
        horse_weight=hw,
        time=col(tds, "タイム"),
        comment=col(tds, "備考"),
        netkeiba_race_id=race_id,
    )


def _int(s: str) -> int:
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def _float(s: str) -> Optional[float]:
    m = re.search(r"-?[\d.]+", s or "")
    try:
        return float(m.group()) if m else None
    except ValueError:
        return None
