"""
strategies/choc_detector.py
Mendeteksi Change of Character (CHoCH) pada Lower Timeframe (LTF)
berdasarkan Timeframe Setup (HTF).
"""
import pandas as pd
from core.mt5_connector import fetch_ohlcv

class ChocDetector:
    def __init__(self, lookback_period: int = 20, recent_exclude: int = 5):
        self.lookback_period = lookback_period
        self.recent_exclude = recent_exclude

    def check(self, symbol: str, htf: str, direction: str) -> bool:
        """
        Mengecek apakah terjadi CHoCH pada LTF sesuai dengan arah sinyal HTF.

        Args:
            symbol: Pair yang discan (misal: "XAUUSD")
            htf: Timeframe setup utama (misal: "H1")
            direction: 'BUY' atau 'SELL'

        Return:
            True jika CHoCH terkonfirmasi di LTF, False jika tidak.
        """
        # 1. Mapping HTF (Setup) ke LTF (Konfirmasi)
        # Anda bisa menyesuaikan mapping ini sesuai preferensi trading Anda
        ltf_mapping = {
            'M15': 'M1',
            'M30': 'M3',
            'H1': 'M5',
            'H4': 'M15',
            'D1': 'H1'
        }

        ltf = ltf_mapping.get(htf, 'M15') # Default ke M15 jika TF tidak dikenali

        # 2. Fetch data khusus untuk LTF (ambil 30-40 candle LTF cukup untuk lookback 20)
        df_ltf = fetch_ohlcv(symbol, ltf, bars=40)

        if df_ltf is None or len(df_ltf) < self.lookback_period + 2:
            return False

        # 3. Tentukan Level Swing High/Low dari periode lookback di LTF
        # (Mengambil data dari indeks -(lookback+1) sampai -1, mengabaikan candle LTF saat ini)
        lookback = self.lookback_period
        past_highs = float(df_ltf['high'].iloc[-(lookback + 1) : -1].max())
        past_lows = float(df_ltf['low'].iloc[-(lookback + 1) : -1].min())

        # 4. Kondisi Candle LTF Saat Ini (Candle terakhir / iloc[-1])
        current_close = float(df_ltf['close'].iloc[-1])

        # 5. Logika CHoCH (Menggunakan Close untuk menghindari fakeout/wick di LTF)
        if direction == 'BUY':
            # CHoCH BUY: Harga close di LTF berhasil break di atas Swing High LTF sebelumnya
            return current_close > past_highs

        elif direction == 'SELL':
            # CHoCH SELL: Harga close di LTF berhasil break di bawah Swing Low LTF sebelumnya
            return current_close < past_lows

        return False
