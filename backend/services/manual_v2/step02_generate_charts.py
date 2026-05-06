"""
Manual Rationale Step 2: Generate Stock Charts

Fetches candlestick stock charts from Dhan API and generates premium charts
with moving averages, RSI, and volume indicators.

Input: 
  - analysis/stocks_with_cmp.csv (from Step 1)
  - Dhan API key from database
Output: 
  - charts/*.png (chart images)
  - analysis/stocks_with_charts.csv
"""

import os
import time
import pandas as pd
import numpy as np
import requests
import pytz
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from backend.utils.database import get_db_cursor

IST = pytz.timezone("Asia/Kolkata")
BASE_URL = "https://api.dhan.co/v2"


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
    raise ValueError(f"Unrecognized TIME format: {s!r}")


def _post(path: str, payload: dict, headers: dict, max_retries: int = 4) -> dict:
    """POST with retry on typical transient errors"""
    for attempt in range(max_retries):
        r = requests.post(f"{BASE_URL}{path}", headers=headers, json=payload, timeout=30)
        if r.ok:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2**attempt)
            continue
        try:
            error_msg = r.json()
            print(f"  ⚠️  Dhan API Error {r.status_code}: {error_msg}")
        except:
            print(f"  ⚠️  Dhan API Error {r.status_code}: {r.text}")
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
    df = df.assign(datetime=dt).set_index("datetime").drop(columns=["timestamp"])

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    return df


def get_daily_history(security_id: str, start_date, end_date_non_inclusive,
                     headers: dict, exchange_segment: str = "NSE_EQ") -> pd.DataFrame:
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


def get_intraday_1m(security_id: str, from_dt_local: datetime, to_dt_local: datetime,
                   headers: dict, exchange_segment: str = "NSE_EQ") -> pd.DataFrame:
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
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1/period, adjust=False).mean()

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
    pad = pd.DataFrame(np.nan, index=pd.DatetimeIndex(fut, tz=idx.tz),
                      columns=["open", "high", "low", "close", "volume"])
    return pd.concat([df, pad])


def make_premium_chart(df: pd.DataFrame, meta: dict, save_path: str,
                      cmp_value: float = None, cmp_datetime: datetime = None):
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
            ap.append(mpf.make_addplot(df_aligned[c], panel=0, type='line',
                                      width=1.2, color=ma_colors[c]))

    have_rsi = ("RSI14" in df_aligned.columns and df_aligned["RSI14"].notna().sum() >= 2)
    if have_rsi:
        ap.append(mpf.make_addplot(df_aligned["RSI14"], panel=2, type='line',
                                  ylabel='RSI(14)', ylim=(0, 100)))

    mc = mpf.make_marketcolors(up='g', down='r', edge='inherit',
                               wick='inherit', volume='inherit')
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle='-',
                          gridcolor='#e8e8e8', y_on_right=True)

    fig, axes = mpf.plot(df_plot, type='candle', style=s, addplot=ap,
                        volume=True, panel_ratios=(6, 2, 2) if have_rsi else (6, 2),
                        returnfig=True, figsize=(14, 7),
                        datetime_format='%d %b %y', tight_layout=False)

    ax_price = axes[0]
    ax_price.yaxis.set_ticks_position('right')
    ax_price.yaxis.tick_right()

    fig.subplots_adjust(left=0.06, right=0.94, top=0.95, bottom=0.08)

    last_ts = df.index[-1]
    last_close = float(df["close"].iloc[-1])

    cmp_display = cmp_value if cmp_value is not None else last_close
    display_ts = cmp_datetime if cmp_datetime is not None else last_ts

    last_ts_str = last_ts.astimezone(IST).strftime('%a %d %b %y • %H:%M:%S')
    cmp_date_only = display_ts.astimezone(IST).strftime('%d %b %Y')
    cmp_time_only = display_ts.astimezone(IST).strftime('%H:%M:%S')

    ax_price.set_xlabel(f"Last (running) candle close: {last_ts_str}", fontsize=10)

    ax_price.text(0.01, 0.98,
                 f"{meta.get('SHORT NAME','')}  •  {meta.get('CHART TYPE','')}  •  {meta.get('EXCHANGE','')}",
                 transform=ax_price.transAxes, ha='left', va='top',
                 fontsize=12, fontweight='bold')

    legend_lines = []
    legend_labels = []
    for c in ["MA20", "MA50", "MA100", "MA200"]:
        if c in df_aligned.columns:
            line, = ax_price.plot([], [], lw=2, color=ma_colors[c])
            legend_lines.append(line)
            legend_labels.append(c)

    if legend_lines:
        leg = ax_price.legend(legend_lines, legend_labels, loc='upper left',
                             bbox_to_anchor=(0.006, 0.90), frameon=True,
                             framealpha=0.9, borderpad=0.6, fontsize=9)
        try:
            leg.get_frame().set_boxstyle("Round,pad=0.3,rounding_size=2")
        except Exception:
            pass

    ax_price.axhline(cmp_display, linestyle='--', linewidth=1.2,
                    color='#666666', alpha=0.7)

    x_data_range = len(df.index)
    mid_position = int(x_data_range * 0.5)

    ax_price.text(mid_position, cmp_display, f"  CMP: ₹{cmp_display:.2f}",
                 ha='left', va='center', fontsize=10, fontweight='bold',
                 bbox=dict(boxstyle="round,pad=0.4", fc="#ffffcc",
                          ec="#999999", alpha=0.95), zorder=10)

    ax_price.text(0.98, 0.02,
                 f"CMP: ₹{cmp_display:.2f}\n{cmp_date_only}\n{cmp_time_only}",
                 transform=ax_price.transAxes, ha='right', va='bottom',
                 fontsize=9, bbox=dict(boxstyle="round,pad=0.5", fc="white",
                                      ec="#666666", alpha=0.90), zorder=10)

    if have_rsi and len(axes) >= 3:
        ax_rsi = axes[2]
        ax_rsi.axhline(70, linestyle=':', linewidth=0.8, color='red', alpha=0.5)
        ax_rsi.axhline(30, linestyle=':', linewidth=0.8, color='green', alpha=0.5)

    fig.savefig(save_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
    plt.close(fig)


def normalize_chart_type(chart_type_value: str) -> str:
    """Normalize and validate CHART TYPE value (Daily/Weekly/Monthly)"""
    if pd.isna(chart_type_value) or not chart_type_value:
        return 'Daily'
    
    normalized = str(chart_type_value).strip()
    normalized_upper = normalized.upper()
    
    valid_chart_types = {'DAILY': 'Daily', 'WEEKLY': 'Weekly', 'MONTHLY': 'Monthly'}
    
    return valid_chart_types.get(normalized_upper, 'Daily')


def generate_charts_for_stocks(job_id: str, job_folder: str, stocks_with_cmp):
    """
    Generate candlestick charts for each stock using Dhan API
    
    Args:
        job_id: Job ID
        job_folder: Path to job directory
        stocks_with_cmp: List of stocks from Step 1
        
    Returns:
        List of stock dictionaries with chart paths
    """
    print("\n" + "=" * 60)
    print("MANUAL RATIONALE STEP 2: GENERATE STOCK CHARTS")
    print("=" * 60 + "\n")

    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        stocks_csv = os.path.join(analysis_folder, 'stocks_with_cmp.csv')
        charts_dir = os.path.join(job_folder, 'charts')
        output_csv = os.path.join(analysis_folder, 'stocks_with_charts.csv')

        if not os.path.exists(stocks_csv):
            raise ValueError(f'Stocks with CMP file not found: {stocks_csv}')

        with get_db_cursor() as cursor:
            cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'dhan'")
            api_key_row = cursor.fetchone()
            dhan_api_key = api_key_row['key_value'] if api_key_row else None

        if not dhan_api_key:
            raise ValueError('Dhan API key not found in database. Please add it in API Keys settings.')

        os.makedirs(charts_dir, exist_ok=True)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": dhan_api_key
        }
        print(f"🔑 Dhan API key found")

        print("📊 Loading stocks with CMP...")
        df = pd.read_csv(stocks_csv)
        print(f"✅ Loaded {len(df)} stocks\n")

        print(f"📈 Generating charts for {len(df)} stocks...")

        out_rows = []
        success_count = 0
        failed_count = 0

        for idx, row in df.iterrows():
            try:
                security_id = str(row.get("SECURITY ID", "")).strip()
                if '.' in security_id:
                    security_id = security_id.split('.')[0]

                if not security_id or security_id == '' or security_id == 'nan':
                    print(f"  ⚠️ [{idx+1}/{len(df)}] Skipping - Missing SECURITY ID")
                    out_row = row.to_dict()
                    out_row["CHART PATH"] = ""
                    out_rows.append(out_row)
                    failed_count += 1
                    continue

                listed_name = str(row.get("LISTED NAME", "")).strip()
                short_name = str(row.get("SHORT NAME", listed_name)).strip()
                exchange = str(row.get("EXCHANGE", "NSE")).strip().upper()

                chart_type_raw = row.get("CHART TYPE", "")
                chart_type = normalize_chart_type(chart_type_raw)

                exchange_segment = f"{exchange}_EQ" if exchange in ["NSE", "BSE"] else "NSE_EQ"

                print(f"  [{idx+1}/{len(df)}] {short_name} ({chart_type}, {exchange_segment})...")

                date_obj = parse_date(str(row.get("DATE", "")).strip())
                time_str = str(row.get("TIME", "")).strip()
                h, m, s = parse_time(time_str)
                end_dt_local = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s))

                start_hist = date_obj - relativedelta(months=8)
                end_hist_non_inclusive = date_obj + timedelta(days=1)

                daily = get_daily_history(security_id, start_hist,
                                         end_hist_non_inclusive, headers,
                                         exchange_segment)

                market_open = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 9, 15, 0))
                if end_dt_local <= market_open:
                    intraday = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                else:
                    intraday = get_intraday_1m(security_id, market_open,
                                              end_dt_local, headers,
                                              exchange_segment)

                df_tf = resample_to(daily, chart_type, intraday)

                if df_tf.empty:
                    raise ValueError("API returned no candles for this SECURITY ID / time window.")

                df_tf = add_indicators(df_tf)

                cmp_value = None
                try:
                    cmp_value = float(row.get("CMP", 0))
                    if pd.isna(cmp_value) or cmp_value == 0:
                        cmp_value = None
                except (ValueError, TypeError):
                    pass

                cmp_datetime = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s))

                fname = f"{security_id}_{chart_type}_{date_obj.strftime('%Y%m%d')}_{h:02d}{m:02d}{s:02d}.png"
                save_path = os.path.join(charts_dir, fname)
                meta = {
                    "SHORT NAME": short_name,
                    "CHART TYPE": chart_type,
                    "EXCHANGE": exchange
                }
                make_premium_chart(df_tf, meta, save_path, cmp_value, cmp_datetime)

                relative_path = f"charts/{fname}"

                out_row = row.to_dict()
                out_row["CHART PATH"] = relative_path
                out_rows.append(out_row)

                print(f"      ✅ Chart saved: {relative_path}")
                success_count += 1

                time.sleep(1.5)

            except Exception as e:
                print(f"      ❌ Error: {str(e)}")
                out_row = row.to_dict()
                out_row["CHART PATH"] = ""
                out_rows.append(out_row)
                failed_count += 1

        print(f"\n💾 Saving output CSV...")
        out_df = pd.DataFrame(out_rows)
        out_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print(f"✅ Generated {success_count} charts")
        if failed_count > 0:
            print(f"⚠️  Failed: {failed_count} charts")
        print(f"   Output: {output_csv}\n")

        stocks_with_charts = out_df.to_dict('records')
        
        return stocks_with_charts

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise e
