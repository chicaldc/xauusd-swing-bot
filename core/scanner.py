"""
core/scanner.py
Orchestrator Streamlit khusus Swing Strategy dengan Notifikasi Suara & Anti-Spam per Candle
+ ADX/DI terintegrasi di DiCrossDetector
+ ✅ ADX-R sebagai Early Warning (bisa trigger tanpa swing)
+ ✅ FIX: Anti-spam yang proper + get_current_candle_time() yang benar
"""
import streamlit as st
import pandas as pd

from core.mt5_connector import (
    fetch_ohlcv,
    get_visible_symbols,
    initialize_mt5,
    get_xauusd_symbol
)
from core.logger import add_log

# 1. Import Strategi Utama (Hard Gate)
from strategies.swing_strategy import SwingStrategy

# 2. Import Detector Independen (Bonus Confluence)
from strategies.di_cross_detector import DiCrossDetector
from strategies.choc_detector import ChocDetector
from strategies.extreme_detector import get_extreme_info

# Inisialisasi Komponen (Hanya dilakukan sekali)
STRATEGY = SwingStrategy()
DI_DETECTOR = DiCrossDetector(period=14, lookback=4)
CHOCH_DETECTOR = ChocDetector(lookback_period=20, recent_exclude=5)


# ==========================================================
# FUNGSI ALERT SUARA - Hanya set flag, audio diputar di app.py
# ==========================================================
def play_alert_sound():
    """
    Tandai bahwa audio perlu diputar di browser.
    Audio sebenarnya akan diputar di app.py menggunakan st.audio() native.
    """
    st.session_state.play_audio_flag = True
    add_log("🔊 Audio alert ditandai untuk diputar di browser")


# ==========================================================
# ✅ FIX: ANTI-SPAM LOGIC
# ==========================================================
def _should_alert(symbol: str, tf_name: str, candle_key: str, direction: str, sinyal: str) -> bool:
    """
    Logika anti-spam yang cerdas:
    - 1 alert per candle per pair+TF
    - Jika sinyal SAMA di candle yang sama → JANGAN alert
    - Jika sinyal BERGANTI → boleh alert lagi
    """
    if 'alert_history' not in st.session_state:
        st.session_state.alert_history = {}
    
    history_key = f"{symbol}_{tf_name}"
    
    # Cek apakah sudah pernah alert di candle ini
    if history_key in st.session_state.alert_history:
        last_alert = st.session_state.alert_history[history_key]
        last_candle_key = last_alert.get('candle_key')
        last_sinyal = last_alert.get('sinyal')
        last_direction = last_alert.get('direction')
        
        # Jika candle SAMA dan sinyal SAMA → JANGAN alert lagi
        if last_candle_key == candle_key:
            return False
        
        # Jika sinyal SAMA (arah sama) → cek cooldown
        if last_direction == direction and last_sinyal == sinyal:
            # Conservative: jangan alert jika sinyal sama meski candle berbeda
            return False
    
    # Boleh alert - simpan history
    st.session_state.alert_history[history_key] = {
        'candle_key': candle_key,
        'sinyal': sinyal,
        'direction': direction,
        'timestamp': pd.Timestamp.now()
    }
    
    return True


def check_expiration(key: str, saved_time_str: str, df: pd.DataFrame, validity_candles: int) -> bool:
    """Cek apakah sinyal masih valid berdasarkan batas waktu (aturan N candle)."""
    if validity_candles >= 999:
        return True

    if df is None or len(df) < 2:
        return False

    time_col = 'time_str' if 'time_str' in df.columns else (df.index.name if df.index.name else 'index')

    if time_col == 'index':
        time_list = [str(idx) for idx in df.index.tolist()]
    else:
        time_list = df[time_col].tolist()

    if saved_time_str not in time_list:
        return False

    saved_idx = time_list.index(saved_time_str)
    current_idx = len(df) - 1
    candles_passed = current_idx - saved_idx

    return candles_passed <= validity_candles


def get_current_candle_time(df: pd.DataFrame) -> str:
    """
    Mengambil waktu Open dari candle yang SEDANG BERJALAN (terbaru).
    
    ✅ FIX: Menggunakan iloc[-1] untuk ambil candle terakhir,
    bukan iloc[0] yang mengambil candle paling lama.
    """
    try:
        if df is None or len(df) == 0:
            return "unknown"
        
        # ✅ Data dari fetch_ohlcv() di-return ascending (lama → baru)
        # Jadi candle terbaru ada di index -1 (paling akhir)
        if 'time_str' in df.columns:
            return str(df.iloc[-1]['time_str'])  # ✅ FIX: -1 bukan 0
        elif df.index.name and 'time' in str(df.index.name).lower():
            return str(df.index[-1])  # ✅ FIX
        else:
            return str(df.index[-1])  # ✅ FIX
    except Exception as e:
        add_log(f"⚠️ Error get_current_candle_time: {e}")
        return "unknown"


def _build_swing_data(result: dict, di_info: dict, current_price: float, candle_key: str) -> dict:
    """
    Bangun payload swing_data lengkap (ADX/DI + bonus confluence + in_zone)
    dari hasil STRATEGY.analyze().
    """
    symbol = result['symbol']
    tf_name = result['tf']
    direction = result['direction']

    swing_data = {
        **result,
        'type': 'Swing Zone',  # ✅ Tandai tipe sinyal
        'adx': di_info['adx'],
        'adx_status': di_info['adx_status'],
        'plus_di': di_info['plus_di'],
        'minus_di': di_info['minus_di'],
        'di_spread': di_info['di_spread'],
        'adx_in_range': di_info['adx_in_range'],
        'in_zone': False,
        'last_candle_key': candle_key,
    }

    in_zone = False
    if 'zone_threshold' in result and 'invalidation_price' in result:
        if direction == 'BUY':
            in_zone = result['invalidation_price'] <= current_price <= result['zone_threshold']
        elif direction == 'SELL':
            in_zone = result['zone_threshold'] <= current_price <= result['invalidation_price']
    swing_data['in_zone'] = in_zone

    di_ok = di_info['di_crossed']
    choc_ok = CHOCH_DETECTOR.check(symbol, tf_name, direction)
    is_extreme_now, extreme_msg = get_extreme_info(symbol, tf_name, direction)

    adx_r_msg = di_info['adx_in_range_msg']

    swing_data['bonus_status'] = (
        f"{'✅' if di_ok else '❌'} DI | "
        f"{'⚡' if choc_ok else '⚪'} CHoCH | "
        f"LTF: {extreme_msg} | "
        f"{adx_r_msg}"
    )

    return swing_data


def _build_adx_r_early_warning(symbol: str, tf_name: str, direction: str, di_info: dict, candle_key: str) -> dict:
    """
    ✅ BARU: Bangun payload ADX-R Early Warning (tanpa swing).
    Sinyal ini muncul SEBELUM swing terbentuk, sebagai early warning.
    """
    adx_r_data = {
        'symbol': symbol,
        'tf': tf_name,
        'direction': direction,
        'type': 'ADX-R Early Warning',  # ✅ Tandai tipe sinyal
        'sinyal': f"ADX-R {direction}",
        'harga': 0.0,  # Tidak ada harga entry spesifik
        'zona': 'Menunggu swing terbentuk...',
        'adx': di_info['adx'],
        'adx_status': di_info['adx_status'],
        'plus_di': di_info['plus_di'],
        'minus_di': di_info['minus_di'],
        'di_spread': di_info['di_spread'],
        'adx_in_range': True,
        'in_zone': False,  # Tidak ada zona karena swing belum terbentuk
        'saved_time_str': candle_key.split('_')[-1],  # Ambil waktu dari candle_key
        'validity_candles': 3,  # Validitas 3 candle
        'last_candle_key': candle_key,
        'bonus_status': f"🎯 ADX-R: {direction} CONFIRMED | ADX:{di_info['adx']:.1f} ({di_info['adx_status']})"
    }
    return adx_r_data


def scan_once(symbols, timeframes, scan_xauusd_only=False, adx_period=14, adx_threshold=25, adx_r_mode="⚪ Bonus Confluence (Default)"):
    """
    Scan semua pair & TF dengan ATURAN EMAS:
    1. Tampilkan info selama 3 candle (Expiration).
    2. Hapus/Invalidasi HANYA jika harga break High/Low candle konfirmasi.
    3. Alert 1x per candle HANYA saat harga masuk zona.
    4. Info tetap ditampilkan meski harga keluar zona (jangan dihapus).
    5. ADX/DI dihitung otomatis via DiCrossDetector.analyze()
    6. ✅ ADX-R bisa trigger sinyal sendiri (Early Warning) jika mode dipilih
    7. ✅ FIX: Anti-spam yang proper
    """

    ok, msg = initialize_mt5()
    if not ok:
        add_log(f"❌ {msg}")
        return

    if 'active_swings' not in st.session_state:
        st.session_state.active_swings = {}
    if 'notified_signals' not in st.session_state:
        st.session_state.notified_signals = set()
    if 'notified_new_swings' not in st.session_state:
        st.session_state.notified_new_swings = set()
    if 'alert_history' not in st.session_state:
        st.session_state.alert_history = {}

    # LOGIKA PEMILIHAN SIMBOL
    if scan_xauusd_only:
        target_symbol = get_xauusd_symbol()
        if not target_symbol:
            add_log("❌ GAGAL: Simbol XAUUSD tidak ditemukan di Market Watch MT5.")
            return
        symbols_to_scan = [target_symbol]
        add_log(f"🎯 Mode Scan: KHUSUS {target_symbol} | ADX({adx_period}, >{adx_threshold}) | ADX-R: {adx_r_mode}")
    else:
        symbols_to_scan = symbols
        add_log(f"🔄 Scanning {len(symbols_to_scan)} pair × {len(timeframes)} TF | ADX({adx_period}, >{adx_threshold}) | ADX-R: {adx_r_mode}")

    for symbol in symbols_to_scan:
        for tf_name in timeframes:
            df = fetch_ohlcv(symbol, tf_name)
            if df is None or len(df) < 2:
                continue

            current_candle_time = get_current_candle_time(df)
            candle_key = f"{symbol}_{tf_name}_{current_candle_time}"
            swing_key = f"{symbol}_{tf_name}_swing"
            adx_r_key = f"{symbol}_{tf_name}_adx_r"  # ✅ Key baru untuk ADX-R standalone

            current_price = float(df['close'].iloc[-1])
            current_high = float(df['high'].iloc[-1])
            current_low = float(df['low'].iloc[-1])

            # =========================================================
            # ✅ MODE 3: ADX-R EARLY WARNING (Tanpa Swing)
            # =========================================================
            if adx_r_mode == "⚡ Early Warning (ADX-R tanpa swing)":
                # Cek ADX-R untuk BUY dan SELL
                for direction in ['BUY', 'SELL']:
                    di_info = DI_DETECTOR.analyze(df, direction=direction, adx_threshold=adx_threshold)

                    if di_info['adx_in_range']:
                        # Cek apakah sudah ada swing aktif di pair+TF ini
                        has_swing = swing_key in st.session_state.active_swings

                        if not has_swing:
                            # ✅ ADX-R standalone (tanpa swing)
                            if adx_r_key not in st.session_state.active_swings:
                                # Sinyal ADX-R baru
                                adx_r_data = _build_adx_r_early_warning(symbol, tf_name, direction, di_info, candle_key)
                                st.session_state.active_swings[adx_r_key] = adx_r_data

                                add_log(
                                    f"⚠️ {symbol} [{tf_name}] 🎯 ADX-R EARLY WARNING! {direction} "
                                    f"| ADX:{di_info['adx']:.1f} ({di_info['adx_status']}) | "
                                    f"+DI:{di_info['plus_di']:.1f} -DI:{di_info['minus_di']:.1f}"
                                )
                                play_alert_sound()
                            else:
                                # Update ADX-R yang sudah ada
                                adx_r_data = st.session_state.active_swings[adx_r_key]
                                adx_r_data['adx'] = di_info['adx']
                                adx_r_data['adx_status'] = di_info['adx_status']
                                adx_r_data['plus_di'] = di_info['plus_di']
                                adx_r_data['minus_di'] = di_info['minus_di']
                                adx_r_data['last_candle_key'] = candle_key

                                # Cek expiration
                                validity = adx_r_data.get('validity_candles', 3)
                                if not check_expiration(adx_r_key, adx_r_data['saved_time_str'], df, validity):
                                    add_log(f"⏳ {symbol} [{tf_name}] ADX-R EXPIRED. Sinyal dihapus.")
                                    del st.session_state.active_swings[adx_r_key]
                                    st.session_state.notified_new_swings.discard(adx_r_key)

            # =========================================================
            # A. JIKA SUDAH ADA SWING AKTIF
            # =========================================================
            if swing_key in st.session_state.active_swings:
                swing_data = st.session_state.active_swings[swing_key]

                validity = swing_data.get('validity_candles', 3)
                if not check_expiration(swing_key, swing_data['saved_time_str'], df, validity):
                    add_log(f"⏳ {symbol} [{tf_name}] Sinyal EXPIRED (Melebihi {validity} Candle). Sinyal dihapus.")
                    del st.session_state.active_swings[swing_key]
                    st.session_state.notified_new_swings.discard(swing_key)

                    # ✅ Jika ada ADX-R early warning di pair+TF yang sama, hapus juga
                    if adx_r_key in st.session_state.active_swings:
                        del st.session_state.active_swings[adx_r_key]
                        st.session_state.notified_new_swings.discard(adx_r_key)
                    continue

                is_invalidated = False
                if 'invalidation_price' in swing_data:
                    if swing_data['direction'] == 'BUY' and current_low < swing_data['invalidation_price']:
                        is_invalidated = True
                    elif swing_data['direction'] == 'SELL' and current_high > swing_data['invalidation_price']:
                        is_invalidated = True

                if is_invalidated:
                    add_log(f"❌ {symbol} [{tf_name}] 🚨 SWING INVALIDATED! (Harga break confirmation candle).")
                    del st.session_state.active_swings[swing_key]
                    st.session_state.notified_new_swings.discard(swing_key)

                    # ✅ Jika ada ADX-R early warning di pair+TF yang sama, hapus juga
                    if adx_r_key in st.session_state.active_swings:
                        del st.session_state.active_swings[adx_r_key]
                        st.session_state.notified_new_swings.discard(adx_r_key)
                    continue

                # Cek apakah ada swing baru
                fresh_result = STRATEGY.analyze(df, symbol, tf_name)
                is_new_swing = (
                    fresh_result is not None
                    and fresh_result.get('saved_time_str') != swing_data.get('saved_time_str')
                )

                if is_new_swing:
                    old_sinyal = swing_data.get('sinyal', '?')
                    add_log(
                        f"🔄 {symbol} [{tf_name}] Swing lama ({old_sinyal}) DIGANTIKAN oleh "
                        f"swing baru ({fresh_result['sinyal']}). Validitas candle direset."
                    )
                    st.session_state.notified_new_swings.discard(swing_key)

                    new_direction = fresh_result['direction']
                    di_info = DI_DETECTOR.analyze(df, direction=new_direction, adx_threshold=adx_threshold)
                    new_swing_data = _build_swing_data(fresh_result, di_info, current_price, candle_key)

                    st.session_state.active_swings[swing_key] = new_swing_data
                    add_log(
                        f"🆕 {symbol} [{tf_name}] 🆕 SWING BARU (REPLACE) TERDETEKSI! {fresh_result['sinyal']} "
                        f"| ADX:{new_swing_data['adx']:.1f} ({new_swing_data['adx_status']}) | {new_swing_data['bonus_status']}"
                    )

                    # ✅ RESET alert history karena sinyal berganti
                    history_key = f"{symbol}_{tf_name}"
                    if history_key in st.session_state.alert_history:
                        del st.session_state.alert_history[history_key]
                        add_log(f"🔄 {symbol} [{tf_name}] Alert history direset (sinyal berganti)")

                    # ✅ Jika ada ADX-R early warning di pair+TF yang sama, hapus karena sudah ada swing
                    if adx_r_key in st.session_state.active_swings:
                        del st.session_state.active_swings[adx_r_key]
                        st.session_state.notified_new_swings.discard(adx_r_key)

                    # ✅ FIX: Pakai _should_alert() untuk anti-spam
                    if new_swing_data['in_zone']:
                        if _should_alert(symbol, tf_name, candle_key, new_direction, fresh_result['sinyal']):
                            play_alert_sound()
                            add_log(
                                f"🚨 {symbol} [{tf_name}] {fresh_result['sinyal']} LANGSUNG MASUK ZONA! "
                                f"| ADX:{new_swing_data['adx']:.1f} ({new_swing_data['adx_status']}) | "
                                f"{new_swing_data['bonus_status']} 🔊"
                            )
                            st.session_state.notified_signals.add(candle_key)

                    continue

                # Update ADX/DI real-time
                direction = swing_data['direction']
                di_info = DI_DETECTOR.analyze(df, direction=direction, adx_threshold=adx_threshold)

                swing_data['adx'] = di_info['adx']
                swing_data['adx_status'] = di_info['adx_status']
                swing_data['plus_di'] = di_info['plus_di']
                swing_data['minus_di'] = di_info['minus_di']
                swing_data['di_spread'] = di_info['di_spread']
                swing_data['adx_in_range'] = di_info['adx_in_range']

                in_zone = False
                if 'zone_threshold' in swing_data and 'invalidation_price' in swing_data:
                    if swing_data['direction'] == 'BUY':
                        in_zone = swing_data['invalidation_price'] <= current_price <= swing_data['zone_threshold']
                    elif swing_data['direction'] == 'SELL':
                        in_zone = swing_data['zone_threshold'] <= current_price <= swing_data['invalidation_price']

                swing_data['in_zone'] = in_zone

                di_ok = di_info['di_crossed']
                adx_r_msg = di_info['adx_in_range_msg']
                choc_ok = CHOCH_DETECTOR.check(symbol, tf_name, direction)
                is_extreme_now, extreme_msg = get_extreme_info(symbol, tf_name, direction)

                bonus_status = (
                    f"{'✅' if di_ok else '❌'} DI | "
                    f"{'⚡' if choc_ok else '⚪'} CHoCH | "
                    f"LTF: {extreme_msg} | "
                    f"{adx_r_msg}"
                )

                swing_data['bonus_status'] = bonus_status
                swing_data['last_candle_key'] = candle_key

                # ✅ FIX: Pakai _should_alert() untuk anti-spam
                if in_zone:
                    if _should_alert(symbol, tf_name, candle_key, direction, swing_data['sinyal']):
                        play_alert_sound()
                        add_log(
                            f"🚨 {symbol} [{tf_name}] {swing_data['sinyal']} MASUK ZONA! "
                            f"| ADX:{di_info['adx']:.1f} ({di_info['adx_status']}) | {bonus_status} 🔊"
                        )
                        st.session_state.notified_signals.add(candle_key)

            # =========================================================
            # B. JIKA BELUM ADA SWING AKTIF (MENCARI SWING BARU)
            # =========================================================
            else:
                result = STRATEGY.analyze(df, symbol, tf_name)

                if result is not None:
                    direction = result['direction']
                    di_info = DI_DETECTOR.analyze(df, direction=direction, adx_threshold=adx_threshold)

                    # ✅ MODE 2: Hard Filter (jika dipilih)
                    if adx_r_mode == "🔒 Hard Filter (Swing harus ADX-R)":
                        if not di_info['adx_in_range']:
                            continue  # Skip swing ini

                    swing_data = _build_swing_data(result, di_info, current_price, candle_key)

                    st.session_state.active_swings[swing_key] = swing_data
                    add_log(
                        f"🆕 {symbol} [{tf_name}] 🆕 SWING BARU TERDETEKSI! {result['sinyal']} "
                        f"| ADX:{swing_data['adx']:.1f} ({swing_data['adx_status']}) | {swing_data['bonus_status']}"
                    )

                    # ✅ Jika ada ADX-R early warning di pair+TF yang sama, hapus karena sudah ada swing
                    if adx_r_key in st.session_state.active_swings:
                        del st.session_state.active_swings[adx_r_key]
                        st.session_state.notified_new_swings.discard(adx_r_key)

                    # ✅ FIX: Pakai _should_alert() untuk anti-spam
                    if swing_data['in_zone']:
                        if _should_alert(symbol, tf_name, candle_key, direction, result['sinyal']):
                            play_alert_sound()
                            add_log(
                                f"🚨 {symbol} [{tf_name}] {result['sinyal']} LANGSUNG MASUK ZONA! "
                                f"| ADX:{swing_data['adx']:.1f} ({swing_data['adx_status']}) | {swing_data['bonus_status']} 🔊"
                            )
                            st.session_state.notified_signals.add(candle_key)

    cleanup_old_notifications(symbols_to_scan, timeframes)
    add_log(f"✅ Scan selesai. Sinyal aktif: {len(st.session_state.active_swings)}")


def cleanup_old_notifications(active_symbols: list, timeframes: list):
    """Membersihkan notified_signals dari candle-candle yang sudah lama."""
    if 'notified_signals' not in st.session_state:
        return

    keys_to_remove = set()

    for key in list(st.session_state.notified_signals):
        try:
            parts = key.split('_', 2)
            if len(parts) < 3:
                continue

            symbol = parts[0]
            tf_name = parts[1]

            if symbol not in active_symbols or tf_name not in timeframes:
                continue

            df = fetch_ohlcv(symbol, tf_name, bars=3)
            if df is None or len(df) < 2:
                continue

            recent_candles = set()
            for i in range(min(2, len(df))):
                if 'time_str' in df.columns:
                    recent_candles.add(str(df.iloc[-(i+1)]['time_str']))  # ✅ FIX: iloc[-(i+1)]
                else:
                    recent_candles.add(str(df.index[-(i+1)]))  # ✅ FIX

            candle_time_in_key = parts[2].replace('_EXTREME', '')
            if candle_time_in_key not in recent_candles:
                keys_to_remove.add(key)

        except Exception:
            keys_to_remove.add(key)

    for key in keys_to_remove:
        st.session_state.notified_signals.discard(key)

    if keys_to_remove:
        add_log(f"🧹 Cleanup: {len(keys_to_remove)} notifikasi lama dihapus")


def calculate_remaining_candles(saved_time_str: str, symbol: str, tf_name: str, validity_candles: int) -> int:
    """Hitung sisa candle validitas sebelum sinyal expired"""
    if validity_candles >= 999:
        return 999

    df = fetch_ohlcv(symbol, tf_name, bars=validity_candles + 5)
    if df is None:
        return 0

    time_col = 'time_str' if 'time_str' in df.columns else (df.index.name if df.index.name else 'index')
    if time_col == 'index':
        time_list = [str(idx) for idx in df.index.tolist()]
    else:
        time_list = df[time_col].tolist()

    if saved_time_str not in time_list:
        return 0

    saved_idx = time_list.index(saved_time_str)
    current_idx = len(df) - 1
    passed = current_idx - saved_idx

    return max(0, validity_candles - passed)
