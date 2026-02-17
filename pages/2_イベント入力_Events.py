# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, date as Date
import re
import pandas as pd
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs, read_json, write_json

BASE_DIR = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="利用者：イベント入力 / User: Events", page_icon="📅", layout="wide")
st.header("利用者：イベント入力 / User: Event Requests")

chosen = ym_selector(resolve_ym())
ym = chosen.ym
paths = ensure_month_dirs(BASE_DIR, ym)

pref_path = paths["data_dir"] / "preferences.json"
event_path = paths["data_dir"] / "events.json"

prefs = read_json(pref_path, default={})
events: list[dict] = read_json(event_path, default=[])

st.caption(f"通常の保存先 / Default save: data/{ym}/events.json（※別月の日付を選ぶと、その月の events.json に自動保存します）")

teams = sorted(prefs.keys())
team = st.selectbox("団体 / Team", options=teams + ["（新規追加 / New）"], index=0 if teams else 0)
if team == "（新規追加 / New）":
    team = st.text_input("新規団体名 / New team name")

# Limit selectable dates to the chosen month
first_day = Date(chosen.year, chosen.month, 1)
if chosen.month == 12:
    next_first = Date(chosen.year + 1, 1, 1)
else:
    next_first = Date(chosen.year, chosen.month + 1, 1)
last_day = next_first - timedelta(days=1)

# Default date: today if within month, else first day
_today = datetime.now().date()
default_date = _today if (first_day <= _today <= last_day) else first_day

colA, colB = st.columns(2)
with colA:
    date = st.date_input("日付 / Date", value=default_date, min_value=first_day, max_value=last_day)
with colB:
    start = st.text_input("開始（例 18:00）/ Start (e.g. 18:00)", value="18:00")

st.caption("イベントは **4時間固定** です（終了は自動計算）。/ Event duration is **fixed to 4 hours** (end is auto).")

note = st.text_input("メモ（任意）/ Note (optional)", value="")

def _normalize_hhmm(s: str) -> str | None:
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"

if st.button("イベント希望を追加 / Add", type="primary"):
    if not team:
        st.error("団体名を入力してください / Please enter team name")
        st.stop()

    start_norm = _normalize_hhmm(start)
    if not start_norm:
        st.error("開始時刻は HH:MM 形式で入力してください / Start time must be HH:MM")
        st.stop()

    dt_start = datetime.combine(date, datetime.strptime(start_norm, "%H:%M").time())

    item = {
        "team": team,
        "date": str(date),
        "start": start_norm,         # normalized
        "duration_hours": 4,         # fixed duration
        "note": note,
    }
    target_ym = f"{date.year:04d}-{date.month:02d}"
    if target_ym != ym:
        # Save into the month selected by the event date
        t_paths = ensure_month_dirs(BASE_DIR, target_ym)
        t_event_path = t_paths["data_dir"] / "events.json"
        t_events: list[dict] = read_json(t_event_path, default=[])
        t_events.append(item)
        write_json(t_event_path, t_events)
        st.success(f"追加しました / Added（※ {target_ym} の events.json に保存しました）")
    else:
        events.append(item)
        write_json(event_path, events)
        st.success("追加しました / Added")

st.markdown("---")
st.subheader("他団体のイベント希望（一覧）/ Other teams' event requests")
st.caption("※ 行番号 / Row は **入力した順番** です / Row number is the **input order**")

if events:
    # Keep original row id for deletion
    rows = []
    for i, e in enumerate(events, start=1):
        row = {"行番号 / Row": i}
        row.update(e)
        rows.append(row)

    df = pd.DataFrame(rows)

    # Ensure legacy files are supported
    # - New format: start + duration_hours (no 'end' stored)
    # - Legacy format: may have 'end' and/or missing 'duration_hours' / 'note'
    if "duration_hours" not in df.columns:
        df["duration_hours"] = 4
    df["duration_hours"] = df["duration_hours"].fillna(4)

    def _calc_end(row) -> str:
        try:
            # If legacy 'end' exists and is non-empty, respect it for display
            if "end" in row and row.get("end"):
                return str(row.get("end"))
            v = str(row.get("start", "")).strip()
            if not v:
                return ""
            t = datetime.strptime(v, "%H:%M")
            dh = row.get("duration_hours", 4)
            try:
                dh = float(dh)
            except Exception:
                dh = 4
            t2 = (t + timedelta(hours=dh)).time()
            return t2.strftime("%H:%M")
        except Exception:
            return ""

    df["end"] = df.apply(_calc_end, axis=1)

    if "note" not in df.columns:
        df["note"] = ""
    else:
        df["note"] = df["note"].fillna("")
# Sorting for readability (but keep row id)
    if {"date","start"}.issubset(df.columns):
        df = df.sort_values(["date", "start", "team"], kind="stable")

    # Filters
    filt_team = st.multiselect(
        "表示する団体（空=全て）/ Filter teams (empty=all)",
        options=sorted(df["team"].unique().tolist())
    )
    if filt_team:
        df = df[df["team"].isin(filt_team)]

    # Render as HTML table (no pyarrow)
    show = df[["行番号 / Row", "team", "date", "start", "end", "note"]].copy()
    show.columns = ["行番号 / Row", "団体 / Team", "日付 / Date", "開始 / Start", "終了 / End", "メモ / Note"]
    st.markdown(show.to_html(index=False, escape=True), unsafe_allow_html=True)

    st.markdown("#### 削除 / Delete")
    visible_rows = show["行番号 / Row"].tolist()
    if visible_rows:
        del_row = st.selectbox("削除する行番号 / Row to delete", options=visible_rows)
        if st.button("この行を削除 / Delete selected row", type="secondary"):
            events.pop(int(del_row) - 1)
            write_json(event_path, events)
            st.success(f"削除しました / Deleted row {del_row}")
            st.rerun()
else:
    st.info("まだイベント希望はありません / No events yet")
