# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import streamlit as st

from ui_utils.month import resolve_ym, ym_selector
from ui_utils.storage import ensure_month_dirs

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="春日体育館 割り当てシステム / Kasuga Gym Allocator", layout="wide")

st.title("春日体育館 割り当てシステム / Kasuga Gym Allocation System")

current = resolve_ym()
chosen = ym_selector(current)
ym = chosen.ym
ensure_month_dirs(BASE_DIR, ym)

st.markdown("---")
st.subheader(f"ホーム / Home（{ym}）")

st.write("左のサイドバーの **Pages** から移動できます。 / Use the left sidebar **Pages** to navigate.")

# Quick links (visual cues)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.page_link("pages/1_希望日入力_Preferences.py", label="利用者：希望日入力 / User: Preferred dates", icon="🗓️")
with col2:
    st.page_link("pages/2_イベント入力_Events.py", label="利用者：イベント入力 / User: Event requests", icon="🎯")
with col3:
    st.page_link("pages/3_結果表示_Results.py", label="結果の詳細表示 / Results", icon="📊")
with col4:
    st.page_link("pages/9_管理者用ページ_Admin.py", label="管理者：設定と実行 / Admin", icon="🛠️")


