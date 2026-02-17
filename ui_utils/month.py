from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import streamlit as st

TOKYO = ZoneInfo("Asia/Tokyo")
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class YearMonth:
    year: int
    month: int

    @property
    def ym(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def _tokyo_now() -> datetime:
    return datetime.now(TOKYO)


def resolve_ym() -> YearMonth:
    """
    Resolve Year-Month with priority:
    1) st.session_state["ym"]
    2) URL query (?ym=YYYY-MM)
    3) current month (Tokyo)
    """
    # 1) session_state
    ss_ym = st.session_state.get("ym")
    if isinstance(ss_ym, str) and YM_RE.match(ss_ym):
        y, m = ss_ym.split("-")
        return YearMonth(int(y), int(m))

    # 2) query params
    qp = st.query_params
    ym = qp.get("ym")
    if isinstance(ym, list):
        ym = ym[0] if ym else None
    if isinstance(ym, str) and YM_RE.match(ym):
        st.session_state["ym"] = ym  # ★ここで保存
        y, m = ym.split("-")
        return YearMonth(int(y), int(m))

    # 3) default (Tokyo now)
    now = _tokyo_now()
    default = YearMonth(now.year, now.month)
    st.session_state["ym"] = default.ym  # ★初期値も保存
    return default


def ym_selector(current: YearMonth) -> YearMonth:
    """Sidebar selector for year-month, persist in session_state (and optionally URL)."""
    st.sidebar.markdown("### 対象月（YYYY-MM）/ Target month")

    years = list(range(current.year - 2, current.year + 3))
    months = list(range(1, 13))

    year = st.sidebar.selectbox(
        "年 / Year",
        years,
        index=years.index(current.year),
        key="ym_year",
    )

    month = st.sidebar.selectbox(
        "月 / Month",
        months,
        index=months.index(current.month),
        key="ym_month",
    )

    chosen = YearMonth(int(year), int(month))

    # ★ページ移動しても保持される保存先
    st.session_state["ym"] = chosen.ym

    # URLは「変わった時だけ」同期（任意だけど便利）
    qp = st.query_params
    cur_qp = qp.get("ym")
    if isinstance(cur_qp, list):
        cur_qp = cur_qp[0] if cur_qp else None
    if chosen.ym != cur_qp:
        st.query_params["ym"] = chosen.ym

    return chosen
