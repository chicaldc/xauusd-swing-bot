"""
Fungsi-fungsi helper yang sering digunakan di seluruh aplikasi.
Dipisah agar tidak mengotori file logika utama.
"""
import pandas as pd
from datetime import datetime, timedelta


# ==========================================
# 1. Format Harga (Price Formatting)
# ==========================================
def format_price(price: float, symbol: str = "") -> str:
    if not symbol:
        return f"{price:.5f}"

    symbol_upper = symbol.upper()

    # Pair JPY = 3 digit
    if "JPY" in symbol_upper:
        return f"{price:.3f}"

    # Index, Crypto, & GOLD = 2 digit
    if any(x in symbol_upper for x in ["US30", "NAS", "SPX", "BTC", "ETH", "XAU", "GOLD"]):
        return f"{price:.2f}"

    # Forex standar = 5 digit (atau 4 digit untuk pair lawas, tapi 5 lebih aman)
    return f"{price:.5f}"

def get_pip_value(symbol: str) -> float:
    """
    Kembalikan nilai 1 pip untuk simbol tertentu.
    """
    symbol_upper = symbol.upper()
    if "JPY" in symbol_upper:
        return 0.01
    return 0.0001


# ==========================================
# 2. Konversi Timeframe
# ==========================================
def tf_to_minutes(tf_name: str) -> int:
    """
    Konversi string timeframe ke menit.
    
    Contoh:
        "M15" -> 15
        "H1"  -> 60
        "H4"  -> 240
        "D1"  -> 1440
    """
    tf_map = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
        "W1": 10080,
        "MN1": 43200,
    }
    return tf_map.get(tf_name.upper(), 60)


def estimate_candle_close_time(tf_name: str) -> datetime:
    minutes = tf_to_minutes(tf_name)
    now = datetime.now()

    # Mulai dari tengah malam hari ini
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_since_midnight = now.hour * 60 + now.minute

    # Hitung kelipatan menit berikutnya
    next_candle_minutes = ((minutes_since_midnight // minutes) + 1) * minutes

    # Tambahkan ke awal hari — otomatis menangani overflow ke hari/minggu/bulan depan
    next_close = start_of_day + timedelta(minutes=next_candle_minutes)

    return next_close

# ==========================================
# 3. Styling DataFrame untuk Streamlit
# ==========================================
def highlight_signal_row(row):
    """
    Styling baris dataframe berdasarkan arah sinyal.
    Digunakan dengan df.style.apply(highlight_signal_row, axis=1)
    """
    sinyal = str(row.get('Sinyal', ''))
    if '🟢 BUY' in sinyal:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    elif '🔴 SELL' in sinyal:
        return ['background-color: #f8d7da; color: #721c24'] * len(row)
    return [''] * len(row)


def highlight_sisa_candle(val):
    val_str = str(val)
    # ✅ Tangani kasus validitas tak terbatas (BOS/CHoCH)
    if "∞" in val_str or "Aktif" in val_str:
        return 'background-color: #d1ecf1; color: #0c5460; font-weight: bold' # Biru muda
    
    try:
        sisa = int(val_str.split()[0])
        if sisa == 0:
            return 'background-color: #f8d7da; color: #721c24; font-weight: bold' # Merah
        elif sisa == 1:
            return 'background-color: #fff3cd; color: #856404; font-weight: bold' # Kuning
        return 'background-color: #d4edda; color: #155724' # Hijau
    except (ValueError, IndexError):
        return ''


# ==========================================
# 4. Validasi & Sanitasi
# ==========================================
def sanitize_symbol(symbol: str) -> str:
    """
    Bersihkan nama simbol dari spasi dan karakter aneh.
    """
    if not symbol:
        return ""
    return symbol.strip().upper().replace(" ", "")


def validate_symbols_list(symbols_input: str) -> list:
    """
    Validasi input string (satu simbol per baris) menjadi list simbol valid.
    """
    if not symbols_input:
        return []
    
    lines = symbols_input.strip().split('\n')
    result = []
    for line in lines:
        cleaned = sanitize_symbol(line)
        if cleaned:
            result.append(cleaned)
    return result


# ==========================================
# 5. Statistik Sinyal
# ==========================================
def compute_signal_summary(table_data: list) -> dict:
    """
    Hitung ringkasan sinyal dari list data tabel.
    
    Returns:
        dict dengan total, buy_count, sell_count, per_strategy
    """
    if not table_data:
        return {
            'total': 0, 'buy': 0, 'sell': 0, 'per_strategy': {}
        }
    
    buy_count = sum(1 for d in table_data if 'BUY' in d.get('Sinyal', ''))
    sell_count = sum(1 for d in table_data if 'SELL' in d.get('Sinyal', ''))
    
    # Per strategi
    per_strategy = {}
    for d in table_data:
        strat = d.get('Strategi', 'Unknown')
        if strat not in per_strategy:
            per_strategy[strat] = {'total': 0, 'buy': 0, 'sell': 0}
        per_strategy[strat]['total'] += 1
        if 'BUY' in d.get('Sinyal', ''):
            per_strategy[strat]['buy'] += 1
        elif 'SELL' in d.get('Sinyal', ''):
            per_strategy[strat]['sell'] += 1
    
    return {
        'total': len(table_data),
        'buy': buy_count,
        'sell': sell_count,
        'per_strategy': per_strategy
    }


# ==========================================
# 6. Time & Duration Helpers
# ==========================================
def time_ago(dt: datetime) -> str:
    """
    Konversi datetime ke string "X menit yang lalu" atau "X jam yang lalu".
    """
    if not isinstance(dt, datetime):
        return "?"
    
    delta = datetime.now() - dt
    seconds = int(delta.total_seconds())
    
    if seconds < 60:
        return f"{seconds} detik lalu"
    elif seconds < 3600:
        return f"{seconds // 60} menit lalu"
    elif seconds < 86400:
        return f"{seconds // 3600} jam lalu"
    else:
        return f"{seconds // 86400} hari lalu"


def format_duration(seconds: int) -> str:
    """Format durasi dalam detik menjadi string mudah dibaca."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"

def highlight_profit(val):
    """Styling untuk kolom profit: Hijau jika > 0, Merah jika < 0"""
    try:
        num = float(val)
        if num > 0:
            return 'background-color: #d4edda; color: #155724; font-weight: bold'
        elif num < 0:
            return 'background-color: #f8d7da; color: #721c24; font-weight: bold'
        return ''
    except (ValueError, TypeError):
        return ''
