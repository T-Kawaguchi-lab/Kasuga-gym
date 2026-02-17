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
    """Resolve Year-Month from URL (?ym=YYYY-MM) else default to current month (Tokyo)."""
    qp = st.query_params
    ym = qp.get("ym")
    if isinstance(ym, list):
        ym = ym[0] if ym else None

    if isinstance(ym, str) and YM_RE.match(ym):
        y, m = ym.split("-")
        return YearMonth(int(y), int(m))

    now = _tokyo_now()
    return YearMonth(now.year, now.month)


def ym_selector(current: YearMonth) -> YearMonth:
    """Sidebar selector for year-month and keep URL in sync."""
    st.sidebar.markdown("### 対象月（YYYY-MM）/ Target month")

    # Show a reasonable range: current year +/- 2
    years = list(range(current.year - 2, current.year + 3))
    year = st.sidebar.selectbox("年 / Year", years, index=years.index(current.year))

    months = list(range(1, 13))
    month = st.sidebar.selectbox("月 / Month", months, index=months.index(current.month))

    chosen = YearMonth(int(year), int(month))
    st.query_params["ym"] = chosen.ym
    return chosen
