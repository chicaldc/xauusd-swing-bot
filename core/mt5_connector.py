"""core/mt5_connector.py"""
"""Wrapper untuk koneksi MetaTrader 5"""

import MetaTrader5 as mt5
import pandas as pd
import streamlit as st

# ✅ HAPUS 'TIMEFRAMES' dari import ini, biarkan hanya BARS_TO_FETCH
from config.settings import BARS_TO_FETCH

@st.cache_resource
def initialize_mt5():
    """Inisialisasi koneksi MT5 (singleton)"""
    if not mt5.initialize():
        return False, f"MT5 init error: {mt5.last_error()}"

    terminal = mt5.terminal_info()
    if terminal is None or not terminal.connected:
        return False, "MT5 tidak terhubung ke server"

    return True, "OK"

def get_timeframe_const(tf_name: str):
    """Konversi string timeframe ke konstanta MT5"""
    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return tf_map.get(tf_name, mt5.TIMEFRAME_H1)

def get_xauusd_symbol() -> str | None:
    """
    Mencari simbol XAUUSD yang valid, menangani perbedaan akhiran broker
    (misal: XAUUSD, XAUUSDm, XAUUSDpro, XAUUSDc).
    """
    all_symbols = mt5.symbols_get()
    if not all_symbols:
        return None

    # Filter simbol yang 'visible' (ada di Market Watch) dan mengandung 'XAUUSD'
    candidates = [
        s.name for s in all_symbols
        if s.visible and "XAUUSD" in s.name.upper()
    ]

    if not candidates:
        return None

    # Prioritaskan "XAUUSD" tanpa akhiran jika tersedia
    if "XAUUSD" in candidates:
        return "XAUUSD"

    # Jika tidak ada yang polos, kembalikan kandidat pertama yang diurutkan
    # (Pengurutan memastikan konsistensi, misal selalu memilih 'XAUUSDc' daripada 'XAUUSDm' jika keduanya ada)
    return sorted(candidates)[0]

def fetch_xauusd_ohlcv(tf_name: str, bars: int = BARS_TO_FETCH) -> pd.DataFrame | None:
    """
    Ambil data OHLCV khusus untuk XAUUSD.
    Otomatis menyesuaikan dengan nama simbol yang digunakan broker (mengatasi masalah akhiran).
    """
    symbol = get_xauusd_symbol()

    if not symbol:
        st.error("Simbol XAUUSD tidak ditemukan di Market Watch MT5. Pastikan sudah ditambahkan.")
        return None

    # Gunakan fungsi fetch_ohlcv yang sudah ada
    return fetch_ohlcv(symbol, tf_name, bars)

def fetch_ohlcv(symbol: str, tf_name: str, bars: int = BARS_TO_FETCH) -> pd.DataFrame | None:
    """Ambil data OHLCV dari MT5."""
    if not mt5.symbol_select(symbol, True):
        return None

    rates = mt5.copy_rates_from_pos(symbol, get_timeframe_const(tf_name), 0, bars)

    if rates is None or len(rates) < 7:
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['time_str'] = df['time'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df = df.rename(columns={'tick_volume': 'volume'})

    return df[['time', 'time_str', 'open', 'high', 'low', 'close', 'volume']]

def get_visible_symbols() -> list:
    """Ambil daftar simbol yang sedang 'Visible' di Market Watch MT5."""
    symbols = mt5.symbols_get()
    if symbols is None:
        return []
    return sorted([s.name for s in symbols if s.visible])
