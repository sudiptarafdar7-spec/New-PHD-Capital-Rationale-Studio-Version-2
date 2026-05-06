"""
Step 13: Generate Charts

Fetches candlestick stock charts from Dhan API and generates premium charts
with moving averages, RSI, and volume indicators.

Input: 
  - analysis/stocks_with_analysis.csv (from Step 12)
  - Dhan API key from database
Output: 
  - charts/*.png (chart images)
  - analysis/stocks_with_chart.csv
"""

import os
import time
import json
import pandas as pd
import numpy as np
import psycopg2
import requests
import pytz
import matplotlib

matplotlib.use('Agg')  # Non-GUI backend for server environment
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# Constants
IST = pytz.timezone("Asia/Kolkata")
BASE_URL = "https://api.dhan.co/v2"


def get_dhan_api_key():
    """Fetch Dhan API key from database"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()

        cursor.execute("""
            SELECT key_value 
            FROM api_keys 
            WHERE LOWER(provider) = 'dhan'
            LIMIT 1
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return result[0]
        else:
            raise ValueError(
                "Dhan API key not found in database. Please add it in API Keys settings."
            )

    except Exception as e:
        raise Exception(f"Failed to fetch Dhan API key: {str(e)}")


def parse_date(s: str) -> datetime.date:
    """Accept YYYY-MM-DD or DD-MM-YYYY or DD/MM/YYYY"""
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized DATE format: {s!r}")


def parse_time(s: str):
    """Accept HH:MM:SS, HH:MM or HH.MM.SS"""
    s = str(s).strip().replace(".", ":")
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.hour, dt.minute, getattr(dt, "second", 0)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized START TIME format: {s!r}")


def _post(path: str,
          payload: dict,
          headers: dict,
          max_retries: int = 4) -> dict:
    """POST with retry on typical transient errors"""
    for attempt in range(max_retries):
        r = requests.post(f"{BASE_URL}{path}",
                          headers=headers,
                          json=payload,
                          timeout=30)
        if r.ok:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2**attempt)
            continue
        # Log the error response for debugging
        try:
            error_msg = r.json()
            print(f"  ⚠️  Dhan API Error {r.status_code}: {error_msg}")
            print(f"  📦 Payload: {payload}")
        except:
            print(f"  ⚠️  Dhan API Error {r.status_code}: {r.text}")
            print(f"  📦 Payload: {payload}")
        r.raise_for_status()
    raise RuntimeError("Max retries exceeded")


def _is_empty_payload(d: dict) -> bool:
    """Detect if Dhan returned empty arrays payload"""
    if not isinstance(d, dict) or not d:
        return True
    for key in ("open", "high", "low", "close", "volume", "timestamp"):
        arr = d.get(key, [])
        if isinstance(arr, list) and len(arr) > 0:
            return False
    return True


def zip_candles(d: dict) -> pd.DataFrame:
    """Convert Dhan arrays to DataFrame with IST index"""
    if _is_empty_payload(d):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    cols = ["open", "high", "low", "close", "volume", "timestamp"]
    n = min(len(d.get(c, [])) for c in cols if c in d)
    if n == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame({c: d[c][:n] for c in cols})
    dt = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
    df = df.assign(datetime=dt).set_index("datetime").drop(
        columns=["timestamp"])

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    return df


def get_daily_history(security_id: str,
                      start_date,
                      end_date_non_inclusive,
                      headers: dict,
                      exchange_segment: str = "NSE_EQ") -> pd.DataFrame:
    """Fetch daily historical data from Dhan API"""
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": "EQUITY",
        "expiryCode": 0,
        "oi": False,
        "fromDate": start_date.strftime("%Y-%m-%d"),
        "toDate": end_date_non_inclusive.strftime("%Y-%m-%d")
    }
    data = _post("/charts/historical", payload, headers)
    return zip_candles(data)


def get_intraday_1m(security_id: str,
                    from_dt_local: datetime,
                    to_dt_local: datetime,
                    headers: dict,
                    exchange_segment: str = "NSE_EQ") -> pd.DataFrame:
    """Fetch 1-minute intraday data from Dhan API"""
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": "EQUITY",
        "interval": "1",
        "oi": False,
        "fromDate": from_dt_local.strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": to_dt_local.strftime("%Y-%m-%d %H:%M:%S"),
    }
    data = _post("/charts/intraday", payload, headers)
    return zip_candles(data)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Wilder's RSI(14) with EWM smoothing"""
    if len(series) < 2:
        return pd.Series([np.nan] * len(series), index=series.index)

    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1 / period,
                                                    adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1 / period,
                                                        adjust=False).mean()

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = roll_up / roll_down.replace(0, np.nan)
        r = 100 - (100 / (1 + rs))
    return r


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA 20/50/100/200 and RSI(14)"""
    out = df.copy()
    for n in [20, 50, 100, 200]:
        out[f"MA{n}"] = out["close"].rolling(n, min_periods=1).mean()
    out["RSI14"] = rsi(out["close"], 14)
    return out


def _aggregate_partial(df_1m: pd.DataFrame) -> pd.Series:
    """Aggregate intraday 1m into OHLCV for partial last period"""
    if df_1m is None or df_1m.empty:
        return None
    return pd.Series({
        "open": df_1m["open"].iloc[0],
        "high": df_1m["high"].max(),
        "low": df_1m["low"].min(),
        "close": df_1m["close"].iloc[-1],
        "volume": df_1m["volume"].sum()
    })


def resample_to(df_daily: pd.DataFrame, chart_type: str,
                intraday_partial: pd.DataFrame) -> pd.DataFrame:
    """Resample daily to requested timeframe with partial last candle"""
    if df_daily is None or df_daily.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    chart_type = (chart_type or "").strip().lower()

    if chart_type == "daily":
        df = df_daily.copy()
        part = _aggregate_partial(intraday_partial)
        if part is not None:
            day = intraday_partial.index[-1].date()
            idx = IST.localize(datetime(day.year, day.month, day.day, 15, 30))
            df = df[df.index.date != day]
            partial_df = pd.DataFrame(part).T
            partial_df.index = [idx]
            df = pd.concat([df, partial_df]).sort_index()
        return df

    elif chart_type == "weekly":
        # Convert to UTC naive index for stable resampling
        df_tmp = df_daily.copy()
        df_tmp.index = df_tmp.index.tz_convert("UTC").tz_localize(None)

        weekly = df_tmp.resample("W-FRI").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna(how="any")

        # Convert back to IST timezone
        weekly.index = weekly.index.tz_localize("UTC").tz_convert(IST)

        # Handle current partial week candle (if intraday available)
        part = _aggregate_partial(intraday_partial)
        if part is not None:
            last_dt = intraday_partial.index[-1]

            # Calculate current week boundaries
            start_of_week = last_dt - timedelta(days=last_dt.weekday())
            start_of_week = start_of_week.replace(hour=0,
                                                  minute=0,
                                                  second=0,
                                                  microsecond=0)
            end_of_week = start_of_week + timedelta(
                days=4, hours=15, minutes=30)

            # Filter daily candles within this week
            done_days = df_daily[(df_daily.index >= start_of_week)
                                 & (df_daily.index <= end_of_week)]

            open_price = done_days["open"].iloc[
                0] if not done_days.empty else intraday_partial["open"].iloc[0]
            high_price = max(
                done_days["high"].max() if not done_days.empty else -np.inf,
                part["high"])
            low_price = min(
                done_days["low"].min() if not done_days.empty else np.inf,
                part["low"])
            close_price = part["close"]
            vol_sum = (done_days["volume"].sum()
                       if not done_days.empty else 0) + part["volume"]

            idx = IST.localize(
                datetime(end_of_week.year, end_of_week.month, end_of_week.day,
                         15, 30))

            # Replace the last candle if it overlaps with current week
            if not weekly.empty and idx <= weekly.index[-1]:
                weekly = weekly.iloc[:-1]

            weekly.loc[idx] = [
                open_price, high_price, low_price, close_price, vol_sum
            ]

        return weekly.sort_index()

    elif chart_type == "monthly":
        monthly = df_daily.resample("M").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna(how="any")
        part = _aggregate_partial(intraday_partial)
        if part is not None and not monthly.empty:
            last_dt = intraday_partial.index[-1]
            start_month = (
                pd.Timestamp(last_dt).tz_convert(IST)).normalize().replace(
                    day=1)
            done_days = df_daily[(df_daily.index >= start_month)
                                 & (df_daily.index.date < last_dt.date())]

            open_price = done_days["open"].iloc[
                0] if not done_days.empty else intraday_partial["open"].iloc[0]
            high_price = max(
                done_days["high"].max() if not done_days.empty else -np.inf,
                part["high"])
            low_price = min(
                done_days["low"].min() if not done_days.empty else np.inf,
                part["low"])
            close_price = part["close"]
            vol_sum = (done_days["volume"].sum()
                       if not done_days.empty else 0) + part["volume"]

            month_end = (pd.Timestamp(last_dt).tz_convert(IST)
                         ).normalize() + pd.offsets.MonthEnd(0)
            idx = month_end + pd.Timedelta(hours=15, minutes=30)

            if len(monthly) > 0:
                monthly = monthly.iloc[:-1]
            partial_df = pd.DataFrame(
                {
                    "open": [open_price],
                    "high": [high_price],
                    "low": [low_price],
                    "close": [close_price],
                    "volume": [vol_sum]
                },
                index=[idx])
            monthly = pd.concat([monthly, partial_df]).sort_index()
        return monthly

    else:
        return df_daily.copy()


def _pad_right(df: pd.DataFrame, n_steps: int = 6) -> pd.DataFrame:
    """Add empty time steps to the right for whitespace"""
    if df is None or df.empty or len(df.index) < 2:
        return df

    idx = df.index
    try:
        step = idx[-1] - idx[-2]
        if step <= pd.Timedelta(0):
            step = pd.Timedelta(days=1)
    except Exception:
        step = pd.Timedelta(days=1)

    fut = [idx[-1] + (i * step) for i in range(1, n_steps + 1)]
    pad = pd.DataFrame(np.nan,
                       index=pd.DatetimeIndex(fut, tz=idx.tz),
                       columns=["open", "high", "low", "close", "volume"])
    return pd.concat([df, pad])


def make_premium_chart(df: pd.DataFrame,
                       meta: dict,
                       save_path: str,
                       cmp_value: float = None,
                       cmp_datetime: datetime = None):
    """Generate premium chart with candles, volume, RSI and MAs"""
    if df is None or df.empty or len(df) == 0:
        raise ValueError("No data to plot.")

    df_plot = df[["open", "high", "low", "close", "volume"]].copy()
    df_plot = _pad_right(df_plot, n_steps=3)
    df_aligned = df.reindex(df_plot.index)

    ma_colors = {
        "MA20": "#1f77b4",
        "MA50": "#ff7f0e",
        "MA100": "#2ca02c",
        "MA200": "#d62728",
    }

    ap = []
    for c in ["MA20", "MA50", "MA100", "MA200"]:
        if c in df_aligned.columns and df_aligned[c].notna().sum() >= 2:
            ap.append(
                mpf.make_addplot(df_aligned[c],
                                 panel=0,
                                 type='line',
                                 width=1.2,
                                 color=ma_colors[c]))

    have_rsi = ("RSI14" in df_aligned.columns
                and df_aligned["RSI14"].notna().sum() >= 2)
    if have_rsi:
        ap.append(
            mpf.make_addplot(df_aligned["RSI14"],
                             panel=2,
                             type='line',
                             ylabel='RSI(14)',
                             ylim=(0, 100)))

    mc = mpf.make_marketcolors(up='g',
                               down='r',
                               edge='inherit',
                               wick='inherit',
                               volume='inherit')
    s = mpf.make_mpf_style(marketcolors=mc,
                           gridstyle='-',
                           gridcolor='#e8e8e8',
                           y_on_right=True)

    fig, axes = mpf.plot(df_plot,
                         type='candle',
                         style=s,
                         addplot=ap,
                         volume=True,
                         panel_ratios=(6, 2, 2) if have_rsi else (6, 2),
                         returnfig=True,
                         figsize=(14, 7),
                         datetime_format='%d %b %y',
                         tight_layout=False)

    ax_price = axes[0]
    ax_price.yaxis.set_ticks_position('right')
    ax_price.yaxis.tick_right()

    # Adjust subplot spacing to reduce left margin and prevent right cropping
    fig.subplots_adjust(left=0.06, right=0.94, top=0.95, bottom=0.08)

    last_ts = df.index[-1]
    last_close = float(df["close"].iloc[-1])

    # Use CMP value and datetime if provided, otherwise use last close and timestamp
    cmp_display = cmp_value if cmp_value is not None else last_close
    display_ts = cmp_datetime if cmp_datetime is not None else last_ts

    last_ts_str = last_ts.astimezone(IST).strftime('%a %d %b %y • %H:%M:%S')
    cmp_date_only = display_ts.astimezone(IST).strftime('%d %b %Y')
    cmp_time_only = display_ts.astimezone(IST).strftime('%H:%M:%S')

    ax_price.set_xlabel(f"Last (running) candle close: {last_ts_str}",
                        fontsize=10)

    ax_price.text(
        0.01,
        0.98,
        f"{meta.get('SHORT NAME','')}  •  {meta.get('CHART TYPE','')}  •  {meta.get('EXCHANGE','')}",
        transform=ax_price.transAxes,
        ha='left',
        va='top',
        fontsize=12,
        fontweight='bold')

    legend_lines = []
    legend_labels = []
    for c in ["MA20", "MA50", "MA100", "MA200"]:
        if c in df_aligned.columns:
            line, = ax_price.plot([], [], lw=2, color=ma_colors[c])
            legend_lines.append(line)
            legend_labels.append(c)

    if legend_lines:
        leg = ax_price.legend(legend_lines,
                              legend_labels,
                              loc='upper left',
                              bbox_to_anchor=(0.006, 0.90),
                              frameon=True,
                              framealpha=0.9,
                              borderpad=0.6,
                              fontsize=9)
        try:
            leg.get_frame().set_boxstyle("Round,pad=0.3,rounding_size=2")
        except Exception:
            pass

    # Draw CMP horizontal line
    ax_price.axhline(cmp_display,
                     linestyle='--',
                     linewidth=1.2,
                     color='#666666',
                     alpha=0.7)

    # Find the middle position of the chart for CMP label
    x_data_range = len(df.index)
    mid_position = int(x_data_range * 0.5)  # Middle of the chart

    # Add CMP label on the dotted line (middle of chart)
    ax_price.text(mid_position,
                  cmp_display,
                  f"  CMP: ₹{cmp_display:.2f}",
                  ha='left',
                  va='center',
                  fontsize=10,
                  fontweight='bold',
                  bbox=dict(boxstyle="round,pad=0.4",
                            fc="#ffffcc",
                            ec="#999999",
                            alpha=0.95),
                  zorder=10)

    # Add CMP with Date and Time on the right side (using CMP datetime from CSV)
    ax_price.text(0.98,
                  0.02,
                  f"CMP: ₹{cmp_display:.2f}\n{cmp_date_only}\n{cmp_time_only}",
                  transform=ax_price.transAxes,
                  ha='right',
                  va='bottom',
                  fontsize=9,
                  bbox=dict(boxstyle="round,pad=0.5",
                            fc="white",
                            ec="#666666",
                            alpha=0.90),
                  zorder=10)

    if have_rsi and len(axes) >= 3:
        ax_rsi = axes[2]
        ax_rsi.axhline(70,
                       linestyle=':',
                       linewidth=0.8,
                       color='red',
                       alpha=0.5)
        ax_rsi.axhline(30,
                       linestyle=':',
                       linewidth=0.8,
                       color='green',
                       alpha=0.5)

    fig.savefig(save_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)


def update_step_message(job_folder, message):
    """Update the step 13 message in the database"""
    try:
        job_id = os.path.basename(job_folder)
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE job_steps
            SET message = %s
            WHERE job_id = %s AND step_number = 13
        """, (message, job_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not update step message: {e}")


def run(job_folder):
    """
    Generate candlestick charts for each stock using Dhan API

    Args:
        job_folder: Path to job directory

    Returns:
        dict: Status, message, and output files
    """
    print("\n" + "=" * 60)
    print("STEP 13: Generate Charts")
    print(f"{'='*60}\n")

    try:
        # Input/output paths
        stocks_csv = os.path.join(job_folder, "analysis",
                                  "stocks_with_analysis.csv")
        charts_dir = os.path.join(job_folder, "charts")
        output_csv = os.path.join(job_folder, "analysis",
                                  "stocks_with_chart.csv")

        # Verify input file exists
        if not os.path.exists(stocks_csv):
            return {
                'status': 'failed',
                'message': f'Stocks with analysis file not found: {stocks_csv}'
            }

        # Create charts directory
        os.makedirs(charts_dir, exist_ok=True)

        # Get Dhan API key
        print("🔑 Retrieving Dhan API key from database...")
        api_key = get_dhan_api_key()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": api_key
        }
        print(f"✅ Dhan API key found\n")

        # Load stocks
        print("📊 Loading stocks with analysis...")
        update_step_message(job_folder, "Loading stocks...")
        df = pd.read_csv(stocks_csv)

        # Normalize column names
        def norm_col(x):
            return x.strip().upper().replace("\xa0", " ")

        df.columns = [norm_col(c) for c in df.columns]

        required = [
            "STOCK NAME", "STOCK SYMBOL", "LISTED NAME", "SHORT NAME",
            "SECURITY ID", "EXCHANGE", "INSTRUMENT", "SEGMENT", "START TIME",
            "DATE", "CMP", "CHART TYPE", "ANALYSIS"
        ]
        for c in required:
            if c not in df.columns:
                return {
                    'status': 'failed',
                    'message':
                    f'Missing column in stocks_with_analysis.csv: {c}'
                }

        print(f"✅ Loaded {len(df)} stocks\n")

        out_rows = []
        success_count = 0
        failed_count = 0

        # Process each stock
        for idx, row in df.iterrows():
            try:
                security_id = str(row["SECURITY ID"]).strip()
                # Remove decimal points from security ID if present (e.g., "1333.0" -> "1333")
                if '.' in security_id:
                    security_id = security_id.split('.')[0]

                short_name = str(row["SHORT NAME"]).strip()
                exchange = str(row["EXCHANGE"]).strip().upper()
                chart_type = str(row["CHART TYPE"]).strip().title()
                segment = str(row["SEGMENT"]).strip()

                # --- Determine correct exchange segment for Dhan API ---
                # Dhan API expects formats like: NSE_EQ, BSE_EQ, NSE_FNO, etc.
                # If segment is just a single letter like 'E', we need to build the full format
                if pd.notna(segment) and str(segment).strip().upper() not in ['', 'NAN']:
                    seg_value = str(segment).strip().upper()
                    # Check if segment is already in correct format (contains underscore)
                    if '_' in seg_value:
                        exchange_segment = seg_value
                    else:
                        # Single letter segment (E, D, F, etc.) - build full format
                        exchange_segment = f"{exchange}_EQ" if exchange in ["NSE", "BSE"] else "NSE_EQ"
                else:
                    exchange_segment = f"{exchange}_EQ" if exchange in ["NSE", "BSE"] else "NSE_EQ"

                progress_msg = f"Processing {idx+1}/{len(df)}: {short_name}..."
                print(f"[{idx+1}/{len(df)}] {short_name} ({chart_type}, {exchange_segment})...")
                update_step_message(job_folder, progress_msg)

                # Parse date and time
                date_obj = parse_date(str(row["DATE"]).strip())
                h, m, s = parse_time(str(row["START TIME"]).strip())
                end_dt_local = IST.localize(
                    datetime(date_obj.year, date_obj.month, date_obj.day, h, m,
                             s))

                # Historical window: last 8 months
                start_hist = date_obj - relativedelta(months=8)
                end_hist_non_inclusive = date_obj + timedelta(days=1)

                # Fetch historical daily data
                daily = get_daily_history(security_id, start_hist,
                                          end_hist_non_inclusive, headers,
                                          exchange_segment)

                # Fetch intraday data
                market_open = IST.localize(
                    datetime(date_obj.year, date_obj.month, date_obj.day, 9,
                             15, 0))
                if end_dt_local <= market_open:
                    intraday = pd.DataFrame(
                        columns=["open", "high", "low", "close", "volume"])
                else:
                    intraday = get_intraday_1m(security_id, market_open,
                                               end_dt_local, headers,
                                               exchange_segment)

                # Resample to timeframe
                df_tf = resample_to(daily, chart_type, intraday)

                if df_tf.empty:
                    raise ValueError(
                        "API returned no candles for this SECURITY ID / time window."
                    )

                # Add indicators
                df_tf = add_indicators(df_tf)

                # Get CMP value and datetime from CSV
                cmp_value = None
                try:
                    cmp_value = float(row["CMP"])
                except (ValueError, TypeError):
                    pass

                # Use the DATE and START TIME from CSV for CMP display
                cmp_datetime = IST.localize(
                    datetime(date_obj.year, date_obj.month, date_obj.day, h, m,
                             s))

                # Generate chart filename and save
                fname = f"{security_id}_{chart_type}_{date_obj.strftime('%Y%m%d')}_{h:02d}{m:02d}{s:02d}.png"
                save_path = os.path.join(charts_dir, fname)
                meta = {
                    "SHORT NAME": short_name,
                    "CHART TYPE": chart_type,
                    "EXCHANGE": exchange
                }
                make_premium_chart(df_tf, meta, save_path, cmp_value,
                                   cmp_datetime)

                # Save relative path for CSV
                relative_path = f"charts/{fname}"

                out_row = {c: row.get(c, "") for c in required}
                out_row["CHART PATH"] = relative_path
                out_rows.append(out_row)

                print(f"  ✅ Chart saved: {relative_path}")
                success_count += 1

                # Rate limiting
                time.sleep(1.5)

            except Exception as e:
                error_msg = str(e)
                print(f"  ❌ Error for {short_name}: {error_msg}")
                # Add failed row with empty chart path
                out_row = {c: row.get(c, "") for c in required}
                out_row["CHART PATH"] = ""
                out_rows.append(out_row)
                failed_count += 1
                # Continue with next stock - don't let one failure stop the whole process

        # Save output CSV
        print(f"\n💾 Saving output CSV...")
        out_df = pd.DataFrame(out_rows)
        out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print(f"✅ Saved {len(out_df)} records")
        print(f"✅ Success: {success_count} charts")
        if failed_count > 0:
            print(f"⚠️ Failed: {failed_count} charts")
        print(f"✅ Output: analysis/stocks_with_chart.csv\n")

        # Store full path for download functionality (only return files that exist)
        return {
            'status': 'success',
            'message':
            f'Generated {success_count} charts ({failed_count} failed)',
            'output_files':
            [f'{job_folder}/analysis/stocks_with_analysis.csv'
             ]  # Analysis CSV for download
        }

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Chart generation failed: {str(e)}'
        }


if __name__ == "__main__":
    # Test the step
    import sys
    if len(sys.argv) > 1:
        test_folder = sys.argv[1]
    else:
        test_folder = "backend/job_files/test_job"

    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {result['status'].upper()}")
    print(f"Message: {result['message']}")
    if 'output_files' in result:
        print(f"Output Files: {result['output_files']}")
    print(f"{'='*60}")
