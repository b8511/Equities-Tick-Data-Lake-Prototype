"""
Synthetic Equities Tick Data Generator
======================================
Generates realistic L1 trade and quote data for ~25 symbols over 30 trading days.
Deliberately injects data quality anomalies (crossed spreads, stale quotes,
price outliers) for the quality monitoring layer to detect.

Target: ~50M total rows (trades + quotes combined).
Output: CSV files ready for ClickHouse bulk insert.
"""

import csv
import os
import random
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).parent.parent / "data"
NUM_TRADING_DAYS = 30
START_DATE = datetime(2025, 12, 1, tzinfo=timezone.utc)

# Market hours (US Eastern approximation in UTC: 14:30 - 21:00)
MARKET_OPEN_HOUR, MARKET_OPEN_MIN = 14, 30
MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN = 21, 0

# Anomaly injection rates
CROSSED_SPREAD_RATE = 0.001       # 0.1% of quotes
STALE_QUOTE_RATE = 0.002          # 0.2% of quotes will have a > 5s gap flagged
PRICE_OUTLIER_RATE = 0.0005       # 0.05% of trades
MISSING_FIELD_RATE = 0.0003       # 0.03%

EXCHANGES = ["NYSE", "NASDAQ", "ARCA", "BATS", "IEX", "EDGX"]
TRADE_CONDITIONS = ["@", "F", "T", "I", "W"]  # regular, intermarket sweep, ext hours, etc.

# Batch size for CSV writes
BATCH_SIZE = 100_000


@dataclass
class SymbolConfig:
    """Per-symbol simulation parameters."""
    symbol: str
    base_price: float
    daily_vol: float           # annualised volatility
    avg_spread_bps: float      # average spread in basis points
    avg_trade_size: int
    trades_per_day: int        # approximate
    quotes_per_day: int        # approximate (typically 3-5x trades)


# 25 symbols with varied characteristics
SYMBOLS = [
    SymbolConfig("AAPL",  175.0,  0.25, 1.0,  150, 40000, 150000),
    SymbolConfig("MSFT",  380.0,  0.22, 0.8,  100, 35000, 130000),
    SymbolConfig("GOOGL", 140.0,  0.28, 1.2,  80,  25000, 100000),
    SymbolConfig("AMZN",  180.0,  0.30, 1.0,  90,  30000, 110000),
    SymbolConfig("TSLA",  250.0,  0.50, 2.0,  120, 50000, 180000),
    SymbolConfig("META",  500.0,  0.32, 0.9,  70,  28000, 105000),
    SymbolConfig("NVDA",  800.0,  0.45, 0.5,  60,  45000, 160000),
    SymbolConfig("JPM",   190.0,  0.20, 1.5,  200, 20000,  75000),
    SymbolConfig("BAC",    35.0,  0.22, 3.0,  500, 25000,  90000),
    SymbolConfig("GS",    400.0,  0.25, 1.0,  50,  12000,  45000),
    SymbolConfig("MS",     90.0,  0.24, 1.8,  180, 15000,  55000),
    SymbolConfig("C",      55.0,  0.23, 2.5,  300, 18000,  65000),
    SymbolConfig("WFC",    50.0,  0.20, 2.0,  250, 16000,  60000),
    SymbolConfig("BLK",   800.0,  0.18, 1.2,  30,   8000,  30000),
    SymbolConfig("UNH",   550.0,  0.20, 0.8,  40,  10000,  38000),
    SymbolConfig("JNJ",   160.0,  0.15, 1.0,  120, 12000,  45000),
    SymbolConfig("V",     275.0,  0.18, 0.7,  80,  14000,  52000),
    SymbolConfig("MA",    450.0,  0.20, 0.6,  60,  11000,  42000),
    SymbolConfig("PG",    160.0,  0.14, 1.2,  100, 10000,  38000),
    SymbolConfig("XOM",   105.0,  0.25, 1.5,  200, 18000,  68000),
    SymbolConfig("CVX",   155.0,  0.24, 1.3,  150, 14000,  52000),
    SymbolConfig("HD",    370.0,  0.20, 0.9,  60,  10000,  38000),
    SymbolConfig("DIS",    95.0,  0.30, 2.0,  180, 16000,  60000),
    SymbolConfig("NFLX",  600.0,  0.35, 1.0,  50,  15000,  55000),
    SymbolConfig("AMD",   150.0,  0.45, 1.5,  200, 40000, 150000),
]


def trading_days(start: datetime, n: int) -> list[datetime]:
    """Generate n weekday dates starting from start."""
    days = []
    current = start
    while len(days) < n:
        if current.weekday() < 5:  # Mon-Fri
            days.append(current)
        current += timedelta(days=1)
    return days


def intraday_timestamps(day: datetime, n: int, rng: np.random.Generator) -> np.ndarray:
    """
    Generate n sorted timestamps within market hours for a given day.
    Uses a Poisson-like process with U-shaped intensity (more activity at open/close).
    """
    open_ts = day.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MIN, second=0, microsecond=0)
    close_ts = day.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MIN, second=0, microsecond=0)
    total_seconds = (close_ts - open_ts).total_seconds()

    # U-shaped distribution: beta(0.7, 0.7) concentrates near open and close
    fracs = rng.beta(0.7, 0.7, size=n)
    fracs.sort()

    # Convert fractions to microsecond offsets
    offsets_us = (fracs * total_seconds * 1_000_000).astype(np.int64)
    base_us = int(open_ts.timestamp() * 1_000_000)
    return base_us + offsets_us


def format_ts(us_timestamp: int) -> str:
    """Format microsecond unix timestamp to ClickHouse DateTime64(6) string."""
    s, us = divmod(us_timestamp, 1_000_000)
    dt = datetime.fromtimestamp(s, tz=timezone.utc)
    return dt.strftime(f"%Y-%m-%d %H:%M:%S.{us:06d}")


def simulate_prices(
    base: float, vol: float, n: int, rng: np.random.Generator
) -> np.ndarray:
    """GBM-like price path with mean reversion."""
    dt = 1.0 / (252 * 23400)  # ~1 second in trading-year units
    sigma = vol * math.sqrt(dt)
    returns = rng.normal(0, sigma, size=n)
    # Light mean reversion
    prices = np.empty(n)
    prices[0] = base
    for i in range(1, n):
        drift = -0.01 * (prices[i - 1] - base) * dt
        prices[i] = prices[i - 1] * (1 + drift + returns[i])
    return np.round(prices, 2)


def generate_quotes_for_day(
    sym: SymbolConfig, day: datetime, price_path: np.ndarray,
    timestamps_us: np.ndarray, rng: np.random.Generator
) -> list[list]:
    """Generate quote rows for one symbol-day."""
    n = len(timestamps_us)
    half_spread = sym.base_price * (sym.avg_spread_bps / 10000) / 2

    rows = []
    for i in range(n):
        mid = price_path[i] if i < len(price_path) else price_path[-1]
        spread_noise = rng.exponential(half_spread)
        bid = round(mid - spread_noise, 2)
        ask = round(mid + rng.exponential(half_spread), 2)
        bid_size = int(rng.choice([100, 200, 300, 500, 1000]) * max(1, rng.poisson(3)))
        ask_size = int(rng.choice([100, 200, 300, 500, 1000]) * max(1, rng.poisson(3)))
        exchange = rng.choice(EXCHANGES)
        flag = "OK"

        # --- Anomaly injection ---
        r = rng.random()
        if r < CROSSED_SPREAD_RATE:
            bid, ask = ask + 0.05, bid - 0.05  # crossed
            flag = "CROSSED_SPREAD"
        elif r < CROSSED_SPREAD_RATE + STALE_QUOTE_RATE:
            flag = "STALE"
        elif r < CROSSED_SPREAD_RATE + STALE_QUOTE_RATE + MISSING_FIELD_RATE:
            bid_size = 0
            flag = "MISSING_FIELD"

        ts_str = format_ts(int(timestamps_us[i]))
        rows.append([
            sym.symbol, ts_str, bid, ask, bid_size, ask_size, exchange, flag
        ])

    return rows


def generate_trades_for_day(
    sym: SymbolConfig, day: datetime, price_path: np.ndarray,
    timestamps_us: np.ndarray, rng: np.random.Generator
) -> list[list]:
    """Generate trade rows for one symbol-day."""
    n = len(timestamps_us)
    rows = []

    for i in range(n):
        mid = price_path[i] if i < len(price_path) else price_path[-1]
        # Trade price: mid + noise, biased slightly to bid or ask side
        slippage = rng.normal(0, sym.base_price * 0.0001)
        trade_price = round(mid + slippage, 2)
        trade_size = max(1, int(rng.lognormal(math.log(sym.avg_trade_size), 0.8)))
        exchange = rng.choice(EXCHANGES)
        condition = rng.choice(TRADE_CONDITIONS)
        flag = "OK"

        # --- Anomaly injection ---
        r = rng.random()
        if r < PRICE_OUTLIER_RATE:
            trade_price = round(mid * (1 + rng.choice([-1, 1]) * rng.uniform(0.05, 0.15)), 2)
            flag = "PRICE_OUTLIER"
        elif r < PRICE_OUTLIER_RATE + MISSING_FIELD_RATE:
            trade_size = 0
            flag = "MISSING_FIELD"

        ts_str = format_ts(int(timestamps_us[i]))
        rows.append([
            sym.symbol, ts_str, trade_price, trade_size, exchange, condition, flag
        ])

    return rows


def write_csv_batch(filepath: Path, rows: list[list], header: list[str], mode: str = "a"):
    """Append rows to CSV file."""
    write_header = mode == "w" or not filepath.exists()
    with open(filepath, mode, newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)
        writer.writerows(rows)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trades_path = OUTPUT_DIR / "trades.csv"
    quotes_path = OUTPUT_DIR / "quotes.csv"

    # Wipe previous output
    for p in [trades_path, quotes_path]:
        if p.exists():
            p.unlink()

    rng = np.random.default_rng(seed=42)
    days = trading_days(START_DATE, NUM_TRADING_DAYS)

    trade_header = ["symbol", "timestamp", "trade_price", "trade_size",
                    "exchange", "trade_condition", "data_quality_flag"]
    quote_header = ["symbol", "timestamp", "bid_price", "ask_price",
                    "bid_size", "ask_size", "exchange", "data_quality_flag"]

    total_trades = 0
    total_quotes = 0

    # Initialise files with headers
    write_csv_batch(trades_path, [], trade_header, mode="w")
    write_csv_batch(quotes_path, [], quote_header, mode="w")

    for day_idx, day in enumerate(days):
        day_str = day.strftime("%Y-%m-%d")
        print(f"[{day_idx+1}/{NUM_TRADING_DAYS}] Generating {day_str} ...")

        trade_buffer = []
        quote_buffer = []

        for sym in SYMBOLS:
            # Generate price path for the day (use max of trade/quote count)
            n_max = max(sym.trades_per_day, sym.quotes_per_day)
            price_path = simulate_prices(sym.base_price, sym.daily_vol, n_max, rng)

            # Timestamps
            trade_ts = intraday_timestamps(day, sym.trades_per_day, rng)
            quote_ts = intraday_timestamps(day, sym.quotes_per_day, rng)

            trade_rows = generate_trades_for_day(sym, day, price_path, trade_ts, rng)
            quote_rows = generate_quotes_for_day(sym, day, price_path, quote_ts, rng)

            trade_buffer.extend(trade_rows)
            quote_buffer.extend(quote_rows)

            # Flush in batches to control memory
            if len(trade_buffer) >= BATCH_SIZE:
                write_csv_batch(trades_path, trade_buffer, trade_header)
                total_trades += len(trade_buffer)
                trade_buffer = []
            if len(quote_buffer) >= BATCH_SIZE:
                write_csv_batch(quotes_path, quote_buffer, quote_header)
                total_quotes += len(quote_buffer)
                quote_buffer = []

        # Flush remaining
        if trade_buffer:
            write_csv_batch(trades_path, trade_buffer, trade_header)
            total_trades += len(trade_buffer)
        if quote_buffer:
            write_csv_batch(quotes_path, quote_buffer, quote_header)
            total_quotes += len(quote_buffer)

        print(f"    cumulative: {total_trades:,} trades, {total_quotes:,} quotes")

    print(f"\nDone. Total: {total_trades:,} trades, {total_quotes:,} quotes")
    print(f"Files: {trades_path}, {quotes_path}")


if __name__ == "__main__":
    main()
