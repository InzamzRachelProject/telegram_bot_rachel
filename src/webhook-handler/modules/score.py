# -*- coding: utf8 -*-
"""Telegram 积分系统：按时段/行为记分，MongoDB 按 user_id 持久化。"""
from __future__ import annotations

import math
import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

TZ_CN = timezone(timedelta(hours=8))
SCORE_PAGES = 3
COLLECTION_NAME = "UserScores"

# 消息内 slash 快捷命令 -> apply_action
SCORE_ACTION_COMMANDS = {
    "/score_wake": "wake",
    "/score_sleep": "sleep",
    "/score_arrive": "arrive",
    "/score_leave": "leave",
    "/score_ot": "ot",
    "/score_diet": "diet",
    "/score_plane_tool": "plane_tool",
    "/score_plane_notool": "plane_notool",
    "/score_plane_minus": "plane_minus",
    "/score_med_plus": "med_plus",
    "/score_med_minus": "med_minus",
    "/score_duo_plus": "duo_plus",
    "/score_duo_minus": "duo_minus",
}

# Inline callback_data payload（score: 前缀之后）-> action
CALLBACK_ACTION_MAP = {
    "wake": "wake",
    "sleep": "sleep",
    "arrive": "arrive",
    "leave": "leave",
    "ot": "ot",
    "diet": "diet",
    "plane:tool": "plane_tool",
    "plane:notool": "plane_notool",
    "plane:minus": "plane_minus",
    "med:+": "med_plus",
    "med:-": "med_minus",
    "duo:+": "duo_plus",
    "duo:-": "duo_minus",
}

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def now_cn() -> datetime:
    return datetime.now(TZ_CN)


def date_str(d: date) -> str:
    return d.isoformat()


def parse_date(s: str) -> date:
    return date.fromisoformat(s)


def week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def minutes_of_day(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt_hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def logical_sleep_date(now: Optional[datetime] = None) -> date:
    """中午 12:00 前点睡觉，归入前一天。"""
    now = now or now_cn()
    d = now.date()
    if now.hour < 12:
        return d - timedelta(days=1)
    return d


def sleep_hour_offset(logical_day: date, click_at: datetime) -> float:
    """逻辑日起点 00:00 到实际点击时刻的小时数（可 >24，如 02:00 -> 26）。"""
    start = datetime(logical_day.year, logical_day.month, logical_day.day, tzinfo=TZ_CN)
    return (click_at - start).total_seconds() / 3600.0


def iter_dates(end: date, days: int) -> List[date]:
    return [end - timedelta(days=i) for i in range(days)]


# ---------------------------------------------------------------------------
# Scoring pure functions
# ---------------------------------------------------------------------------


def score_wake(hhmm: str) -> float:
    mins = minutes_of_day(hhmm)
    if mins < 6 * 60 + 5:
        return 2.0
    if mins < 7 * 60 + 5:
        return 1.5
    if mins < 8 * 60 + 5:
        return 1.0
    if mins >= 9 * 60:
        return -1.0
    return 0.0


def score_sleep(hour_offset: float) -> float:
    if hour_offset < 22 + 5 / 60:
        return 2.0
    if hour_offset < 23 + 5 / 60:
        return 1.5
    if hour_offset < 24 + 5 / 60:
        return 1.0
    if hour_offset >= 26:
        # 26点后 -1，27点后 -2 ...
        return -float(math.floor(hour_offset - 25))
    return 0.0


def score_arrive(hhmm: str) -> float:
    mins = minutes_of_day(hhmm)
    if mins < 8 * 60 + 5:
        return 2.0
    if mins < 9 * 60 + 5:
        return 1.0
    if mins >= 11 * 60:
        return -4.0
    if mins >= 10 * 60 + 30:
        return -2.0
    if mins >= 10 * 60:
        return -1.0
    return 0.0


def score_leave(hhmm: str, logical_day: date, click_at: datetime) -> float:
    """下班：相对逻辑日 0 点的小时数；跨日 00:xx 视为 24+。"""
    hour_offset = sleep_hour_offset(logical_day, click_at)
    # 若同一天内用 hhmm（无跨日），也兼容直接点按
    if click_at.date() == logical_day:
        hour_offset = minutes_of_day(hhmm) / 60.0
    if hour_offset >= 24:
        return 2.0
    if hour_offset >= 23:
        return 1.0
    return 0.0


def score_sleep_hours(hours: float) -> float:
    """少于7小时 -1，少于6小时 -2，以此类推。"""
    if hours >= 7:
        return 0.0
    # 6.9→-1, 5.9→-2, 5.0→-2, 4.0→-3
    return -float(math.floor(7 - hours - 1e-12) + 1)


def score_activity_minutes(minutes: float) -> float:
    if minutes < 30:
        return 0.0
    return math.floor(minutes / 30) * 0.5


def score_cost(rmb: float) -> float:
    """多余4k -1，多余5k -2，以此类推；小于3k +1。"""
    if rmb < 3000:
        return 1.0
    if rmb <= 4000:
        return 0.0
    penalty = 0
    threshold = 4000
    while rmb > threshold:
        penalty += 1
        threshold += 1000
    return -float(penalty)


def score_sport_week(total_min: int) -> float:
    if total_min <= 0:
        return -2.0
    if total_min < 60:
        return -1.0
    return 0.0


def plane_net(day: dict) -> int:
    raw = int(day.get("plane_with_tool", 0)) + int(day.get("plane_no_tool", 0)) - int(
        day.get("plane_minus", 0)
    )
    return max(0, raw)


# ---------------------------------------------------------------------------
# Mongo
# ---------------------------------------------------------------------------


def _collection():
    from pymongo import MongoClient

    mongo_uri = os.getenv("MONGODB_ATLAS_URI")
    if not mongo_uri:
        raise RuntimeError("MONGODB_ATLAS_URI not set")
    rachel_db_name = os.environ.get("RACHEL_DATABASE", "Rachel")
    client = MongoClient(mongo_uri, maxPoolSize=10, minPoolSize=1)
    db = client.get_database(rachel_db_name)
    col = db.get_collection(COLLECTION_NAME)
    col.create_index("user_id", unique=True)
    return client, col


def empty_day() -> dict:
    return {
        "wake_at": None,
        "sleep_at": None,
        "sleep_hours": None,
        "arrive_at": None,
        "leave_at": None,
        "overtime": 0,
        "read_min": 0,
        "study_min": 0,
        "guitar_min": 0,
        "sport_min": 0,
        "healthy_diet": False,
        "plane_with_tool": 0,
        "plane_no_tool": 0,
        "plane_minus": 0,
        "plane_scored_net": 0,  # 已按净计数扣过分的水位
        "meditate_min": 0,
        "duolingo_delta": 0,
        "deltas": [],
        "healthy_pair_awarded": False,
        "meditate_streak_awarded_key": None,
    }


def get_or_create_score(user_id: str) -> dict:
    client, col = _collection()
    try:
        doc = col.find_one({"user_id": str(user_id)})
        if doc:
            doc.pop("_id", None)
            return doc
        doc = {
            "user_id": str(user_id),
            "total_score": 0.0,
            "days": {},
            "months": {},
            "weeks": {},
            "resets": [],
            "updated_at": now_cn().isoformat(),
        }
        col.insert_one(deepcopy(doc))
        return doc
    finally:
        client.close()


def save_score(doc: dict) -> None:
    client, col = _collection()
    try:
        doc = deepcopy(doc)
        doc["updated_at"] = now_cn().isoformat()
        user_id = doc["user_id"]
        col.update_one({"user_id": user_id}, {"$set": doc}, upsert=True)
    finally:
        client.close()


def day_bucket(doc: dict, d: date) -> dict:
    key = date_str(d)
    days = doc.setdefault("days", {})
    if key not in days:
        days[key] = empty_day()
    # backfill new fields
    base = empty_day()
    for k, v in base.items():
        days[key].setdefault(k, v)
    return days[key]


def sum_deltas_by_src(day: dict, src: str) -> float:
    return sum(float(x.get("delta", 0)) for x in day.get("deltas", []) if x.get("src") == src)


def remove_deltas_by_src(day: dict, src: str) -> float:
    """移除某 src 的全部 delta，返回被移除合计（正数表示曾加上的分）。"""
    kept = []
    removed = 0.0
    for x in day.get("deltas", []):
        if x.get("src") == src:
            removed += float(x.get("delta", 0))
        else:
            kept.append(x)
    day["deltas"] = kept
    return removed


def add_delta(day: dict, src: str, delta: float, note: str = "") -> None:
    if abs(delta) < 1e-9 and not note:
        return
    entry = {"src": src, "delta": float(delta), "at": now_cn().isoformat()}
    if note:
        entry["note"] = note
    day.setdefault("deltas", []).append(entry)


def apply_replace_src(doc: dict, day: dict, src: str, new_delta: float, note: str = "") -> float:
    """冲销旧 src 分，写入新分；返回对 total 的净变化。"""
    old = remove_deltas_by_src(day, src)
    add_delta(day, src, new_delta, note)
    net = new_delta - old
    doc["total_score"] = float(doc.get("total_score", 0)) + net
    return net


# ---------------------------------------------------------------------------
# Weekly sport penalty (no double count)
# ---------------------------------------------------------------------------


def week_date_range(wk: str) -> Tuple[date, date]:
    """Parse 2026-W29 -> Mon..Sun dates."""
    year_s, w_s = wk.split("-W")
    year, week = int(year_s), int(w_s)
    # ISO: week 1 contains Jan 4
    jan4 = date(year, 1, 4)
    start = jan4 - timedelta(days=jan4.isoweekday() - 1) + timedelta(weeks=week - 1)
    return start, start + timedelta(days=6)


def sport_minutes_in_week(doc: dict, wk: str) -> int:
    start, end = week_date_range(wk)
    total = 0
    d = start
    while d <= end:
        day = doc.get("days", {}).get(date_str(d), {})
        total += int(day.get("sport_min", 0) or 0)
        d += timedelta(days=1)
    return total


def ensure_sport_week_penalty(doc: dict, today: Optional[date] = None) -> Optional[str]:
    """
    进入新周后第一次触达时，结算上一完整周；用 weeks[wk].sport_penalty_applied 防重复。
    返回提示语或 None。
    """
    today = today or now_cn().date()
    prev_sunday = today - timedelta(days=today.isoweekday())
    prev_week = week_key(prev_sunday)
    weeks = doc.setdefault("weeks", {})
    w = weeks.setdefault(prev_week, {})
    if "sport_penalty_applied" in w and w["sport_penalty_applied"] is not None:
        return None
    # 仅当 prev_sunday 严格早于 today（即上周已结束）
    if prev_sunday >= today:
        return None
    mins = sport_minutes_in_week(doc, prev_week)
    penalty = score_sport_week(mins)
    w["sport_penalty_applied"] = penalty
    w["sport_penalty_delta"] = penalty
    w["sport_minutes"] = mins
    if abs(penalty) > 1e-9:
        # 记到上周日那天的 deltas 便于审计
        day = day_bucket(doc, prev_sunday)
        add_delta(day, "sport_week", penalty, note=f"{prev_week} sport={mins}m")
        doc["total_score"] = float(doc.get("total_score", 0)) + penalty
        return f"上周({prev_week})运动{mins}分钟，结算 {penalty:+g} 分"
    return f"上周({prev_week})运动{mins}分钟，无需扣分"


# ---------------------------------------------------------------------------
# Plane / healthy / meditate streak logic
# ---------------------------------------------------------------------------


def _had_any_plane(day: dict) -> bool:
    return (
        int(day.get("plane_with_tool", 0))
        + int(day.get("plane_no_tool", 0))
        + int(day.get("plane_minus", 0))
    ) > 0


def apply_plane_click(doc: dict, today: date, kind: str) -> str:
    """kind: tool | notool | minus"""
    day = day_bucket(doc, today)
    before_any_today = _had_any_plane(day)

    if kind == "tool":
        day["plane_with_tool"] = int(day.get("plane_with_tool", 0)) + 1
    elif kind == "notool":
        day["plane_no_tool"] = int(day.get("plane_no_tool", 0)) + 1
    elif kind == "minus":
        day["plane_minus"] = int(day.get("plane_minus", 0)) + 1
    else:
        return "未知飞机操作"

    net = plane_net(day)
    msgs = []
    delta_total = 0.0

    # 四天内无飞机记录 + 本次带工具 → +0.5（当天此前也无记录）
    if kind == "tool" and not before_any_today:
        prior_plane = False
        for d in iter_dates(today, 5)[1:]:
            od = doc.get("days", {}).get(date_str(d), {})
            if _had_any_plane(od):
                prior_plane = True
                break
        if not prior_plane:
            add_delta(day, "plane_tool_bonus", 0.5)
            delta_total += 0.5
            msgs.append("四日无记录+工具 +0.5")

    # 当天 net>=2：首次到 2 扣 1，之后每多一次再扣 1（用水位防叠）
    scored = int(day.get("plane_scored_net", 0))
    if net >= 2:
        target_penalty_units = net - 1  # net=2→1, net=3→2
        already_units = max(0, scored - 1) if scored >= 2 else 0
        extra = target_penalty_units - already_units
        if extra > 0:
            pen = -float(extra)
            add_delta(day, "plane_day", pen)
            delta_total += pen
            msgs.append(f"当日飞机净计{net} {pen:+g}")
        day["plane_scored_net"] = net
    elif net < scored:
        day["plane_scored_net"] = net

    # net>1 且近4天存在 net>1 → -0.5（每次满足条件的点击）
    if net > 1:
        has_recent = False
        for d in iter_dates(today, 5)[1:]:
            od = doc.get("days", {}).get(date_str(d), {})
            if plane_net(od) > 1:
                has_recent = True
                break
        if has_recent:
            add_delta(day, "plane_4d", -0.5)
            delta_total += -0.5
            msgs.append("四日内曾>1次 -0.5")

    doc["total_score"] = float(doc.get("total_score", 0)) + delta_total
    return f"飞机净计 {net}；" + ("；".join(msgs) if msgs else "无额外分")


def apply_healthy_toggle(doc: dict, today: date) -> str:
    day = day_bucket(doc, today)
    day["healthy_diet"] = not bool(day.get("healthy_diet"))
    msg = "已标记健康饮食" if day["healthy_diet"] else "已取消健康饮食"

    if day["healthy_diet"] and not day.get("healthy_pair_awarded"):
        yday = today - timedelta(days=1)
        y = doc.get("days", {}).get(date_str(yday), {})
        if y.get("healthy_diet"):
            # 连续两天：在第二天 +0.5，用 pair key 防重
            add_delta(day, "healthy_streak", 0.5)
            day["healthy_pair_awarded"] = True
            doc["total_score"] = float(doc.get("total_score", 0)) + 0.5
            msg += "；连续两天健康饮食 +0.5"
    return msg


def apply_meditate(doc: dict, today: date, delta_min: int) -> str:
    day = day_bucket(doc, today)
    day["meditate_min"] = max(0, int(day.get("meditate_min", 0)) + delta_min)
    mins = int(day["meditate_min"])
    new_score = score_activity_minutes(mins)
    apply_replace_src(doc, day, "meditate", new_score)

    # 连续 3 天每天 >=5 分钟 → +0.5（防重）
    d0, d1, d2 = today, today - timedelta(days=1), today - timedelta(days=2)
    m0 = int(day_bucket(doc, d0).get("meditate_min", 0))
    m1 = int(doc.get("days", {}).get(date_str(d1), {}).get("meditate_min", 0) or 0)
    m2 = int(doc.get("days", {}).get(date_str(d2), {}).get("meditate_min", 0) or 0)
    streak_key = f"{date_str(d2)}_{date_str(d0)}"
    msg = f"冥想 {mins} 分钟（当日分 {new_score:+g}）"
    if m0 >= 5 and m1 >= 5 and m2 >= 5:
        if day.get("meditate_streak_awarded_key") != streak_key:
            # 冲销可能存在的旧不同窗口奖励不需要；只对当前窗口发一次
            if not any(
                x.get("src") == "meditate_streak" and x.get("note") == streak_key
                for x in day.get("deltas", [])
            ):
                add_delta(day, "meditate_streak", 0.5, note=streak_key)
                day["meditate_streak_awarded_key"] = streak_key
                doc["total_score"] = float(doc.get("total_score", 0)) + 0.5
                msg += "；连续3天≥5分钟 +0.5"
    return msg


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def apply_action(
    user_id: str,
    action: str,
    *,
    value: Any = None,
    target_date: Optional[str] = None,
    note: str = "",
    now: Optional[datetime] = None,
) -> Tuple[dict, str]:
    """
    执行动作并持久化。返回 (doc, toast_message)。
    action: wake/sleep/arrive/leave/ot/diet/plane_tool/plane_notool/plane_minus/
            med_plus/med_minus/duo_plus/duo_minus/
            sleeptime/readtime/studytime/guitartime/sporttime/cost/reset
    """
    now = now or now_cn()
    today = now.date()
    doc = get_or_create_score(user_id)
    tip = ensure_sport_week_penalty(doc, today)
    msgs: List[str] = []
    if tip:
        msgs.append(tip)

    def parse_target(default: date) -> date:
        if target_date:
            return parse_date(target_date)
        return default

    if action == "wake":
        d = today
        day = day_bucket(doc, d)
        hhmm = fmt_hhmm(now)
        day["wake_at"] = hhmm
        sc = score_wake(hhmm)
        apply_replace_src(doc, day, "wake", sc)
        msgs.append(f"起床 {hhmm} → {sc:+g}")

    elif action == "sleep":
        d = logical_sleep_date(now)
        day = day_bucket(doc, d)
        hhmm = fmt_hhmm(now)
        day["sleep_at"] = hhmm
        offset = sleep_hour_offset(d, now)
        sc = score_sleep(offset)
        apply_replace_src(doc, day, "sleep", sc)
        msgs.append(f"睡觉(逻辑日 {date_str(d)}) {hhmm} ({offset:.2f}h) → {sc:+g}")

    elif action == "arrive":
        d = today
        day = day_bucket(doc, d)
        hhmm = fmt_hhmm(now)
        day["arrive_at"] = hhmm
        sc = score_arrive(hhmm)
        apply_replace_src(doc, day, "arrive", sc)
        msgs.append(f"到岗 {hhmm} → {sc:+g}")

    elif action == "leave":
        d = today
        # 凌晨下班：若 <12:00，逻辑日归前一天（与睡觉类似，便于 24 点后记分）
        if now.hour < 12:
            d = today - timedelta(days=1)
        day = day_bucket(doc, d)
        hhmm = fmt_hhmm(now)
        day["leave_at"] = hhmm
        sc = score_leave(hhmm, d, now)
        apply_replace_src(doc, day, "leave", sc)
        msgs.append(f"下班(逻辑日 {date_str(d)}) {hhmm} → {sc:+g}")

    elif action == "ot":
        day = day_bucket(doc, today)
        day["overtime"] = int(day.get("overtime", 0)) + 1
        add_delta(day, "overtime", 1.0)
        doc["total_score"] = float(doc.get("total_score", 0)) + 1.0
        msgs.append(f"加班 +1（今日第 {day['overtime']} 次）")

    elif action == "diet":
        msgs.append(apply_healthy_toggle(doc, today))

    elif action == "plane_tool":
        msgs.append(apply_plane_click(doc, today, "tool"))
    elif action == "plane_notool":
        msgs.append(apply_plane_click(doc, today, "notool"))
    elif action == "plane_minus":
        msgs.append(apply_plane_click(doc, today, "minus"))

    elif action == "med_plus":
        msgs.append(apply_meditate(doc, today, 1))
    elif action == "med_minus":
        msgs.append(apply_meditate(doc, today, -1))

    elif action == "duo_plus":
        day = day_bucket(doc, today)
        day["duolingo_delta"] = int(day.get("duolingo_delta", 0)) + 1
        add_delta(day, "duolingo", 1.0)
        doc["total_score"] = float(doc.get("total_score", 0)) + 1.0
        msgs.append("多邻国 +1")
    elif action == "duo_minus":
        day = day_bucket(doc, today)
        day["duolingo_delta"] = int(day.get("duolingo_delta", 0)) - 1
        add_delta(day, "duolingo", -1.0)
        doc["total_score"] = float(doc.get("total_score", 0)) - 1.0
        msgs.append("多邻国 -1")

    elif action == "sleeptime":
        hours = float(value)
        d = parse_target(today)
        day = day_bucket(doc, d)
        day["sleep_hours"] = hours
        sc = score_sleep_hours(hours)
        apply_replace_src(doc, day, "sleeptime", sc)
        msgs.append(f"{date_str(d)} 睡眠 {hours}h → {sc:+g}")

    elif action in ("readtime", "studytime", "guitartime", "sporttime"):
        minutes = float(value)
        d = parse_target(today)
        day = day_bucket(doc, d)
        field = {
            "readtime": "read_min",
            "studytime": "study_min",
            "guitartime": "guitar_min",
            "sporttime": "sport_min",
        }[action]
        day[field] = minutes
        sc = score_activity_minutes(minutes)
        apply_replace_src(doc, day, action, sc)
        msgs.append(f"{date_str(d)} {action} {minutes:g}m → {sc:+g}")

    elif action == "cost":
        rmb = float(value)
        if target_date:
            # yyyy-mm
            mk = target_date
        else:
            mk = month_key(today)
        months = doc.setdefault("months", {})
        m = months.setdefault(mk, {})
        m["cost_rmb"] = rmb
        sc = score_cost(rmb)
        # 冲销记在「当月最后一天」或用虚拟 day key month:cost
        # 用 months 内 deltas 简化：挂在当月 1 号 day
        y, mo = mk.split("-")
        d = date(int(y), int(mo), 1)
        day = day_bucket(doc, d)
        apply_replace_src(doc, day, "cost", sc, note=mk)
        m["cost_score"] = sc
        msgs.append(f"{mk} 花销 {rmb:g} → {sc:+g}")

    elif action == "reset":
        prev = float(doc.get("total_score", 0))
        new_score = float(value)
        doc["total_score"] = new_score
        doc.setdefault("resets", []).append(
            {
                "score": new_score,
                "note": note or "",
                "at": now.isoformat(),
                "prev": prev,
            }
        )
        msgs.append(f"重置分数 {prev:g} → {new_score:g}" + (f"（{note}）" if note else ""))

    else:
        msgs.append(f"未知动作: {action}")

    save_score(doc)
    return doc, "；".join(msgs)


# ---------------------------------------------------------------------------
# Summary + keyboard
# ---------------------------------------------------------------------------


def healthy_streak_count(doc: dict, today: date) -> int:
    n = 0
    d = today
    while True:
        day = doc.get("days", {}).get(date_str(d), {})
        if not day.get("healthy_diet"):
            break
        n += 1
        d -= timedelta(days=1)
    return n


def month_activity_sum(doc: dict, field: str, today: date) -> float:
    mk = month_key(today)
    total = 0.0
    for k, day in doc.get("days", {}).items():
        if k.startswith(mk):
            total += float(day.get(field, 0) or 0)
    return total


def build_summary_text(doc: dict, page: int = 1, toast: str = "") -> str:
    today = now_cn().date()
    day = doc.get("days", {}).get(date_str(today), empty_day())
    total = float(doc.get("total_score", 0))
    lines: List[str] = []
    if toast:
        lines.append(f"✓ {toast}")
        lines.append("")
    lines.append(f"📊 总分: {total:g}")
    lines.append(f"📅 今日 {date_str(today)}（东八区）· 键盘页 {page}/{SCORE_PAGES}")
    lines.append("")
    lines.append("—— 今日状态 ——")
    lines.append(
        f"☀ {day.get('wake_at') or '-'}  🌙 {day.get('sleep_at') or '-'}  "
        f"💻 {day.get('arrive_at') or '-'}  🚪 {day.get('leave_at') or '-'}"
    )
    lines.append(
        f"💪加班×{day.get('overtime', 0)}  🥗{'是' if day.get('healthy_diet') else '否'}  "
        f"✈️净计 {plane_net(day)} "
        f"(🛠{day.get('plane_with_tool', 0)}/"
        f"{day.get('plane_no_tool', 0)}/-{day.get('plane_minus', 0)})  "
        f"🧘{day.get('meditate_min', 0)}m  🦉{day.get('duolingo_delta', 0):+d}"
    )
    if day.get("sleep_hours") is not None:
        lines.append(f"睡眠时长: {day.get('sleep_hours')}h")

    lines.append("")
    lines.append("—— 时长（今日 / 本月累计）——")
    for label, field in (
        ("阅读", "read_min"),
        ("学习", "study_min"),
        ("吉他", "guitar_min"),
        ("运动", "sport_min"),
    ):
        t = float(day.get(field, 0) or 0)
        m = month_activity_sum(doc, field, today)
        lines.append(f"{label}: {t:g}m / {m:g}m")

    lines.append("")
    lines.append("—— 近况 ——")
    plane_bits = []
    for d in reversed(iter_dates(today, 4)):
        od = doc.get("days", {}).get(date_str(d), {})
        plane_bits.append(f"{d.strftime('%m-%d')}:{plane_net(od)}")
    lines.append("飞机近4日: " + " ".join(plane_bits))

    med_bits = []
    for d in reversed(iter_dates(today, 5)):
        od = doc.get("days", {}).get(date_str(d), {})
        med_bits.append(f"{d.strftime('%m-%d')}:{int(od.get('meditate_min', 0) or 0)}m")
    lines.append("冥想近5日: " + " ".join(med_bits))
    lines.append(f"健康饮食连续: {healthy_streak_count(doc, today)} 天")

    mk = month_key(today)
    cost = doc.get("months", {}).get(mk, {})
    if cost:
        lines.append(
            f"本月花销: {cost.get('cost_rmb', '-')} "
            f"(分 {cost.get('cost_score', score_cost(float(cost.get('cost_rmb', 0)))):+g})"
        )
    else:
        lines.append("本月花销: 未设置")

    wk = week_key(today)
    sport_week = sport_minutes_in_week(doc, wk)
    lines.append(f"本周运动: {sport_week}m（周键 {wk}）")
    prev_sunday = today - timedelta(days=today.isoweekday())
    prev_wk = week_key(prev_sunday)
    pw = doc.get("weeks", {}).get(prev_wk, {})
    if "sport_penalty_applied" in pw:
        lines.append(
            f"上周({prev_wk})已结算: {pw.get('sport_penalty_applied'):+g} "
            f"(运动 {pw.get('sport_minutes', '?')}m)"
        )
    else:
        lines.append(f"上周({prev_wk}): 尚未结算")

    # 今日 deltas 摘要
    deltas = day.get("deltas") or []
    if deltas:
        lines.append("")
        lines.append("—— 今日入账 ——")
        for x in deltas[-8:]:
            lines.append(f"· {x.get('src')}: {float(x.get('delta', 0)):+g}")

    # 消息内快捷命令（参数单位/日期格式写清楚）
    ds = date_str(today)
    lines.append("")
    lines.append("—— 动作命令（无参数，按当前东八区时刻记）——")
    lines.append("/score_wake 起床  /score_sleep 睡觉  /score_arrive 到岗  /score_leave 下班")
    lines.append("/score_ot 加班+1  /score_diet 健康饮食切换")
    lines.append("/score_plane_tool 飞机+(工具)  /score_plane_notool 飞机+  /score_plane_minus 飞机-")
    lines.append("/score_med_plus 冥想+1分钟  /score_med_minus 冥想-1分钟")
    lines.append("/score_duo_plus 多邻国+1分  /score_duo_minus 多邻国-1分")
    lines.append("")
    lines.append("—— 录入命令 ——")
    lines.append("日期 date = yyyy-mm-dd（如 " + ds + "）；省略则=今天")
    lines.append("月份 month = yyyy-mm（如 " + mk + "）；省略则=本月")
    lines.append("sleeptime: 睡眠时长，单位=小时(h)，可用小数")
    lines.append(f"/score sleeptime <小时h> [date]  例: /score sleeptime 7 {ds}")
    lines.append("read/study/guitar/sport: 当日累计时长，单位=分钟(m)，整数或小数")
    lines.append(f"/score readtime <分钟m> [date]  例: /score readtime 30 {ds}")
    lines.append(f"/score studytime <分钟m> [date]  例: /score studytime 30 {ds}")
    lines.append(f"/score guitartime <分钟m> [date]  例: /score guitartime 30 {ds}")
    lines.append(f"/score sporttime <分钟m> [date]  例: /score sporttime 30 {ds}")
    lines.append("cost: 当月花销，单位=人民币元(RMB)")
    lines.append(f"/score cost <金额RMB> [month]  例: /score cost 3500 {mk}")
    lines.append("reset: 将总分设为指定数值（可含小数），后跟备注文本")
    lines.append("/score reset <分数> <备注>  例: /score reset 0 月初清零")
    lines.append("")
    lines.append("—— 面板 ——")
    lines.append("/score 打开面板  /score_refresh 刷新")
    lines.append("/score_page_1|_2|_3 翻到对应页（N=页码1-3）")

    return "\n".join(lines)


def build_score_keyboard(page: int = 1):
    """Inline Keyboard：emoji 按钮 + callback_data。"""
    from telebot import types

    page = max(1, min(SCORE_PAGES, page))
    kb = types.InlineKeyboardMarkup()
    if page == 1:
        kb.row(
            types.InlineKeyboardButton("☀", callback_data="score:wake"),
            types.InlineKeyboardButton("🌙", callback_data="score:sleep"),
            types.InlineKeyboardButton("💻", callback_data="score:arrive"),
            types.InlineKeyboardButton("🚪", callback_data="score:leave"),
        )
    elif page == 2:
        kb.row(
            types.InlineKeyboardButton("💪", callback_data="score:ot"),
            types.InlineKeyboardButton("🥗", callback_data="score:diet"),
            types.InlineKeyboardButton("🛠✈", callback_data="score:plane:tool"),
            types.InlineKeyboardButton("✈", callback_data="score:plane:notool"),
            types.InlineKeyboardButton("❌✈", callback_data="score:plane:minus"),
        )
    else:
        kb.row(
            types.InlineKeyboardButton("🧘+", callback_data="score:med:+"),
            types.InlineKeyboardButton("🧘-", callback_data="score:med:-"),
            types.InlineKeyboardButton("🦉+", callback_data="score:duo:+"),
            types.InlineKeyboardButton("🦉-", callback_data="score:duo:-"),
        )

    prev_p = page - 1 if page > 1 else SCORE_PAGES
    next_p = page + 1 if page < SCORE_PAGES else 1
    kb.row(
        types.InlineKeyboardButton("◀️", callback_data=f"score:page:{prev_p}"),
        types.InlineKeyboardButton("🔄", callback_data="score:refresh"),
        types.InlineKeyboardButton("▶️", callback_data=f"score:page:{next_p}"),
    )
    return kb


SCORE_USAGE = (
    "用法（时区=东八区）\n"
    "\n"
    "面板:\n"
    "  /score — 打开积分面板\n"
    "  /score_refresh — 刷新\n"
    "  /score_page_<N> — 翻页，N=1|2|3\n"
    "\n"
    "动作（无参数，按点击时刻记录）:\n"
    "  /score_wake 起床  /score_sleep 睡觉\n"
    "  /score_arrive 到岗  /score_leave 下班\n"
    "  /score_ot 加班+1分  /score_diet 健康饮食开/关\n"
    "  /score_plane_tool 飞机+(带工具)\n"
    "  /score_plane_notool 飞机+(无工具)\n"
    "  /score_plane_minus 飞机-\n"
    "  /score_med_plus|/score_med_minus 冥想 ±1 分钟\n"
    "  /score_duo_plus|/score_duo_minus 多邻国 ±1 分\n"
    "\n"
    "录入（方括号=可选）:\n"
    "  date 格式=yyyy-mm-dd（例 2026-07-15），省略=今天\n"
    "  month 格式=yyyy-mm（例 2026-07），省略=本月\n"
    "  /score sleeptime <小时h> [date]\n"
    "      小时单位=小时，可用小数，例: /score sleeptime 7.5 2026-07-15\n"
    "  /score readtime|studytime|guitartime|sporttime <分钟m> [date]\n"
    "      分钟单位=分钟，例: /score readtime 30 2026-07-15\n"
    "  /score cost <金额RMB> [month]\n"
    "      金额单位=人民币元，例: /score cost 3500 2026-07\n"
    "  /score reset <分数> <备注>\n"
    "      分数=目标总分（可小数），备注=任意文本\n"
    "      例: /score reset 0 月初清零"
)


def _send_score_message(bot, chat_id, text, message=None, reply_markup=None):
    """发送积分消息；reply 目标不存在时回退为普通发送。"""
    from telebot import types

    reply_id = None
    if message:
        reply_id = message.get("message_id")
    kwargs = {}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    # 若曾留下 Reply Keyboard，顺带清掉
    if reply_markup is None:
        kwargs["reply_markup"] = types.ReplyKeyboardRemove()
    if reply_id is not None:
        try:
            return bot.send_message(
                chat_id, text, reply_to_message_id=reply_id, **kwargs
            )
        except Exception as e:
            err = str(e).lower()
            if "message to be replied not found" not in err and "replied message" not in err:
                raise
            print(f"score reply fallback (no reply_to): {e}", flush=True)
    return bot.send_message(chat_id, text, **kwargs)


def ensure_webhook_callback_updates(bot) -> Optional[str]:
    """确保 webhook 订阅 callback_query，否则 Inline 按钮不会推送。"""
    try:
        info = bot.get_webhook_info()
        url = getattr(info, "url", None) or ""
        allowed = list(getattr(info, "allowed_updates", None) or [])
        print(f"webhook url={url!r} allowed_updates={allowed!r}", flush=True)
        if not url:
            return "未设置 webhook"
        if not allowed or "callback_query" in allowed:
            return None
        new_allowed = list(dict.fromkeys(allowed + ["callback_query"]))
        secret = os.getenv("telegram_bot_api_secret_token")
        kwargs = {"url": url, "allowed_updates": new_allowed}
        if secret:
            kwargs["secret_token"] = secret
        ok = bot.set_webhook(**kwargs)
        print(f"updated webhook allowed_updates -> {new_allowed}, ok={ok}", flush=True)
        return f"已更新 webhook 订阅 callback_query"
    except Exception as e:
        print(f"ensure_webhook_callback_updates failed: {e}", flush=True)
        return None


def _get_ui_page(doc: dict) -> int:
    try:
        p = int(doc.get("ui_page", 1))
    except (TypeError, ValueError):
        p = 1
    return max(1, min(SCORE_PAGES, p))


def _set_ui_page(doc: dict, page: int) -> None:
    doc["ui_page"] = max(1, min(SCORE_PAGES, page))


def _reply_panel(bot, message: dict, doc: dict, page: int, toast: str = "") -> None:
    from telebot import types

    chat_id = message["chat"]["id"]
    # 先清掉可能残留的 Reply Keyboard（随后删除占位消息）
    try:
        tmp = bot.send_message(chat_id, "\u200b", reply_markup=types.ReplyKeyboardRemove())
        try:
            bot.delete_message(chat_id, tmp.message_id)
        except Exception:
            pass
    except Exception:
        pass
    text = build_summary_text(doc, page=page, toast=toast)
    _send_score_message(
        bot,
        chat_id,
        text,
        message=message,
        reply_markup=build_score_keyboard(page),
    )


def handle_score_command(message: dict, bot, command_args: List[str]) -> Tuple[int, str]:
    """处理 /score* 命令（含动作快捷命令）；面板使用 Inline Keyboard。"""
    user_id = str(message["from"]["id"])
    chat_id = message["chat"]["id"]
    command_args = list(command_args)
    cmd = command_args[0].split("@")[0]

    webhook_tip = ensure_webhook_callback_updates(bot)

    if cmd in SCORE_ACTION_COMMANDS:
        try:
            doc, toast = apply_action(user_id, SCORE_ACTION_COMMANDS[cmd])
            if webhook_tip:
                toast = f"{toast}；{webhook_tip}"
            _reply_panel(bot, message, doc, _get_ui_page(doc), toast=toast)
            return 0, f"Score action {cmd} ok"
        except Exception as e:
            _send_score_message(bot, chat_id, f"执行失败: {e}", message=message)
            return 1, f"score action error: {e}"

    if cmd.startswith("/score_page"):
        try:
            page = int(cmd.split("_")[-1])
        except (ValueError, IndexError):
            page = 1
        page = max(1, min(SCORE_PAGES, page))
        doc = get_or_create_score(user_id)
        tip = ensure_sport_week_penalty(doc)
        _set_ui_page(doc, page)
        save_score(doc)
        toast = tip or f"第 {page} 页"
        if webhook_tip:
            toast = f"{toast}；{webhook_tip}"
        _reply_panel(bot, message, doc, page, toast=toast)
        return 0, f"Score page {page}"

    if cmd == "/score_refresh":
        doc = get_or_create_score(user_id)
        tip = ensure_sport_week_penalty(doc)
        if tip:
            save_score(doc)
        toast = tip or "已刷新"
        if webhook_tip:
            toast = f"{toast}；{webhook_tip}"
        _reply_panel(bot, message, doc, _get_ui_page(doc), toast=toast)
        return 0, "Score refresh"

    if cmd != "/score":
        return 1, "not score command"

    if len(command_args) == 1:
        doc = get_or_create_score(user_id)
        tip = ensure_sport_week_penalty(doc)
        _set_ui_page(doc, 1)
        save_score(doc)
        toast_parts = [x for x in (tip, webhook_tip) if x]
        _reply_panel(bot, message, doc, 1, toast="；".join(toast_parts))
        return 0, "Score panel sent"

    sub = command_args[1].lower()
    try:
        if sub == "sleeptime":
            if len(command_args) < 3:
                _send_score_message(bot, chat_id, SCORE_USAGE, message=message)
                return 1, "usage"
            hours = float(command_args[2])
            d = command_args[3] if len(command_args) > 3 else None
            doc, toast = apply_action(user_id, "sleeptime", value=hours, target_date=d)
        elif sub in ("readtime", "studytime", "guitartime", "sporttime"):
            if len(command_args) < 3:
                _send_score_message(bot, chat_id, SCORE_USAGE, message=message)
                return 1, "usage"
            minutes = float(command_args[2])
            d = command_args[3] if len(command_args) > 3 else None
            doc, toast = apply_action(user_id, sub, value=minutes, target_date=d)
        elif sub == "cost":
            if len(command_args) < 3:
                _send_score_message(bot, chat_id, SCORE_USAGE, message=message)
                return 1, "usage"
            rmb = float(command_args[2])
            mk = command_args[3] if len(command_args) > 3 else None
            doc, toast = apply_action(user_id, "cost", value=rmb, target_date=mk)
        elif sub == "reset":
            if len(command_args) < 3:
                _send_score_message(bot, chat_id, SCORE_USAGE, message=message)
                return 1, "usage"
            score_val = float(command_args[2])
            note = " ".join(command_args[3:]) if len(command_args) > 3 else ""
            doc, toast = apply_action(user_id, "reset", value=score_val, note=note)
        else:
            _send_score_message(bot, chat_id, SCORE_USAGE, message=message)
            return 1, "unknown subcommand"

        _reply_panel(bot, message, doc, _get_ui_page(doc), toast=toast)
        return 0, f"Score {sub} ok"
    except Exception as e:
        _send_score_message(
            bot, chat_id, f"执行失败: {e}\n\n{SCORE_USAGE}", message=message
        )
        return 1, f"score error: {e}"


def handle_score_callback(callback_query: dict, bot) -> Tuple[int, str]:
    """处理 score:* Inline 回调。"""
    data = callback_query.get("data", "")
    user_id = str(callback_query.get("from", {}).get("id", ""))
    cq_id = callback_query.get("id")
    message = callback_query.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if not data.startswith("score:"):
        return 1, "not score callback"

    try:
        bot.answer_callback_query(cq_id, text="…")
    except Exception as e:
        print(f"answer_callback_query early failed: {e}", flush=True)

    payload = data[len("score:") :]
    page = 1
    try:
        body = message.get("text") or ""
        for part in body.split("\n"):
            if "键盘页" in part and "/" in part:
                page = int(part.split("键盘页")[-1].strip().split("/")[0])
                break
    except Exception:
        page = 1

    toast = ""
    try:
        if payload.startswith("page:"):
            page = int(payload.split(":")[1])
            doc = get_or_create_score(user_id)
            tip = ensure_sport_week_penalty(doc)
            _set_ui_page(doc, page)
            save_score(doc)
            toast = tip or f"第 {page} 页"
        elif payload == "refresh":
            doc = get_or_create_score(user_id)
            tip = ensure_sport_week_penalty(doc)
            if tip:
                save_score(doc)
            page = _get_ui_page(doc)
            toast = tip or "已刷新"
        else:
            action = CALLBACK_ACTION_MAP.get(payload)
            if not action:
                return 1, "unknown button"
            doc, toast = apply_action(user_id, action)
            page = _get_ui_page(doc)

        text = build_summary_text(doc, page=page, toast=toast)
        kb = build_score_keyboard(page)
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        except Exception as e:
            err = str(e).lower()
            if "message is not modified" in err:
                pass
            else:
                print(f"edit_message_text failed, fallback send: {e}", flush=True)
                bot.send_message(chat_id, text, reply_markup=kb)
        return 0, f"score callback ok: {toast}"
    except Exception as e:
        print(f"score callback error: {e}", flush=True)
        try:
            if chat_id:
                bot.send_message(chat_id, f"积分操作失败: {e}")
        except Exception:
            pass
        return 1, f"score callback error: {e}"


# ---------------------------------------------------------------------------
# Lightweight self-checks (no Mongo)
# ---------------------------------------------------------------------------


def _self_check() -> None:
    assert score_wake("05:59") == 2.0
    assert score_wake("06:04") == 2.0
    assert score_wake("06:05") == 1.5
    assert score_wake("07:04") == 1.5
    assert score_wake("08:04") == 1.0
    assert score_wake("08:05") == 0.0
    assert score_wake("09:00") == -1.0

    assert score_sleep(21.9) == 2.0
    assert score_sleep(22.0) == 2.0
    assert score_sleep(22 + 4 / 60) == 2.0
    assert score_sleep(22 + 6 / 60) == 1.5
    assert score_sleep(23 + 6 / 60) == 1.0
    assert score_sleep(24 + 6 / 60) == 0.0
    assert score_sleep(26.0) == -1.0
    assert score_sleep(27.0) == -2.0

    assert score_arrive("07:59") == 2.0
    assert score_arrive("08:04") == 2.0
    assert score_arrive("09:00") == 1.0
    assert score_arrive("10:00") == -1.0
    assert score_arrive("10:30") == -2.0
    assert score_arrive("11:00") == -4.0

    assert score_sleep_hours(7) == 0
    assert score_sleep_hours(6.9) == -1
    assert score_sleep_hours(5.1) == -2
    assert score_sleep_hours(5) == -2
    assert score_sleep_hours(4) == -3

    assert score_activity_minutes(29) == 0
    assert score_activity_minutes(30) == 0.5
    assert score_activity_minutes(59) == 0.5
    assert score_activity_minutes(60) == 1.0

    assert score_cost(2999) == 1.0
    assert score_cost(4000) == 0.0
    assert score_cost(4000.1) == -1.0
    assert score_cost(5000) == -1.0
    assert score_cost(5000.1) == -2.0
    assert score_cost(6000) == -2.0
    assert score_cost(6000.1) == -3.0

    assert score_sport_week(0) == -2
    assert score_sport_week(30) == -1
    assert score_sport_week(60) == 0

    d = date(2026, 7, 15)
    click = datetime(2026, 7, 15, 23, 30, tzinfo=TZ_CN)
    assert score_leave("23:30", d, click) == 1.0
    click2 = datetime(2026, 7, 16, 0, 30, tzinfo=TZ_CN)
    assert score_leave("00:30", d, click2) == 2.0

    # covering replace
    day = empty_day()
    doc = {"total_score": 0.0, "days": {"2026-07-15": day}}
    apply_replace_src(doc, day, "wake", 2.0)
    assert abs(doc["total_score"] - 2.0) < 1e-9
    apply_replace_src(doc, day, "wake", 1.0)
    assert abs(doc["total_score"] - 1.0) < 1e-9

    # sport week marker idempotent
    doc2 = {
        "total_score": 0.0,
        "days": {},
        "weeks": {"2026-W28": {"sport_penalty_applied": -2, "sport_minutes": 0}},
    }
    assert ensure_sport_week_penalty(doc2, date(2026, 7, 13)) is None
    assert abs(doc2["total_score"]) < 1e-9

    # first settlement for previous week
    doc3 = {"total_score": 0.0, "days": {}, "weeks": {}}
    # 2026-07-13 is Monday; previous week W28 ends 2026-07-12
    tip = ensure_sport_week_penalty(doc3, date(2026, 7, 13))
    assert tip is not None
    assert "sport_penalty_applied" in doc3["weeks"][week_key(date(2026, 7, 12))]
    tip2 = ensure_sport_week_penalty(doc3, date(2026, 7, 13))
    assert tip2 is None  # no double count
    assert abs(doc3["total_score"] + 2.0) < 1e-9  # sport 0 → -2

    # plane day penalties
    doc4 = {"total_score": 0.0, "days": {}}
    t = date(2026, 7, 15)
    msg = apply_plane_click(doc4, t, "tool")
    assert "四日无记录+工具" in msg
    assert abs(doc4["total_score"] - 0.5) < 1e-9
    apply_plane_click(doc4, t, "notool")  # net=2 → -1 → total -0.5
    assert abs(doc4["total_score"] + 0.5) < 1e-9
    scored_after_two = doc4["total_score"]
    apply_plane_click(doc4, t, "notool")  # net=3 → extra -1
    assert abs(doc4["total_score"] - (scored_after_two - 1.0)) < 1e-9

    # healthy streak once
    doc5 = {"total_score": 0.0, "days": {}}
    y = date(2026, 7, 14)
    day_bucket(doc5, y)["healthy_diet"] = True
    apply_healthy_toggle(doc5, date(2026, 7, 15))
    assert abs(doc5["total_score"] - 0.5) < 1e-9
    # toggle off and on again should not re-award
    apply_healthy_toggle(doc5, date(2026, 7, 15))  # off
    apply_healthy_toggle(doc5, date(2026, 7, 15))  # on
    assert abs(doc5["total_score"] - 0.5) < 1e-9

    # meditate streak
    doc6 = {"total_score": 0.0, "days": {}}
    day_bucket(doc6, date(2026, 7, 13))["meditate_min"] = 5
    day_bucket(doc6, date(2026, 7, 14))["meditate_min"] = 5
    # simulate minutes via apply_meditate five times
    for _ in range(5):
        apply_meditate(doc6, date(2026, 7, 15), 1)
    assert any(x.get("src") == "meditate_streak" for x in day_bucket(doc6, date(2026, 7, 15))["deltas"])
    total_before = doc6["total_score"]
    apply_meditate(doc6, date(2026, 7, 15), 1)
    # streak not awarded twice
    streak_deltas = [
        x
        for x in day_bucket(doc6, date(2026, 7, 15))["deltas"]
        if x.get("src") == "meditate_streak"
    ]
    assert len(streak_deltas) == 1
    assert abs(doc6["total_score"] - total_before) < 1e-9  # +0 from minutes still <30

    print("score self-check passed")


if __name__ == "__main__":
    _self_check()
