"""core/logger.py"""
"""Sistem logging terpusat"""

from datetime import datetime
import streamlit as st


def get_logs() -> list:
    """Ambil list log dari session state"""
    if 'logs' not in st.session_state:
        st.session_state.logs = []
    return st.session_state.logs


def add_log(message: str):
    """Tambahkan pesan log dengan timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    logs = get_logs()
    logs.append(f"[{timestamp}] {message}")
    # Batasi maksimal 150 log
    if len(logs) > 150:
        st.session_state.logs = logs[-150:]


def clear_logs():
    """Hapus semua log"""
    st.session_state.logs = []
