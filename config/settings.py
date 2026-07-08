"""config/settings.py"""

# Jumlah candle yang diambil dari MT5
BARS_TO_FETCH = 100

# Validitas sinyal (dalam candle)
SIGNAL_VALIDITY_CANDLES = 3

# Interval auto-refresh (ms)
AUTO_REFRESH_INTERVAL_MS = 60000

# Default timeframe aktif
DEFAULT_TIMEFRAMES = ["M15", "M30", "H1", "H4"]
