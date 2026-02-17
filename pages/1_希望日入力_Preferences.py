# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import calendar
from datetime import date as Date
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs, read_json, write_json
from ui_utils.month import resolve_ym, ym_selector

st.set_page_config(page_title="利用者：希望日入力 / User: Preferences", page_icon="✅", layout="wide")


BASE_DIR = Path(__file__).resolve().parents[1]

current = resolve_ym()
chosen = ym_selector(current)
ym = chosen.ym
paths = ensure_month_dirs(BASE_DIR, ym)
# Predefined teams (editable here)
DEFAULT_TEAMS = ['KickChat T-ACT', "SPIKERS'inc", 'ULISバドミントン部', 'ULISバレーボール部', '中国留学生学友会', '医学フットサル同好会', 'インドネシア学友会']

st.header("利用者：希望日入力 / User: Preferred Dates")

pref_path = paths["data_dir"] / "preferences.json"

prefs = read_json(pref_path, default={})

# Team list: predefined first, then any existing in file
teams = []
for t in list(DEFAULT_TEAMS) + sorted(prefs.keys()):
    if t and t not in teams:
        teams.append(t)

st.caption(f"保存先 / Save to: data/{ym}/preferences.json")

team = st.selectbox("団体 / Team", options=teams + ["（新規追加 / New）"], index=0 if teams else 0)
if team == "（新規追加 / New）":
    team = st.text_input("新規団体名 / New team name")

if not team:
    st.stop()

existing = set(prefs.get(team, []))

st.subheader("希望日の入力 / Preferred dates")

year_i, month_i = map(int, ym.split("-"))
last_day = calendar.monthrange(year_i, month_i)[1]

all_days = st.checkbox("全ての日 / All days", value=(len(existing) == last_day))

st.caption("📱 スマホではカレンダー表示が縦に崩れやすいので、**リスト表示（スマホ推奨）** を用意しています。")
mode = st.radio(
    "表示モード / Mode",
    ["リスト表示（スマホ推奨）/ List (mobile)", "カレンダー表示 / Calendar (desktop)"],
    index=0,
    horizontal=False
)

checked: list[str] = []

def _weekday_labels():
    return ["月","火","水","木","金","土","日"], ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

if all_days:
    checked = [f"{ym}-{d:02d}" for d in range(1, last_day + 1)]
else:
    if mode.startswith("リスト表示"):
        # Mobile-friendly: multiselect list
        ja, en = _weekday_labels()
        options = []
        label_to_date = {}
        for d in range(1, last_day + 1):
            wd = Date(year_i, month_i, d).weekday()
            d_str = f"{ym}-{d:02d}"
            label = f"{d}日（{ja[wd]}/{en[wd]}）"
            options.append(label)
            label_to_date[label] = d_str

        default_labels = [lbl for lbl, ds in label_to_date.items() if ds in existing]
        selected = st.multiselect(
            "希望日を選択 / Select preferred dates",
            options=options,
            default=default_labels,
        )
        checked = [label_to_date[lbl] for lbl in selected]
    else:
        # Calendar-like grid (7 columns) - good for desktop
        st.write("各日付にチェックを入れるだけで登録できます。 / Just check the dates you want.")
        week_cols = st.columns(7)
        weekdays_ja, weekdays_en = _weekday_labels()
        for i in range(7):
            week_cols[i].markdown(f"**{weekdays_ja[i]} / {weekdays_en[i]}**")

        first_weekday = Date(year_i, month_i, 1).weekday()  # Monday=0

        cells = []
        for _ in range(first_weekday):
            cells.append(None)
        for d in range(1, last_day + 1):
            cells.append(d)

        for idx, d in enumerate(cells):
            col = week_cols[idx % 7]
            if d is None:
                # keep same height to avoid uneven spacing
                col.checkbox(" ", value=False, disabled=True, key=f"pref_empty_{ym}_{team}_{idx}")
                continue

            d_str = f"{ym}-{d:02d}"
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
