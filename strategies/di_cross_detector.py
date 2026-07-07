"""
strategies/di_cross_detector.py
Detector independen untuk ADX, DI+/DI-, persilangan DI, dan ADX in Range DI
"""
import pandas as pd
import numpy as np


class DiCrossDetector:
    def __init__(self, period: int = 14, lookback: int = 4, di_threshold: float = 20.0):
        self.period = period
        self.lookback = lookback
        self.di_threshold = di_threshold  # ✅ Threshold untuk ADX in Range

    def analyze(self, df: pd.DataFrame, direction: str = None, adx_threshold: int = 25) -> dict:
        """
        Analisis lengkap: ADX, +DI, -DI, DI Spread, Status ADX, deteksi cross, dan ADX in Range.

        Args:
            df: DataFrame OHLCV
            direction: 'BUY' atau 'SELL' untuk cek cross & ADX in Range. None jika hanya butuh data ADX.
            adx_threshold: Threshold minimum ADX untuk klasifikasi kekuatan tren.

        Returns:
            dict dengan keys:
                - adx (float): Nilai ADX terakhir
                - plus_di (float): Nilai +DI terakhir
                - minus_di (float): Nilai -DI terakhir
                - di_spread (float): Selisih +DI - -DI
                - adx_status (str): 🟢 STRONG / 🟡 MODERATE / 🔴 WEAK
                - di_crossed (bool): Apakah terjadi cross sesuai direction dalam lookback
                - adx_in_range (bool): ✅ BARU - Apakah ADX di antara +DI dan -DI dengan dominasi arah
                - adx_in_range_msg (str): ✅ BARU - Pesan status ADX in Range
        """
        default_result = {
            'adx': 0.0,
            'plus_di': 0.0,
            'minus_di': 0.0,
            'di_spread': 0.0,
            'adx_status': 'N/A',
            'di_crossed': False,
            'adx_in_range': False,
            'adx_in_range_msg': '⚪ ADX-R: N/A'
        }

        if df is None or len(df) < (self.period * 2 + 2):
            return default_result

        try:
            # 1. Directional Movement (+DM / -DM)
            high_diff = df['high'].diff()
            low_diff = -df['low'].diff()

            plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
            minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)

            # 2. True Range (TR)
            tr = pd.concat([
                df['high'] - df['low'],
                (df['high'] - df['close'].shift(1)).abs(),
                (df['low'] - df['close'].shift(1)).abs()
            ], axis=1).max(axis=1)

            # 3. Wilder's Smoothing (EWM dengan alpha = 1/period)
            alpha = 1 / self.period
            smoothed_tr = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, 1e-10)
            smoothed_plus_dm = plus_dm.ewm(alpha=alpha, adjust=False).mean()
            smoothed_minus_dm = minus_dm.ewm(alpha=alpha, adjust=False).mean()

            # 4. +DI dan -DI
            di_plus = 100 * (smoothed_plus_dm / smoothed_tr)
            di_minus = 100 * (smoothed_minus_dm / smoothed_tr)

            # 5. DX dan ADX
            di_sum = (di_plus + di_minus).replace(0, 1e-10)
            dx = 100 * (di_plus - di_minus).abs() / di_sum
            adx = dx.ewm(alpha=alpha, adjust=False).mean()

            # 6. Ambil nilai terakhir (handle NaN)
            final_adx = float(adx.iloc[-1])
            final_plus_di = float(di_plus.iloc[-1])
            final_minus_di = float(di_minus.iloc[-1])

            if np.isnan(final_adx):
                final_adx = 0.0
            if np.isnan(final_plus_di):
                final_plus_di = 0.0
            if np.isnan(final_minus_di):
                final_minus_di = 0.0

            final_di_spread = final_plus_di - final_minus_di

            # 7. Klasifikasi status ADX (dinamis mengikuti threshold dari UI)
            if final_adx >= (adx_threshold + 10):
                adx_status = "🟢 Strong"
            elif final_adx >= adx_threshold:
                adx_status = "🟡 Moderate"
            else:
                adx_status = "🔴 Weak"

            # 8. Deteksi cross DI sesuai arah (jika direction diberikan)
            di_crossed = False
            if direction is not None:
                if direction == 'BUY':
                    cross_condition = (di_plus > di_minus) & (di_plus.shift(1) <= di_minus.shift(1))
                else:
                    cross_condition = (di_minus > di_plus) & (di_minus.shift(1) <= di_plus.shift(1))
                di_crossed = bool(cross_condition.iloc[-self.lookback:].any())

            # ✅ 9. ADX in Range DI (BARU)
            adx_in_range = False
            adx_in_range_msg = '⚪ ADX-R: N/A'

            if direction is not None:
                # Cek apakah ADX berada di antara +DI dan -DI
                di_min = min(final_plus_di, final_minus_di)
                di_max = max(final_plus_di, final_minus_di)
                adx_between_di = di_min <= final_adx <= di_max

                if not adx_between_di:
                    adx_in_range_msg = '⚪ ADX-R: ADX di luar range DI'
                else:
                    # Cek dominasi arah
                    if direction == 'BUY':
                        di_dominant_ok = (final_plus_di > self.di_threshold) and (final_minus_di < self.di_threshold)
                        if di_dominant_ok:
                            adx_in_range = True
                            adx_in_range_msg = '🎯 ADX-R: BUY'
                        else:
                            adx_in_range_msg = '⚪ ADX-R: TIDAK'

                    elif direction == 'SELL':
                        di_dominant_ok = (final_minus_di > self.di_threshold) and (final_plus_di < self.di_threshold)
                        if di_dominant_ok:
                            adx_in_range = True
                            adx_in_range_msg = '🎯 ADX-R: SELL'
                        else:
                            adx_in_range_msg = '⚪ ADX-R: TIDAK'

            return {
                'adx': final_adx,
                'plus_di': final_plus_di,
                'minus_di': final_minus_di,
                'di_spread': final_di_spread,
                'adx_status': adx_status,
                'di_crossed': di_crossed,
                'adx_in_range': adx_in_range,
                'adx_in_range_msg': adx_in_range_msg
            }

        except Exception:
            return default_result

    def check(self, df: pd.DataFrame, direction: str) -> bool:
        """Wrapper backward-compatible: hanya mengembalikan apakah cross terjadi."""
        return self.analyze(df, direction)['di_crossed']
