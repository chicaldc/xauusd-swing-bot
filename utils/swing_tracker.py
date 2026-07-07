"""
/utils/swing_tracker.py
Mengelola status aktif, invalidasi, dan alerting untuk Swing yang terdeteksi.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from utils.helpers import format_price

@dataclass
class ActiveSwing:
    symbol: str
    tf: str
    direction: str
    sinyal: str
    detection_time: str
    start_candle_time: str  # Waktu candle saat pertama kali terdeteksi
    conf_high: float
    conf_low: float
    zone_threshold: float
    invalidation_price: float
    candles_alive: int = 1
    has_alerted_this_candle: bool = False
    is_active: bool = True
    status_reason: str = "Active"

class SwingTracker:
    def __init__(self):
        # Key: "SYMBOL_TF", Value: ActiveSwing object
        self.active_swings: Dict[str, ActiveSwing] = {}

    def update_and_check(self, symbol: str, tf: str, current_price: float, current_high: float, current_low: float, current_candle_time: str, new_swing_data: Optional[dict] = None) -> Optional[ActiveSwing]:
        key = f"{symbol}_{tf}"

        # 1. Jika ada swing baru terdeteksi, tambahkan ke tracker
        if new_swing_data:
            self.active_swings[key] = ActiveSwing(
                symbol=symbol,
                tf=tf,
                direction=new_swing_data['direction'],
                sinyal=new_swing_data['sinyal'],
                detection_time=new_swing_data['detection_time'],
                start_candle_time=current_candle_time,
                conf_high=new_swing_data['conf_high'],
                conf_low=new_swing_data['conf_low'],
                zone_threshold=new_swing_data['zone_threshold'],
                invalidation_price=new_swing_data['invalidation_price'],
                candles_alive=1,
                has_alerted_this_candle=False,
                is_active=True,
                status_reason="Active"
            )
            return self.active_swings[key] # Return untuk trigger alert awal

        # 2. Update swing yang sudah ada
        if key in self.active_swings:
            swing = self.active_swings[key]

            # Cek apakah candle baru sudah terbentuk (reset flag alert)
            if current_candle_time != swing.start_candle_time and swing.candles_alive < 3:
                # Sederhana: kita asumsikan jika waktu candle beda, itu candle baru.
                # Dalam implementasi real, bandingkan dengan swing.last_candle_time
                swing.has_alerted_this_candle = False
                swing.candles_alive += 1

            # Aturan 1: Batas Masa Aktif 3 Candle
            if swing.candles_alive > 3:
                swing.is_active = False
                swing.status_reason = "Expired (Max 3 Candles)"
                return swing

            # Aturan 2: Invalidasi jika break High/Low Candle Konfirmasi
            if swing.direction == 'BUY' and current_low < swing.invalidation_price:
                swing.is_active = False
                swing.status_reason = f"Invalidated (Break Low {format_price(swing.invalidation_price, symbol)})"
                return swing

            if swing.direction == 'SELL' and current_high > swing.invalidation_price:
                swing.is_active = False
                swing.status_reason = f"Invalidated (Break High {format_price(swing.invalidation_price, symbol)})"
                return swing

            # Aturan 3: Cek Zona & Alert (1x per candle)
            in_zone = False
            if swing.direction == 'BUY' and (swing.invalidation_price <= current_price <= swing.zone_threshold):
                in_zone = True
            elif swing.direction == 'SELL' and (swing.zone_threshold <= current_price <= swing.invalidation_price):
                in_zone = True

            if in_zone and not swing.has_alerted_this_candle:
                swing.has_alerted_this_candle = True
                swing.status_reason = "ALERT: In Zone!"
                # Di sini kamu bisa panggil fungsi send_telegram_alert() atau play_sound()
                print(f"🚨 ALERT: {swing.symbol} {swing.tf} {swing.direction} masuk zona!")

            elif in_zone and swing.has_alerted_this_candle:
                swing.status_reason = "In Zone (Alerted)"
            else:
                swing.status_reason = "Active (Out of Zone)"

            return swing

        return None

    def get_all_active_for_streamlit(self) -> list:
        """Mengembalikan list swing untuk ditampilkan di Streamlit, termasuk yang baru saja invalid/expired (opsional, tergantung preferensi UI)"""
        # Kita kembalikan semua yang masih is_active=True
        return [swing for swing in self.active_swings.values() if swing.is_active]
