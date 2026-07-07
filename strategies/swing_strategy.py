"""
/strategies/swing_strategy.py
Murni Detektor Pola Swing & Zona
"""

import pandas as pd
from strategies.base_strategy import BaseStrategy
from utils.helpers import format_price

class SwingStrategy(BaseStrategy):

    def __init__(self):
        super().__init__(
            name="Swing Zone",
            icon="📊",
            validity_candles=3
        )

    def analyze(self, df: pd.DataFrame, symbol: str, tf_name: str) -> dict:

        if df is None or len(df) < 10:
            return None

        if not all(col in df.columns for col in ['high', 'low', 'close']):
            return None

        current_price = float(df['close'].iloc[-1])

        conf_high  = float(df['high'].iloc[-2])
        conf_low   = float(df['low'].iloc[-2])
        conf_close = float(df['close'].iloc[-2])

        swing_high = float(df['high'].iloc[-3])
        swing_low  = float(df['low'].iloc[-3])

        # Candle index mengikuti konvensi MT5 (bar[2] = c2, bar[3] = c3, dst)
        c2 = float(df['close'].iloc[-3])
        c3 = float(df['close'].iloc[-4])
        c4 = float(df['close'].iloc[-5])
        c5 = float(df['close'].iloc[-6])

        h3 = float(df['high'].iloc[-4])   # bar[3] high
        l3 = float(df['low'].iloc[-4])    # bar[3] low

        range_conf = conf_high - conf_low

        if range_conf <= 0:
            return None

        # =========================
        # LWMA-3 (periode 3, shift 2 dan 3)
        # Bobot: candle terbaru = 3, tengah = 2, terlama = 1
        # =========================

        ma_h_shift3 = (
            df['high'].iloc[-6] * 1 +
            df['high'].iloc[-5] * 2 +
            df['high'].iloc[-4] * 3
        ) / 6.0

        ma_h_shift2 = (
            df['high'].iloc[-5] * 1 +
            df['high'].iloc[-4] * 2 +
            df['high'].iloc[-3] * 3
        ) / 6.0

        ma_l_shift3 = (
            df['low'].iloc[-6] * 1 +
            df['low'].iloc[-5] * 2 +
            df['low'].iloc[-4] * 3
        ) / 6.0

        ma_l_shift2 = (
            df['low'].iloc[-5] * 1 +
            df['low'].iloc[-4] * 2 +
            df['low'].iloc[-3] * 3
        ) / 6.0

        # =========================
        # SWING ORIGINAL
        # 3 candle trending + konfirmasi break
        # =========================

        is_sh = (
            (c4 < c3) and
            (c3 < c2) and
            (conf_close < swing_low)
        )

        is_sl = (
            (c4 > c3) and
            (c3 > c2) and
            (conf_close > swing_high)
        )

        # =========================
        # SWING INSIDE BAR
        # 4 candle trending + candle swing inside range bar[3]
        # FIX: cek high/low candle swing, bukan close
        # =========================

        is_sh2 = (
            (c5 < c4) and
            (c4 < c3) and
            (c3 < c2) and
            (swing_high < h3) and    # high bar[2] < high bar[3] ✅
            (swing_low  > l3) and    # low  bar[2] > low  bar[3] ✅
            (conf_close < swing_low)
        )

        is_sl2 = (
            (c5 > c4) and
            (c4 > c3) and
            (c3 > c2) and
            (swing_low  > l3) and    # low  bar[2] > low  bar[3] ✅
            (swing_high < h3) and    # high bar[2] < high bar[3] ✅
            (conf_close > swing_high)
        )

        # =========================
        # EARLY REVERSAL MA (LWMA)
        # =========================

        new_is_sh = (
            (ma_h_shift3 < ma_h_shift2) and
            (conf_close < swing_low)
        )

        new_is_sl = (
            (ma_l_shift3 > ma_l_shift2) and
             (conf_close > swing_high)
        )

        is_valid_swing = (
            is_sh or
            is_sl or
            is_sh2 or
            is_sl2 or
            new_is_sh or
            new_is_sl
        )

        if not is_valid_swing:
            return None

        is_buy = (
            is_sl or
            is_sl2 or
            new_is_sl
        )

        direction = "BUY" if is_buy else "SELL"

        if is_buy:
            zone_threshold = conf_low + (range_conf * 0.40)
            inval_price    = conf_low

            if is_sl2:
                pattern_name = "SwingLow2 (InsideBar)"
            elif new_is_sl:
                pattern_name = "SwingLow_MA (Early Reversal)"
            else:
                pattern_name = "SwingLow (Original)"
        else:
            zone_threshold = conf_high - (range_conf * 0.60)
            inval_price    = conf_high

            if is_sh2:
                pattern_name = "SwingHigh2 (InsideBar)"
            elif new_is_sh:
                pattern_name = "SwingHigh_MA (Early Reversal)"
            else:
                pattern_name = "SwingHigh (Original)"

        time_col = (
            'time_str'
            if 'time_str' in df.columns
            else (df.index.name if df.index.name else 'index')
        )

        detection_time_str = (
            str(df[time_col].iloc[-2])
            if time_col != 'index'
            else str(df.index[-2])
        )

        current_time_str = (
            str(df[time_col].iloc[-1])
            if time_col != 'index'
            else str(df.index[-1])
        )

        return {
            'symbol':               symbol,
            'tf':                   tf_name,
            'strategy':             self.name,
            'direction':            direction,
            'sinyal':               pattern_name,
            'detection_time':       detection_time_str,
            'current_candle_time':  current_time_str,
            'saved_time_str':       current_time_str,
            'harga':                format_price(current_price, symbol),
            'conf_high':            conf_high,
            'conf_low':             conf_low,
            'invalidation_price':   float(inval_price),
            'zone_threshold':       float(zone_threshold),
            'zona': (
                f"Zone: {'≤' if is_buy else '≥'} "
                f"{format_price(zone_threshold, symbol)} | "
                f"Inval: {'<' if is_buy else '>'} "
                f"{format_price(inval_price, symbol)}"
            )
        }
