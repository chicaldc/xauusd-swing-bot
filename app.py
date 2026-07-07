"""
app.py
Swing Zone Scanner EA - Single Strategy Focus + ADX/DI Filter Integration
Konsisten dengan 1 setup: Swing 3-Candle + Invalidation Level + ADX/DI Confirmation

✅ ENHANCEMENT: ADX in Range (ADX-R) terintegrasi penuh di UI
✅ LAYOUT: Reorganisasi kolom tabel + split metrics untuk kerapian visual

FIX (audio alert):
1. st.audio() sebelumnya dipanggil dengan bytes file yang SELALU SAMA setiap
   rerun -> Streamlit menganggap widget identik -> elemen <audio> di browser
   TIDAK dibuat ulang -> atribut autoplay cuma nge-trigger sekali (saat klik
   "Enable Sound") lalu bisu selamanya. FIX: beri `key` unik (counter + ts)
   setiap kali alert baru diputar, supaya Streamlit selalu mount elemen BARU
   dan autoplay ke-trigger lagi.
2. Auto-scan background sebelumnya dijalankan SETELAH proses deteksi sinyal
   baru + play_audio_in_browser() -> sinyal baru dari auto-scan baru "kebaca"
   1 siklus refresh berikutnya (delay). FIX: auto-scan dipindah ke atas,
   sebelum bagian render dashboard & deteksi sinyal, supaya dalam 1 kali
   rerun urutannya: scan -> deteksi sinyal baru -> set flag -> mainkan audio.
3. UI toggle "Enable/Disable Sound" & "Test Alert Sound" DIHAPUS. Audio alert
   sekarang otomatis aktif tanpa perlu interaksi apapun dari user (asumsi
   izin autoplay browser sudah di-set "Allow" di level browser/site settings
   untuk domain/port yang dipakai).
"""
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import time
import datetime
import os

from core.scanner import scan_once, calculate_remaining_candles
from core.logger import get_logs, add_log, clear_logs
from core.mt5_connector import initialize_mt5, get_visible_symbols, get_xauusd_symbol
from config.settings import DEFAULT_TIMEFRAMES, AUTO_REFRESH_INTERVAL_MS
from core.position_tracker import get_open_positions, get_portfolio_summary
from utils.helpers import (
    highlight_signal_row,
    highlight_sisa_candle,
    highlight_profit,
    estimate_candle_close_time,
    format_duration,
)


# ==========================================
# ✅ FUNGSI SUARA ALERT (NATIVE st.audio + UNIQUE KEY FIX)
# ==========================================
def play_audio_in_browser():
    """
    Putar audio alert di browser menggunakan st.audio() NATIVE Streamlit.

    ✅ FIX PENTING: setiap pemanggilan diberi `key` yang UNIK (counter + timestamp).
    Tanpa ini, karena bytes audio yang dibaca selalu sama persis, Streamlit
    menganggap widget tidak berubah dan TIDAK me-remount elemen <audio> di
    DOM browser -> autoplay cuma jalan sekali seumur sesi. Dengan key unik,
    Streamlit selalu membuat elemen <audio autoplay> yang baru, sehingga
    browser mencoba autoplay lagi setiap ada sinyal baru.
    """
    if not st.session_state.get('play_audio_flag', False):
        return

    # ✅ Reset flag
    st.session_state.play_audio_flag = False

    # ✅ Cari file audio
    audio_file = None
    for filename in ["alert.wav", "alert.mp3"]:
        if os.path.exists(filename):
            audio_file = filename
            break

    if not audio_file:
        add_log("⚠️ File audio tidak ditemukan (alert.wav / alert.mp3)!")
        return

    with open(audio_file, "rb") as f:
        audio_bytes = f.read()

    audio_format = "audio/wav" if audio_file.endswith(".wav") else "audio/mpeg"

    # ✅ FIX: parameter `key` di st.audio() tidak didukung di versi Streamlit
    # yang terpasang (TypeError). Sebagai gantinya, kita paksa Streamlit
    # menganggap kontennya BEDA setiap kali dengan menambahkan marker unik
    # di akhir bytes audio. Ini aman: browser membaca panjang data audio dari
    # header format-nya sendiri (RIFF/WAVE untuk .wav, frame MPEG untuk .mp3),
    # jadi beberapa byte tambahan di ujung file tidak akan ikut terdengar
    # atau merusak playback — tapi cukup untuk membuat Streamlit me-remount
    # elemen <audio> baru (bukan reuse elemen lama) sehingga autoplay
    # ke-trigger lagi.
    st.session_state.alert_play_counter = st.session_state.get('alert_play_counter', 0) + 1
    marker = f"__ALERT_{st.session_state.alert_play_counter}_{int(time.time() * 1000)}__".encode()
    audio_bytes_unique = audio_bytes + marker

    st.audio(audio_bytes_unique, format=audio_format, autoplay=True)
    add_log(f"🔊 Audio diputar: {audio_file} (trigger #{st.session_state.alert_play_counter})")


# ==========================================
# ✅ WRAPPER play_alert_sound() untuk app.py
# ==========================================
def play_alert_sound():
    """Wrapper untuk menandai flag audio di app.py (dipanggil saat ada sinyal baru)"""
    st.session_state.play_audio_flag = True


# ==========================================
# ✅ FUNGSI HELPER UNTUK STYLING KOLOM INFO
# ==========================================
def highlight_info_columns(val):
    """
    Background SAMA dengan kolom lain (Pair, TF, Sinyal, dll).
    Hanya warna TULISAN yang membedakan status.
    """
    val_str = str(val)

    if ('STRONG' in val_str or '✅' in val_str or
            'YA' in val_str or 'EXTREME' in val_str):
        return 'color: #FF4444'
    elif ('WEAK' in val_str or '❌' in val_str or
          'TIDAK' in val_str or 'Normal' in val_str):
        return 'color: #FF4444'
    elif ('MODERATE' in val_str or '⚪' in val_str or
          'Menunggu' in val_str or 'N/A' in val_str):
        return 'color: #FFD700'
    return ''


def run_auto_scan_if_due(scan_mode, timeframes, symbols_to_scan, adx_period, adx_threshold):
    """
    ✅ FIX ORDERING: fungsi ini dipanggil SEBELUM dashboard sinyal dirender,
    supaya sinyal baru dari auto-scan langsung terdeteksi & memicu audio
    pada rerun yang SAMA (bukan menunggu 1 siklus refresh berikutnya).
    """
    if time.time() - st.session_state.last_scan_ts < 60:
        return

    is_xau_only = (scan_mode == "🎯 Hanya XAUUSD")
    can_auto_scan = bool(timeframes) if is_xau_only else bool(symbols_to_scan and timeframes)

    if can_auto_scan:
        scan_once(
            symbols=symbols_to_scan if not is_xau_only else [],
            timeframes=timeframes,
            scan_xauusd_only=is_xau_only,
            adx_period=adx_period,
            adx_threshold=adx_threshold
        )
        st.session_state.last_scan_ts = time.time()


# ==========================================
# 1. Konfigurasi Halaman
# ==========================================
st.set_page_config(
    page_title="Ultimate Swing Zone Scanner EA",
    layout="wide",
    page_icon="📊"
)

st.markdown("""
<style>
/* ✅ FIX: sebelumnya pakai display:none yang berpotensi membuat browser
   tidak benar-benar menginisialisasi elemen <audio> (beberapa implementasi
   komponen menganggap display:none = tidak perlu render/play).
   Sekarang disembunyikan dengan cara ditaruh di luar layar, TANPA display:none,
   supaya elemen tetap "hidup" dan bisa autoplay normal. */
[data-testid="stAudio"] {
    position: fixed !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    opacity: 0.01 !important;
    pointer-events: none !important;
}

/* ✅ ENHANCEMENT: Styling untuk header group kolom tabel */
.group-header {
    background-color: #1f77b4;
    color: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-weight: bold;
    text-align: center;
    margin-bottom: 4px;
}

/* ✅ ENHANCEMENT: Styling untuk metric cards yang lebih visual */
.metric-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 12px;
    border-radius: 8px;
    color: white;
    text-align: center;
}

/* ✅ ENHANCEMENT: Spacing antar section */
.section-divider {
    margin: 20px 0;
    border-top: 2px solid #e0e0e0;
}
</style>
""", unsafe_allow_html=True)

st.title("📊 Ultimate Swing Zone Scanner EA")
st.caption("Single Strategy Focus | Multi-Pair & Multi-Timeframe | 3-Candle Valid + ADX/DI Filter + ADX in Range")

last_scan = st.session_state.get('last_scan_ts', 0)
if last_scan > 0:
    time_ago = int(time.time() - last_scan)
    st.info(f"🟢 **Scanner Aktif:** Terakhir scan {time_ago} detik yang lalu. (Auto-refresh: {AUTO_REFRESH_INTERVAL_MS}ms)")
else:
    st.warning("🟡 **Scanner Belum Berjalan.** Klik 'Scan Now' atau tunggu auto-scan.")

st_autorefresh(interval=AUTO_REFRESH_INTERVAL_MS, limit=None, key="auto_refresh_main")

# ✅ Initialize session state
if 'active_swings' not in st.session_state:
    st.session_state.active_swings = {}
if 'last_scan_ts' not in st.session_state:
    st.session_state.last_scan_ts = 0
if 'notified_signals' not in st.session_state:
    st.session_state.notified_signals = set()
# ✅ FIX: set TERPISAH khusus untuk alert "swing baru terdeteksi" di app.py.
# Sebelumnya app.py numpang pakai `notified_signals` yang formatnya beda
# dengan milik scanner.py (candle_key vs swing_key) -> tabrakan, dan
# cleanup_old_notifications() di scanner.py terus-menerus menghapus key
# "..._swing" tiap scan, bikin sinyal yang SAMA ke-alert berulang-ulang.
if 'notified_new_swings' not in st.session_state:
    st.session_state.notified_new_swings = set()
if 'scan_mode' not in st.session_state:
    st.session_state.scan_mode = "🎯 Hanya XAUUSD"
if 'play_audio_flag' not in st.session_state:
    st.session_state.play_audio_flag = False
if 'alert_play_counter' not in st.session_state:
    st.session_state.alert_play_counter = 0


# ==========================================
# 2. Sidebar: Kontrol
# ==========================================
with st.sidebar:
    st.header("⚙️ Kontrol Scanner")

    st.divider()

    st.subheader("🎯 Mode ADX in Range")
    adx_r_mode = st.radio(
        "Pilih perilaku ADX in Range:",
        options=[
            "⚪ Bonus Confluence (Default)",
            "🔒 Hard Filter (Swing harus ADX-R)",
            "⚡ Early Warning (ADX-R tanpa swing)"
        ],
        index=0,
        help="• **Bonus**: ADX-R hanya sebagai konfirmasi swing\n• **Hard Filter**: Swing hanya disimpan jika ADX-R terpenuhi\n• **Early Warning**: ADX-R trigger sinyal sendiri sebelum swing terbentuk"
    )
    st.session_state['adx_r_mode'] = adx_r_mode

    st.subheader("🎯 Mode Scan")
    scan_mode = st.radio(
        "Pilih target pair:",
        options=["🎯 Hanya XAUUSD", "🌍 Semua Pair Visible"],
        index=0 if st.session_state.scan_mode == "🎯 Hanya XAUUSD" else 1,
        help="• **Hanya XAUUSD**: Scanner fokus ke Gold saja.\n• **Semua Pair Visible**: Scan seluruh pair yang ditampilkan di Market Watch MT5."
    )
    st.session_state.scan_mode = scan_mode

    if scan_mode == "🎯 Hanya XAUUSD":
        ok_mt5, _ = initialize_mt5()
        if ok_mt5:
            detected_xau = get_xauusd_symbol()
            if detected_xau:
                st.success(f"✅ Terdeteksi: **{detected_xau}**")
            else:
                st.error("❌ XAUUSD tidak ditemukan di Market Watch!")
        st.caption("💡 Multiselect pair dinonaktifkan pada mode ini.")
    else:
        st.caption("💡 Pilih pair yang ingin di-scan di bawah ini.")

    st.divider()

    symbols_to_scan = []
    if scan_mode == "🌍 Semua Pair Visible":
        st.subheader("🌍 Pair (Symbol)")
        st.caption("Kelola pair di MT5 (Ctrl+U → Show/Hide)")

        ok, msg = initialize_mt5()
        if ok:
            visible_symbols = get_visible_symbols()
            if not visible_symbols:
                st.warning("⚠️ Tidak ada pair 'Visible' di Market Watch MT5.")
                symbols_to_scan = []
            else:
                symbols_to_scan = st.multiselect(
                    "Pilih pair untuk di-scan:",
                    options=visible_symbols,
                    default=visible_symbols,
                    help="Hapus centang pada pair yang tidak ingin di-scan."
                )
                st.info(f"✅ **{len(symbols_to_scan)}** pair aktif")
                if len(symbols_to_scan) > 0:
                    st.markdown(" ".join([f"`{s}`" for s in symbols_to_scan[:8]]))
                    if len(symbols_to_scan) > 8:
                        st.caption(f"...dan {len(symbols_to_scan) - 8} lainnya.")
        else:
            st.error(f"❌ {msg}")
            symbols_to_scan = []

    st.divider()

    st.subheader("⏱️ Timeframe")
    timeframes = st.multiselect(
        "Pilih TF:",
        ["M15", "M30", "H1", "H4", "D1"],
        default=DEFAULT_TIMEFRAMES
    )

    if timeframes:
        st.caption("⏰ Close candle berikutnya:")
        for tf in timeframes:
            close_time = estimate_candle_close_time(tf)
            remaining = int((close_time - pd.Timestamp.now()).total_seconds())
            st.text(f"  • {tf}: {close_time.strftime('%H:%M:%S')} ({format_duration(remaining)})")

    st.divider()

    st.subheader("📉 Filter ADX / DI (Kekuatan Tren)")
    adx_period = st.slider("Periode ADX", 7, 21, 14, help="Periode perhitungan ADX dan DI.")
    adx_threshold = st.slider("Minimum ADX (Tren Kuat)", 15, 35, 25, help="Sinyal dengan ADX di bawah ini akan ditandai WEAK.")

    st.session_state['adx_period'] = adx_period
    st.session_state['adx_threshold'] = adx_threshold

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Scan Now", width="stretch"):
            can_scan = False
            if scan_mode == "🎯 Hanya XAUUSD":
                can_scan = bool(timeframes)
                if not can_scan:
                    st.warning("Pilih minimal 1 Timeframe.")
            else:
                can_scan = bool(symbols_to_scan and timeframes)
                if not can_scan:
                    st.warning("Lengkapi pair & TF terlebih dahulu.")

            if can_scan:
                with st.spinner("Scanning..."):
                    is_xau_only = (scan_mode == "🎯 Hanya XAUUSD")
                    # Di tombol "Scan Now" dan `run_auto_scan_if_due()`
                    scan_once(
                        symbols=symbols_to_scan if not is_xau_only else [],
                        timeframes=timeframes,
                        scan_xauusd_only=is_xau_only,
                        adx_period=adx_period,
                        adx_threshold=adx_threshold,
                        adx_r_mode=st.session_state.get('adx_r_mode', "⚪ Bonus Confluence (Default)")  # ✅ Tambah parameter
                    )
                st.session_state.last_scan_ts = time.time()
                st.rerun()
    with col2:
        if st.button("🗑️ Reset", width="stretch"):
            st.session_state.active_swings = {}
            st.session_state.notified_signals = set()
            st.session_state.notified_new_swings = set()
            clear_logs()
            st.rerun()

    st.divider()

    st.subheader("📜 Log Aktivitas")
    log_container = st.container(height=250)
    with log_container:
        logs = get_logs()
        if not logs:
            st.caption("Belum ada aktivitas.")
        else:
            for log_entry in reversed(logs[-40:]):
                st.text(log_entry)


# ==========================================
# ✅ AUTO-SCAN BACKGROUND — DIPINDAH KE SINI (SEBELUM render dashboard)
# Ini fix untuk delay 1 siklus: data hasil auto-scan langsung ikut
# diproses oleh blok deteksi sinyal baru + audio di bawah, pada rerun
# yang sama.
# ==========================================
run_auto_scan_if_due(
    scan_mode=st.session_state.scan_mode,
    timeframes=timeframes,
    symbols_to_scan=symbols_to_scan,
    adx_period=st.session_state.get('adx_period', 14),
    adx_threshold=st.session_state.get('adx_threshold', 25),
)


# ==========================================
# 3. Dashboard Posisi Terbuka (MT5)
# ==========================================
st.markdown("---")
st.subheader("💼 Portofolio & Posisi Terbuka di MT5")

summary = get_portfolio_summary()

col_p1, col_p2, col_p3, col_p4 = st.columns(4)
with col_p1:
    st.metric("📊 Total Posisi", summary['total_positions'])
with col_p2:
    st.metric("🟢 Posisi BUY", summary['buy_count'])
with col_p3:
    st.metric("🔴 Posisi SELL", summary['sell_count'])
with col_p4:
    delta_color = "normal" if summary['total_profit'] >= 0 else "inverse"
    st.metric(
        "💰 Floating P/L",
        f"${summary['total_profit']:.2f}",
        delta=f"{summary['total_profit']:+.2f}",
        delta_color=delta_color
    )

with st.expander("📂 Lihat Detail Posisi Terbuka (Klik untuk membuka)", expanded=False):
    if summary['total_positions'] > 0:
        df_positions = get_open_positions()
        if not df_positions.empty:
            styled_pos = df_positions.style.map(highlight_profit, subset=['profit', 'profit_pips'])
            st.dataframe(styled_pos, width="stretch", hide_index=True, height=300)
        else:
            st.info("Gagal mengambil data detail posisi dari MT5.")
    else:
        st.info("💤 Tidak ada posisi (order) yang sedang terbuka di MT5 saat ini.")


# ==========================================
# 4. Main Content: Dashboard Sinyal
# ==========================================
st.markdown("---")
st.subheader("📡 Sinyal Aktif (Swing Zone + ADX Filter + ADX in Range)")

# ✅ ENHANCEMENT: Filter 3 kolom (tambah ADX-R filter)
col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
with col_f1:
    filter_signal = st.selectbox(
        "Filter Arah:",
        ["Semua", "🟢 BUY Only", "🔴 SELL Only"],
    )
with col_f2:
    hide_weak_adx = st.checkbox(
        "🙈 Sembunyikan ADX Lemah",
        value=False,
        help=f"Sembunyikan sinyal dengan ADX < {adx_threshold} (Market Sideways)."
    )
# ✅ ENHANCEMENT: Filter ADX in Range
with col_f3:
    adx_r_only = st.checkbox(
        "🎯 Hanya ADX in Range",
        value=False,
        help="Hanya tampilkan swing dengan ADX berada di antara +DI dan -DI (high probability setup)."
    )

if st.session_state.active_swings:
    table_data = []
    new_signal_count = 0

    for key, data in st.session_state.active_swings.items():
        if filter_signal == "🟢 BUY Only" and data['direction'] != 'BUY':
            continue
        if filter_signal == "🔴 SELL Only" and data['direction'] != 'SELL':
            continue

        adx_val = data.get('adx', 0.0)
        adx_stat = data.get('adx_status', 'N/A')

        if hide_weak_adx and adx_val < adx_threshold:
            continue

        if adx_r_only and not data.get('adx_in_range', False):
            continue

        if key not in st.session_state.notified_new_swings:
            st.session_state.notified_new_swings.add(key)
            new_signal_count += 1
            play_alert_sound()

        sisa = calculate_remaining_candles(
            data['saved_time_str'], data['symbol'], data['tf'],
            data.get('validity_candles', 3)
        )

        direction_icon = "🟢 BUY" if data['direction'] == 'BUY' else "🔴 SELL"

        # ✅ BEDAKAN TIPE SINYAL
        signal_type = data.get('type', 'Swing Zone')

        if signal_type == 'ADX-R Early Warning':
            # ✅ ADX-R Early Warning (tanpa swing)
            display_signal = f"⚠️ {direction_icon} ADX-R Early Warning"
            harga_entry = "Menunggu swing..."
            zona_info = "⏳ Menunggu konfirmasi swing"
        else:
            # ✅ Swing Zone (normal)
            display_signal = f"{direction_icon} {data['sinyal']}"
            harga_entry = data['harga']
            zona_info = data['zona']

        bonus = data.get('bonus_status', '⏳ Menunggu data LTF...')
        di_status = "✅ YA" if "✅ DI" in bonus else "❌ TIDAK"
        choc_status = "✅ YA" if "⚡ CHoCH" in bonus else "❌ TIDAK"
        extreme_status = "✅ EXTREME!" if "🌟 EXTREME" in bonus else "❌ Normal"
        adx_r_status = "✅ YA" if data.get('adx_in_range', False) else "❌ TIDAK"

        table_data.append({
            'Tipe': signal_type,  # ✅ Kolom baru untuk bedakan tipe
            'Pair': data['symbol'],
            'TF': data['tf'],
            'Sinyal': display_signal,
            'Harga Entry': harga_entry,
            'Zona & Invalidation': zona_info,
            'ADX Status': adx_stat,
            'DI Cross?': di_status,
            'ADX-R?': adx_r_status,
            'CHoCH?': choc_status,
            'Extreme?': extreme_status,
            'Sisa Validitas': f"{sisa} Candle"
        })

    if new_signal_count > 0:
        st.toast(f"🔔 {new_signal_count} Sinyal Baru Terdeteksi!", icon="🔔")

    if table_data:
        df_table = pd.DataFrame(table_data)

        styled_df = df_table.style.apply(highlight_signal_row, axis=1)
        styled_df = styled_df.map(highlight_sisa_candle, subset=['Sisa Validitas'])

        # ✅ ENHANCEMENT: Update info_columns dengan ADX-R?
        info_columns = ['ADX Status', 'DI Cross?', 'ADX-R?', 'CHoCH?', 'Extreme?']
        styled_df = styled_df.map(highlight_info_columns, subset=info_columns)

        st.dataframe(
            styled_df,
            width="stretch",
            hide_index=True,
            height=450,
            column_config={
                "Tipe": st.column_config.TextColumn("Tipe", width="140px"),  # ✅ Baru
                "Pair": st.column_config.TextColumn("Pair", width="100px"),
                "TF": st.column_config.TextColumn("TF", width="60px"),
                "Sinyal": st.column_config.TextColumn("Sinyal", width="200px"),
                "Harga Entry": st.column_config.TextColumn("Harga Entry", width="120px"),
                "Zona & Invalidation": st.column_config.TextColumn("Zona & Invalidation", width="280px"),
                "ADX Status": st.column_config.TextColumn("ADX Status", width="120px"),
                "DI Cross?": st.column_config.TextColumn("DI Cross?", width="80px"),
                "ADX-R?": st.column_config.TextColumn("ADX-R?", width="80px"),
                "CHoCH?": st.column_config.TextColumn("CHoCH?", width="80px"),
                "Extreme?": st.column_config.TextColumn("Extreme?", width="100px"),
                "Sisa Validitas": st.column_config.TextColumn("Sisa Validitas", width="100px"),
            }
        )

        # ✅ ENHANCEMENT: Split metrics jadi 2 baris untuk kerapian
        buy_count = sum(1 for d in table_data if 'BUY' in d['Sinyal'])
        sell_count = sum(1 for d in table_data if 'SELL' in d['Sinyal'])
        strong_adx_count = sum(1 for d in table_data if 'STRONG' in d['ADX Status'])
        adx_r_count = sum(1 for d in table_data if d['ADX-R?'] == '✅ YA')  # ✅ Counter baru

        st.markdown("---")

        # Baris 1: Basic counts
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📊 Total Sinyal", len(table_data))
        with col2:
            st.metric("🟢 BUY", buy_count)
        with col3:
            st.metric("🔴 SELL", sell_count)

        # Baris 2: Quality indicators
        col4, col5 = st.columns(2)
        with col4:
            st.metric("🔥 ADX STRONG", strong_adx_count, help="Sinyal dengan tren sangat kuat (ADX > 35)")
        with col5:
            st.metric("🎯 ADX in Range", adx_r_count, help="Sinyal dengan ADX di antara +DI dan -DI (high probability)")
    else:
        st.info("💤 Tidak ada sinyal yang cocok dengan filter.")
else:
    st.info("💤 Tidak ada sinyal aktif. Klik **🔄 Scan Now** untuk memulai.")


# ==========================================
# ✅ PUTAR AUDIO DI BROWSER (JIKA FLAG DISSET)
# Sekarang dipanggil SETELAH auto-scan + deteksi sinyal di run yang sama.
# ==========================================
play_audio_in_browser()
