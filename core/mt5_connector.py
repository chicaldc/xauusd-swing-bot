"""core/mt5_connector.py"""
"""Wrapper untuk koneksi MetaTrader 5 - Support Cloud & Lokal"""

import pandas as pd
import streamlit as st
import os

# ✅ HAPUS 'TIMEFRAMES' dari import ini, biarkan hanya BARS_TO_FETCH
from config.settings import BARS_TO_FETCH

# ============================================
# DETEKSI ENVIRONMENT (Cloud vs Lokal)
# ============================================
IS_CLOUD = os.path.exists('/mount/src') or 'STREAMLIT_SERVER' in os.environ

# Coba import MetaTrader5 (hanya akan sukses di Windows lokal)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None
    if IS_CLOUD:
        print("ℹ️ Running di Streamlit Cloud - MT5 tidak tersedia, pakai yfinance sebagai fallback")
    else:
        print("⚠️ MetaTrader5 tidak terinstall di sistem ini")

# Import yfinance sebagai fallback untuk cloud
if not MT5_AVAILABLE:
    import yfinance as yf


# ============================================
# FUNGSI INISIALISASI
# ============================================
@st.cache_resource
def initialize_mt5():
    """Inisialisasi koneksi MT5 (singleton)"""
    if not MT5_AVAILABLE:
        # Mode cloud - tidak perlu inisialisasi, pakai yfinance
        return True, "OK (Cloud Mode - yfinance)"

    if not mt5.initialize():
        return False, f"MT5 init error: {mt5.last_error()}"

    terminal = mt5.terminal_info()
    if terminal is None or not terminal.connected:
        return False, "MT5 tidak terhubung ke server"

    return True, "OK"


# ============================================
# FUNGSI TIMEFRAME
# ============================================
def get_timeframe_const(tf_name: str):
    """Konversi string timeframe ke konstanta MT5"""
    if not MT5_AVAILABLE:
        return None  # Tidak dipakai di cloud mode

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


def _tf_to_yfinance_interval(tf_name: str) -> str:
    """Konversi timeframe ke interval yfinance"""
    tf_map = {
        "M1": "1m",
        "M5": "5m",
        "M15": "15m",
        "M30": "30m",
        "H1": "1h",
        "H4": "1h",  # yfinance tidak punya 4h, pakai 1h lalu resample
        "D1": "1d",
    }
    return tf_map.get(tf_name, "1h")


def _tf_to_yfinance_period(tf_name: str, bars: int) -> str:
    """Konversi timeframe + jumlah bar ke period yfinance"""
    # Estimasi period berdasarkan timeframe
    if tf_name in ["M1", "M5"]:
        return "5d"  # yfinance batasi data intraday max 7 hari
    elif tf_name in ["M15", "M30"]:
        return "30d"
    elif tf_name == "H1":
        return "60d"
    elif tf_name == "H4":
        return "120d"
    elif tf_name == "D1":
        return "1y"
    return "60d"


# ============================================
# FUNGSI SYMBOL
# ============================================
def get_xauusd_symbol() -> str | None:
    """
    Mencari simbol XAUUSD yang valid.
    - Lokal: dari MT5 Market Watch
    - Cloud: langsung return 'GC=F' (Yahoo Finance Gold Futures)
    """
    if not MT5_AVAILABLE:
        return "GC=F"  # Yahoo Finance symbol untuk Gold

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

    return sorted(candidates)[0]


# ============================================
# FUNGSI FETCH DATA (INTI)
# ============================================
def fetch_xauusd_ohlcv(tf_name: str, bars: int = BARS_TO_FETCH) -> pd.DataFrame | None:
    """
    Ambil data OHLCV khusus untuk XAUUSD.
    Otomatis menyesuaikan dengan nama simbol yang digunakan broker.
    """
    symbol = get_xauusd_symbol()

    if not symbol:
        st.error("Simbol XAUUSD tidak ditemukan. Pastikan sudah ditambahkan ke Market Watch.")
        return None

    return fetch_ohlcv(symbol, tf_name, bars)


def fetch_ohlcv(symbol: str, tf_name: str, bars: int = BARS_TO_FETCH) -> pd.DataFrame | None:
    """Ambil data OHLCV - support MT5 (lokal) dan yfinance (cloud)."""

    # ==========================================
    # MODE CLOUD: Pakai yfinance
    # ==========================================
    if not MT5_AVAILABLE:
        try:
            interval = _tf_to_yfinance_interval(tf_name)
            period = _tf_to_yfinance_period(tf_name, bars)

            # Download data dari Yahoo Finance
            data = yf.download(symbol, period=period, interval=interval, progress=False)

            if data is None or data.empty:
                return None

            # Flatten MultiIndex columns jika ada (yfinance versi baru)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            # Convert ke format yang sama dengan MT5
            df = pd.DataFrame()
            df['time'] = data.index
            df['open'] = data['Open'].values
            df['high'] = data['High'].values
            df['low'] = data['Low'].values
            df['close'] = data['Close'].values
            df['volume'] = data['Volume'].values if 'Volume' in data.columns else 0

            # Resample jika timeframe H4 (karena yfinance tidak support 4h)
            if tf_name == "H4":
                df.set_index('time', inplace=True)
                df = df.resample('4h').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna()
                df.reset_index(inplace=True)

            # Ambil hanya jumlah bars yang diminta
            df = df.tail(bars).reset_index(drop=True)

            # Tambah kolom time_str untuk kompatibilitas
            df['time_str'] = df['time'].dt.strftime('%Y-%m-%d %H:%M:%S')

            return df[['time', 'time_str', 'open', 'high', 'low', 'close', 'volume']]

        except Exception as e:
            st.error(f"Error mengambil data dari yfinance: {e}")
            return None

    # ==========================================
    # MODE LOKAL: Pakai MetaTrader5
    # ==========================================
    else:
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


# ============================================
# FUNGSI VISIBLE SYMBOLS
# ============================================
def get_visible_symbols() -> list:
    """Ambil daftar simbol yang sedang 'Visible' di Market Watch MT5."""
    if not MT5_AVAILABLE:
        # Mode cloud - return list default untuk demo
        return ["GC=F", "SI=F", "CL=F", "EURUSD=X", "GBPUSD=X"]

    symbols = mt5.symbols_get()
    if symbols is None:
        return []
    return sorted([s.name for s in symbols if s.visible])
