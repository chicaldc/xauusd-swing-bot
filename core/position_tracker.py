"""core/position_tracker.py"""
"""
Module khusus untuk melacak posisi (order) yang sedang terbuka di MT5.
Terpisah agar mudah di-maintenance dan dikembangkan.
Support Cloud (demo) & Lokal (MT5 real).
"""

import pandas as pd
from datetime import datetime
import os
import streamlit as st

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
        print("ℹ️ Position Tracker: Cloud mode - fitur tracking posisi tidak tersedia")


def get_open_positions(symbol: str = None) -> pd.DataFrame:
    """
    Mengambil semua posisi aktif (trades yang sedang berjalan) di MT5.
    
    Args:
        symbol: (Opsional) Filter berdasarkan pair tertentu, misal "XAUUSD".
                Jika None, akan mengambil semua pair di seluruh akun.
    
    Returns:
        DataFrame berisi detail posisi, atau DataFrame kosong jika tidak ada posisi.
    """
    # ==========================================
    # MODE CLOUD: Return DataFrame kosong
    # ==========================================
    if not MT5_AVAILABLE:
        # Return DataFrame kosong dengan struktur kolom yang sama
        # agar tidak error di UI
        return pd.DataFrame(columns=[
            'ticket', 'symbol', 'type_str', 'volume', 
            'price_open', 'price_current', 'sl', 'tp', 
            'profit', 'profit_pips', 'time_open', 'duration'
        ])

    # ==========================================
    # MODE LOKAL: Pakai MetaTrader5
    # ==========================================
    if symbol:
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()

    if positions is None or len(positions) == 0:
        return pd.DataFrame()

    # Konversi data MT5 ke Pandas DataFrame
    df = pd.DataFrame(list(positions), columns=positions[0]._asdict().keys())
    
    # Format waktu open agar mudah dibaca (YYYY-MM-DD HH:MM)
    df['time_open'] = pd.to_datetime(df['time'], unit='s').dt.strftime('%Y-%m-%d %H:%M')
    
    # Hitung durasi posisi (HH:MM:SS)
    now = datetime.now()
    df['duration'] = df['time'].apply(lambda x: str(now - datetime.fromtimestamp(x)).split('.')[0])

    # Hitung estimasi Profit dalam Pips (Universal untuk 5-digit & JPY 3-digit)
    def calc_pips(row):
        info = mt5.symbol_info(row['symbol'])
        if info is None or info.point == 0:
            return 0.0
        
        point = info.point
        if row['type'] == 0:  # BUY
            pips = (row['price_current'] - row['price_open']) / point / 10
        else:  # SELL
            pips = (row['price_open'] - row['price_current']) / point / 10
        return round(pips, 1)

    df['profit_pips'] = df.apply(calc_pips, axis=1)
    
    # Format tipe order agar lebih ramah di UI
    df['type_str'] = df['type'].map({0: '🟢 BUY', 1: '🔴 SELL'})

    # Pilih hanya kolom yang penting untuk ditampilkan di dashboard
    columns_to_keep = [
        'ticket', 'symbol', 'type_str', 'volume', 
        'price_open', 'price_current', 'sl', 'tp', 
        'profit', 'profit_pips', 'time_open', 'duration'
    ]
    
    # Pastikan semua kolom ada (antisipasi jika MT5 return data tidak lengkap)
    existing_cols = [col for col in columns_to_keep if col in df.columns]
    return df[existing_cols]


def get_portfolio_summary() -> dict:
    """
    Mengambil ringkasan cepat keseluruhan portofolio (Floating P/L, Total Posisi).
    """
    # ==========================================
    # MODE CLOUD: Return data kosong
    # ==========================================
    if not MT5_AVAILABLE:
        return {
            'total_positions': 0, 
            'total_profit': 0.0, 
            'buy_count': 0, 
            'sell_count': 0
        }

    # ==========================================
    # MODE LOKAL: Pakai MetaTrader5
    # ==========================================
    positions = mt5.positions_get()
    
    if positions is None or len(positions) == 0:
        return {
            'total_positions': 0, 
            'total_profit': 0.0, 
            'buy_count': 0, 
            'sell_count': 0
        }

    total_profit = sum(pos.profit for pos in positions)
    buy_count = sum(1 for pos in positions if pos.type == 0)
    sell_count = sum(1 for pos in positions if pos.type == 1)

    return {
        'total_positions': len(positions),
        'total_profit': round(total_profit, 2),
        'buy_count': buy_count,
        'sell_count': sell_count
    }
