# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import os
import re
import pandas as pd
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs
from ui_utils.month import resolve_ym, ym_selector

st.set_page_config(page_title="結果の詳細表示 / Results", page_icon="📊", layout="wide")

BASE_DIR = Path(__file__).resolve().parents[1]
current = resolve_ym()
chosen = ym_selector(current)
ym = chosen.ym
paths = ensure_month_dirs(BASE_DIR, ym)

st.title("結果の詳細表示 / Results")

out_dir: Path = paths["out_dir"]

st.caption(f"読み込み先 / Load from: output/{ym}/")

file_schedule = out_dir / f"schedule_{ym}.csv"
file_calendar = out_dir / f"calendar_{ym}.png"
file_gantt = out_dir / f"gantt_{ym}.png"
file_monthly_summary = out_dir / f"monthly_summary_{ym}.png"
file_group_schedule = out_dir / f"group_schedule_{ym}.png"

tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 予約を検索・確認 / Search & View",
    "🗓 カレンダー / Calendar",
    "📈 利用時間全体像 / Overview",
    "👥 団体別利用時間 / By Team",
])

# --- Tab 1: Search schedule ---
with tab1:
    st.subheader("🔍 予約を検索・確認 / Search & View bookings")

    if file_schedule.exists():
        try:
            df = pd.read_csv(file_schedule, encoding="utf-8")
        except Exception:
            df = pd.read_csv(file_schedule, encoding="cp932")

        # Search & jump
        c1, c2 = st.columns([3, 1])
        with c1:
            search = st.text_input(
                "🔍 サークル名や日付で検索 / Search by team or date",
                placeholder="例 / e.g.: ULIS / 01-10"
            )
        with c2:
            date_options = ["全表示 / All"] + df["Date"].astype(str).tolist() if "Date" in df.columns else ["全表示 / All"]
            target_date = st.selectbox("📅 日付へジャンプ / Jump to date", date_options)

        display_df = df.copy()
        if "Date" in display_df.columns:
            display_df["Date"] = display_df["Date"].astype(str)

        if target_date != "全表示 / All" and "Date" in display_df.columns:
            display_df = display_df[display_df["Date"] == target_date]
        elif search:
            display_df = display_df[display_df.apply(lambda r: r.astype(str).str.contains(search, case=False).any(), axis=1)]

        st.markdown("---")

        # Card layout (single column, mobile friendly)
        for _, row in display_df.iterrows():
            date_str = str(row.get("Date", ""))
            blocks_str = str(row.get("Blocks", ""))
            lines = blocks_str.split("\n")

            filtered_lines = []
            for line in lines:
                if not line.strip():
                    continue
                if not search or search.lower() in line.lower() or search.lower() in date_str.lower():
                    time_match = re.search(r"(\d{1,2}:\d{2}-\d{1,2}:\d{2})", line)
                    if time_match:
                        time_part = time_match.group(1)
                        team_part = line.replace(time_part, "").strip()
                        filtered_lines.append(
                            f"<p style='margin: 1px 0; font-size: 14px;'><b>{time_part}</b> : {team_part}</p>"
                        )
                    else:
                        filtered_lines.append(
                            f"<p style='margin: 1px 0; font-size: 14px;'>{line}</p>"
                        )

            if filtered_lines:
                st.markdown(
                    f"""
                    <div style="background-color: #f8f9fa; padding: 10px; border-radius: 8px; margin-bottom: 12px; border-left: 5px solid #007bff; box-shadow: 1px 1px 3px rgba(0,0,0,0.1);">
                        <h3 style="margin: 0 0 5px 0; font-size: 16px; color: #333;">📅 {date_str}</h3>
                        {''.join(filtered_lines)}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    else:
        st.warning("スケジュールCSVが見つかりません / Schedule CSV not found。まず管理者ページで割り当てを実行してください / Please run allocation in Admin page.")

# --- Tab 2: Calendar ---
with tab2:
    st.subheader("🗓 カレンダー / Calendar")
    if file_calendar.exists():
        st.image(str(file_calendar), use_container_width=True, caption=f"カレンダー / Calendar ({ym})")
    else:
        st.info(f"画像が見つかりません / Not found: {file_calendar.name}")

# --- Tab 3: Overview ---
with tab3:
    st.subheader("📈 利用時間全体像 / Overview")
    st.markdown("### ガントチャート / Gantt")
    if file_gantt.exists():
        st.image(str(file_gantt), use_container_width=True, caption=f"ガントチャート / Gantt ({ym})")
    else:
        st.info(f"画像が見つかりません / Not found: {file_gantt.name}")

    st.markdown("### 公平性 / Fairness")
    if file_monthly_summary.exists():
        st.image(str(file_monthly_summary), use_container_width=True, caption=f"公平性 / Fairness ({ym})")
    else:
        st.info(f"画像が見つかりません / Not found: {file_monthly_summary.name}")

# --- Tab 4: By team ---
with tab4:
    st.subheader("👥 団体別利用時間 / By Team usage")
    if file_group_schedule.exists():
        st.image(str(file_group_schedule), use_container_width=True, caption=f"団体別 / By Team ({ym})")
    else:
        st.info(f"画像が見つかりません / Not found: {file_group_schedule.name}")
