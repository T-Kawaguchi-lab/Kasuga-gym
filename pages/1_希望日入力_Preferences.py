# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import calendar
from datetime import date as Date
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs, read_json, write_json

BASE_DIR = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="利用者：希望日入力 / User: Preferences", page_icon="✅", layout="wide")
st.header("利用者：希望日入力 / User: Preferred Dates")

chosen = ym_selector(resolve_ym())
ym = chosen.ym
paths = ensure_month_dirs(BASE_DIR, ym)

pref_path = paths["data_dir"] / "preferences.json"

prefs = read_json(pref_path, default={})
teams = sorted(prefs.keys())

st.caption(f"保存先 / Save to: data/{ym}/preferences.json")

team = st.selectbox("団体 / Team", options=teams + ["（新規追加 / New）"], index=0 if teams else 0)
if team == "（新規追加 / New）":
    team = st.text_input("新規団体名 / New team name")

if not team:
    st.stop()

existing = set(prefs.get(team, []))

st.subheader("希望日のチェック / Check preferred dates")
st.write("各日付にチェックを入れるだけで登録できます。 / Just check the dates you want.")

year_i, month_i = map(int, ym.split("-"))
last_day = calendar.monthrange(year_i, month_i)[1]

all_days = st.checkbox("全ての日 / All days", value=(len(existing) == last_day))

# NOTE:
# Streamlit の checkbox は key ごとに状態が保持されるため、
# 「全ての日」を後から ON にしても各日の checkbox 状態が自動で揃わないことがあります。
# ここでは、全ての日が ON のときは **全日を選択した扱い** にして保存します。
checked: list[str] = []

# Calendar-like grid (7 columns)
week_cols = st.columns(7)
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
for i, w in enumerate(weekdays):
    week_cols[i].markdown(f"**{w} / {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i]}**")

first_weekday = (Date(year_i, month_i, 1).weekday())  # Monday=0

cells = []
for _ in range(first_weekday):
    cells.append(None)
for d in range(1, last_day + 1):
    cells.append(d)

for idx, d in enumerate(cells):
    col = week_cols[idx % 7]
    if d is None:
        # 1週目に日付が無い場合でも、日付セルと同じ高さの空白を確保して段差を無くす
        col.checkbox(" ", value=False, disabled=True, key=f"pref_empty_{ym}_{team}_{idx}")
        continue

    d_str = f"{ym}-{d:02d}"

    if all_days:
        # 「全ての日」ON のときは各日を選択済みとして扱う（表示も固定）
        col.checkbox(str(d), value=True, disabled=True, key=f"pref_{ym}_{team}_{d}")
        checked.append(d_str)
    else:
        default_val = (d_str in existing)
        val = col.checkbox(str(d), value=default_val, key=f"pref_{ym}_{team}_{d}")
        if val:
            checked.append(d_str)
if st.button("保存 / Save", type="primary"):
    prefs[team] = sorted(set(checked))
    write_json(pref_path, prefs)
    st.success("保存しました / Saved")

st.markdown("---")
st.subheader("現在の登録状況 / Current records")
st.json(prefs)
