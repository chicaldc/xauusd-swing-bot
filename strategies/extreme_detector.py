"""
strategies/extreme_detector.py
Mendeteksi kondisi Extreme di Lower Timeframe (LTF) berdasarkan MA3 dan Bollinger Bands.
"""
import pandas as pd
import numpy as np
from core.mt5_connector import fetch_ohlcv

def get_extreme_info(symbol: str, htf: str, direction: str) -> tuple:
    """
    Mengecek kondisi LTF untuk mendeteksi apakah setup berada di area Extreme.
    Return: (is_extreme: bool, message: str)
    """
    # Mapping HTF ke LTF yang sesuai
    ltf_mapping = {'M15': 'M1', 'M30': 'M3', 'H1': 'M5', 'H4': 'M15', 'D1': 'H1'}
    ltf = ltf_mapping.get(htf)

    if not ltf:
        return False, "🔹 Info LTF tidak tersedia"

    # Ambil data LTF secara mandiri (Scanner tidak perlu repot fetch data LTF)
    df_ltf = fetch_ohlcv(symbol, ltf, bars=30)
    if df_ltf is None or len(df_ltf) < 25:
        return False, "🔹 Data LTF belum cukup"

    # Hitung MA 3 LWMA (High & Low)
    weights = np.array([1, 2, 3])
    weight_sum = weights.sum()

    df_ltf['ma3_high'] = df_ltf['high'].rolling(window=3).apply(lambda x: np.dot(x, weights) / weight_sum, raw=True)
    df_ltf['ma3_low'] = df_ltf['low'].rolling(window=3).apply(lambda x: np.dot(x, weights) / weight_sum, raw=True)

    # Hitung Bollinger Bands (20, 2.0)
    df_ltf['bb_mid'] = df_ltf['close'].rolling(window=20).mean()
    df_ltf['bb_std'] = df_ltf['close'].rolling(window=20).std()
    df_ltf['bb_upper'] = df_ltf['bb_mid'] + (df_ltf['bb_std'] * 2.0)
    df_ltf['bb_lower'] = df_ltf['bb_mid'] - (df_ltf['bb_std'] * 2.0)

    try:
        # Menggunakan iloc[-2] untuk menghindari noise candle yang sedang berjalan (Shift 1)
        curr_ma3_low = float(df_ltf['ma3_low'].iloc[-2])
        curr_bb_lower = float(df_ltf['bb_lower'].iloc[-2])

        curr_ma3_high = float(df_ltf['ma3_high'].iloc[-2])
        curr_bb_upper = float(df_ltf['bb_upper'].iloc[-2])

        if direction == 'BUY':
            # Extreme BUY: MA3 Low menyentuh atau menembus Lower BB
            is_extreme = curr_ma3_low <= curr_bb_lower
            msg = "🌟 EXTREME (Bonus!)" if is_extreme else "🔹 Normal"
            return is_extreme, msg

        elif direction == 'SELL':
            # Extreme SELL: MA3 High menyentuh atau menembus Upper BB
            is_extreme = curr_ma3_high >= curr_bb_upper
            msg = "🌟 EXTREME (Bonus!)" if is_extreme else "🔹 Normal"
            return is_extreme, msg

    except Exception as e:
        return False, f"🔹 Error hitung LTF"

    return False, "🔹 Tidak terdeteksi"
