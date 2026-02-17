# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import calendar
from datetime import date as Date
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs, read_yaml, write_yaml
from ui_utils.runner import run_allocator

BASE_DIR = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="管理者：設定と実行 / Admin", page_icon="🛠", layout="wide")
st.header("管理者：設定と実行 / Admin: Settings & Run")

chosen = ym_selector(resolve_ym())
ym = chosen.ym
paths = ensure_month_dirs(BASE_DIR, ym)

data_dir = paths["data_dir"]
out_dir = paths["out_dir"]
config_path = data_dir / "config.yaml"

st.caption(f"設定保存先 / Save to: data/{ym}/config.yaml")

# Load existing or default
cfg = read_yaml(config_path, default=None)
if not cfg:
    year, month = map(int, ym.split("-"))
    cfg = {
        "year": year,
        "month": month,
        "min_slots": 3,
        "max_solve_seconds": 60,
        "availability": {},
    }

year_i, month_i = map(int, ym.split("-"))
last_day = calendar.monthrange(year_i, month_i)[1]

col1, col2 = st.columns(2)
with col1:
    cfg["min_slots"] = st.number_input(
        "min_slots（最低枠数 / min slots）",
        min_value=1, max_value=20,
        value=int(cfg.get("min_slots", 3))
    )
with col2:
    cfg["max_solve_seconds"] = st.number_input(
        "max_solve_seconds（最大計算秒 / max seconds）",
        min_value=5, max_value=600,
        value=int(cfg.get("max_solve_seconds", 60))
    )

st.subheader("利用可能時間（選択式）/ Availability (select)")
st.write("各日ごとに「開始・終了」を選ぶだけです。/ Just select start/end for each day.")
st.write("※ 2枠（開始2/終了2）も必要なら設定できます（任意）。/ Slot2 is optional.")

# Time options (30-min steps)
def _time_options():
    opts = ["（利用不可 / Unavailable）"]
    for h in range(6, 24):
        for m in (0, 30):
            opts.append(f"{h:02d}:{m:02d}")
    return opts

TIME_OPTS = _time_options()

def _row_to_sel(row_val):
    # row: [start1,end1,start2,end2] with None
    row = row_val or [None, None, None, None]
    row = (row + [None, None, None, None])[:4]
    def conv(x):
        return x if x else "（利用不可 / Unavailable）"
    return [conv(row[0]), conv(row[1]), conv(row[2]), conv(row[3])]

def _sel_to_row(sel):
    def conv(x):
        return None if (x == "（利用不可 / Unavailable）" or x == "" or x is None) else x
    return [conv(sel[0]), conv(sel[1]), conv(sel[2]), conv(sel[3])]

avail = cfg.get("availability", {}) or {}

# Ensure availability has ALL days (default: unavailable) so users don't need to save 'unavailable' manually.
# Normalize keys to strings 1..last_day.
_default_row = [None, None, None, None]
_normalized = {}
for k, v in (avail or {}).items():
    try:
        kk = str(int(k))
    except Exception:
        kk = str(k)
    _normalized[kk] = (v if isinstance(v, list) else _default_row)
avail = _normalized
_changed = False
for d in range(1, last_day + 1):
    if str(d) not in avail:
        avail[str(d)] = _default_row.copy()
        _changed = True
if _changed:
    cfg["availability"] = avail
    write_yaml(config_path, cfg)


# Bulk set
with st.expander("まとめて設定 / Bulk set", expanded=False):
    st.write("平日/土日をまとめて設定できます。/ Apply settings to weekdays/weekends.")
    b1, b2, b3 = st.columns(3)
    with b1:
        apply_to = st.selectbox("対象 / Apply to", ["全日 / All days", "平日 / Weekdays", "土日 / Weekends"])
    with b2:
        bulk_start = st.selectbox("開始 / Start", TIME_OPTS, index=TIME_OPTS.index("08:30") if "08:30" in TIME_OPTS else 0)
    with b3:
        bulk_end = st.selectbox("終了 / End", TIME_OPTS, index=TIME_OPTS.index("21:00") if "21:00" in TIME_OPTS else 0)

    bulk_slot2 = st.checkbox("2枠も設定 / Also set slot2", value=False)
    if bulk_slot2:
        c4, c5 = st.columns(2)
        with c4:
            bulk_start2 = st.selectbox("開始2 / Start2", TIME_OPTS, index=0)
        with c5:
            bulk_end2 = st.selectbox("終了2 / End2", TIME_OPTS, index=0)
    else:
        bulk_start2, bulk_end2 = "（利用不可 / Unavailable）", "（利用不可 / Unavailable）"

    if st.button("適用 / Apply", type="secondary"):
        for d in range(1, last_day + 1):
            wd = Date(year_i, month_i, d).weekday()  # Mon=0
            is_weekend = wd >= 5
            if apply_to == "平日 / Weekdays" and is_weekend:
                continue
            if apply_to == "土日 / Weekends" and not is_weekend:
                continue
            avail[str(d)] = _sel_to_row([bulk_start, bulk_end, bulk_start2, bulk_end2])
        cfg["availability"] = avail
        write_yaml(config_path, cfg)
        st.success("適用しました / Applied")
        st.rerun()

st.markdown("### 日別設定 / Per-day settings")

for day in range(1, last_day + 1):
    key = str(day)
    row = avail.get(key) or avail.get(day) or [None, None, None, None]
    s1, e1, s2, e2 = _row_to_sel(row)

    wd = Date(year_i, month_i, day).weekday()
    wd_ja = ["月","火","水","木","金","土","日"][wd]
    wd_en = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][wd]

    with st.expander(f"{day}日（{wd_ja}/{wd_en}）/ Day {day}", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        s1_sel = c1.selectbox("開始1 / Start1", TIME_OPTS, index=TIME_OPTS.index(s1) if s1 in TIME_OPTS else 0, key=f"d{day}_s1")
        e1_sel = c2.selectbox("終了1 / End1", TIME_OPTS, index=TIME_OPTS.index(e1) if e1 in TIME_OPTS else 0, key=f"d{day}_e1")
        s2_sel = c3.selectbox("開始2 / Start2", TIME_OPTS, index=TIME_OPTS.index(s2) if s2 in TIME_OPTS else 0, key=f"d{day}_s2")
        e2_sel = c4.selectbox("終了2 / End2", TIME_OPTS, index=TIME_OPTS.index(e2) if e2 in TIME_OPTS else 0, key=f"d{day}_e2")

        new_row = _sel_to_row([s1_sel, e1_sel, s2_sel, e2_sel])

        # Save if changed
        if st.button("この日の設定を保存 / Save this day", key=f"save_day_{day}"):
            avail[key] = new_row
            cfg["availability"] = avail
            write_yaml(config_path, cfg)
            st.success("保存しました / Saved")

st.markdown("---")
st.subheader("割り当て実行 / Run allocation")

st.write("このボタンは **sourcecode/main.py を変更せず** そのまま実行します。/ This runs sourcecode/main.py as-is.")

if st.button("▶ 実行 / Run", type="primary"):
    # Ensure year/month consistency
    cfg["year"] = year_i
    cfg["month"] = month_i
    cfg["availability"] = avail
    write_yaml(config_path, cfg)

    result = run_allocator(BASE_DIR, config_path, ym)
    if result.ok:
        st.success("完了 / Done")
    else:
        st.error("失敗 / Failed")
    st.code(result.log, language="text")