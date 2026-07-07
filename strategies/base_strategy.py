"""strategies/base_strategy.py"""
"""Base class untuk semua strategi - memastikan interface yang konsisten"""
from abc import ABC, abstractmethod
import pandas as pd

# PENANDA: Jika ini muncul di terminal, berarti file ini yang terbaca
print("✅ BERHASIL MEMUAT: base_strategy.py VERSI BARU (dengan validity_candles)")

class BaseStrategy(ABC):
    """Abstract base class untuk strategi trading"""
    
    def __init__(self, name: str, icon: str = "📊", validity_candles: int = 3):
        self.name = name
        self.icon = icon
        self.validity_candles = validity_candles
    
    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str, tf_name: str) -> dict:
        """
        Analisis data dan kembalikan signal (jika ada).
        """
        pass
    
    @staticmethod
    def detect_swing_points(df: pd.DataFrame, window: int = 3) -> pd.DataFrame:
        """Helper: deteksi swing high/low menggunakan rolling window"""
        df = df.copy()
        df['swing_high'] = df['high'].rolling(window=2*window+1, center=True).max()
        df['swing_low'] = df['low'].rolling(window=2*window+1, center=True).min()
        df['is_swing_high'] = df['high'] == df['swing_high']
        df['is_swing_low'] = df['low'] == df['swing_low']
        return df
