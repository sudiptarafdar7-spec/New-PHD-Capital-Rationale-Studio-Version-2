"""
Bulk Rationale Step 5: Generate Charts
Generates premium stock charts using Dhan API (same design as Premium Rationale)
"""

import os
import time
import json
import requests
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from backend.utils.database import get_db_cursor

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf

IST = pytz.timezone("Asia/Kolkata")
BASE_URL = "https://api.dhan.co/v2"
MARKET_OPEN_TIME = (9, 15)
MARKET_CLOSE_TIME = (15, 30)


def get_dhan_api_key():
    """Get Dhan API key from database"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'dhan'")
        result = cursor.fetchone()
        if result and result['key_value']:
            return result['key_value'].strip()
    return None


def get_last_trading_day_close(dt_local: datetime) -> datetime:
    """Find the last trading day's closing time (3:30 PM)."""
    market_close_minutes = MARKET_CLOSE_TIME[0] * 60 + MARKET_CLOSE_TIME[1]
    requested_minutes = dt_local.hour * 60 + dt_local.minute
    
    if requested_minutes < market_close_minutes:
        search_date = dt_local.date() - timedelta(days=1)
    else:
        search_date = dt_local.date()
    
    while search_date.weekday() >= 5:
        search_date = search_date - timedelta(days=1)
    
    last_close = IST.localize(datetime(
        search_date.year, 
        search_date.month, 
        search_date.day,
        MARKET_CLOSE_TIME[0],
        MARKET_CLOSE_TIME[1],
        0
    ))
    
    return last_close


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
    return 15, 30, 0


def _post(path: str, payload: dict, headers: dict, max_retries: int = 4) -> dict:
    """POST with retry on typical transient errors"""
    for attempt in range(max_retries):
        try:
            r = requests.post(f"{BASE_URL}{path}", headers=headers, json=payload, timeout=30)
            if r.ok:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
                continue
            raise
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
    """Generate premium chart with candles, volume, RSI and MAs (same as Premium Rationale)"""
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


def run(job_folder, call_date=None, call_time=None):
    """
    Generate premium charts for all stocks (same design as Premium Rationale)
    
    Args:
        job_folder: Path to job directory
        call_date: Date from jobs table (YYYY-MM-DD format) - used for all stocks
        call_time: Time from jobs table (HH:MM:SS format) - used for all stocks
        
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'failed_charts': list,  # List of stocks that failed chart generation
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("BULK STEP 5: GENERATE STOCK CHARTS (PREMIUM DESIGN)")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        charts_folder = os.path.join(job_folder, 'charts')
        input_file = os.path.join(analysis_folder, 'stocks_with_cmp.csv')
        output_file = os.path.join(analysis_folder, 'stocks_with_charts.csv')
        failed_charts_file = os.path.join(analysis_folder, 'failed_charts.json')
        
        os.makedirs(charts_folder, exist_ok=True)
        
        if not os.path.exists(input_file):
            return {
                'success': False,
                'error': f'Input file not found: {input_file}'
            }
        
        dhan_key = get_dhan_api_key()
        if not dhan_key:
            return {
                'success': False,
                'error': 'Dhan API key not found. Please add it in Settings → API Keys.'
            }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": dhan_key
        }
        
        print(f"🔑 Dhan API key found")
        
        if call_date:
            print(f"📅 Using job date: {call_date}")
        if call_time:
            print(f"⏰ Using job time: {call_time}")
        
        print(f"📖 Loading stocks: {input_file}")
        df = pd.read_csv(input_file)
        print(f"✅ Loaded {len(df)} stocks")
        
        if 'CHART PATH' not in df.columns:
            df['CHART PATH'] = ''
        if 'CHART TYPE' not in df.columns:
            df['CHART TYPE'] = 'Daily'
        
        print(f"\n📈 Generating premium charts...")
        print("-" * 60)
        
        success_count = 0
        failed_count = 0
        failed_charts = []
        
        for idx, row in df.iterrows():
            try:
                stock_name = str(row.get('INPUT STOCK', row.get('STOCK NAME', f'Row {idx}'))).strip()
                symbol = str(row.get('STOCK SYMBOL', '')).strip()
                short_name = str(row.get('SHORT NAME', symbol)).strip()
                security_id = str(row.get('SECURITY ID', '')).strip()
                
                if '.' in security_id:
                    security_id = security_id.split('.')[0]
                
                if not security_id or security_id == '' or security_id == 'nan':
                    print(f"  ⚠️ [{idx+1}/{len(df)}] {stock_name:25} | Skipping - No SECURITY ID")
                    failed_charts.append({
                        'index': idx,
                        'stock_name': stock_name,
                        'symbol': symbol,
                        'short_name': short_name,
                        'security_id': '',
                        'error': 'No SECURITY ID found in master data'
                    })
                    failed_count += 1
                    continue
                
                exchange = str(row.get('EXCHANGE', 'NSE')).strip().upper()
                exchange_segment = f"{exchange}_EQ" if exchange in ["NSE", "BSE"] else "NSE_EQ"
                chart_type = str(row.get('CHART TYPE', 'Daily')).strip() or 'Daily'
                
                if call_date:
                    date_str = str(call_date).strip()
                else:
                    date_str = str(row.get('DATE', '')).strip()
                
                if call_time:
                    time_str = str(call_time).strip()
                else:
                    time_str = str(row.get('TIME', '15:30:00')).strip()
                
                cmp = row.get('CMP', None)
                if pd.isna(cmp):
                    cmp = None
                else:
                    try:
                        cmp = float(cmp)
                    except (ValueError, TypeError):
                        cmp = None
                
                print(f"  [{idx+1}/{len(df)}] {stock_name[:25]:25} ({chart_type}, {exchange})...")
                
                date_obj = parse_date(date_str)
                h, m, s = parse_time(time_str)
                end_dt_local = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s))
                
                try:
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
                    
                    if df_tf.empty or len(df_tf) == 0:
                        raise ValueError("No data for requested date/time")
                    
                except Exception as primary_error:
                    print(f"      ℹ️ No data for {date_obj}, fetching last trading day...")
                    
                    last_close = get_last_trading_day_close(end_dt_local)
                    last_date = last_close.date()
                    
                    print(f"      ℹ️ Using last trading day: {last_date.strftime('%Y-%m-%d')} 3:30 PM")
                    
                    start_hist = last_date - relativedelta(months=8)
                    end_hist_non_inclusive = last_date + timedelta(days=1)
                    
                    daily = get_daily_history(security_id, start_hist,
                                             end_hist_non_inclusive, headers,
                                             exchange_segment)
                    
                    market_open = IST.localize(datetime(last_date.year, last_date.month, last_date.day, 9, 15, 0))
                    intraday = get_intraday_1m(security_id, market_open,
                                              last_close, headers,
                                              exchange_segment)
                    
                    df_tf = resample_to(daily, chart_type, intraday)
                    
                    if df_tf.empty:
                        raise ValueError("No data available even for last trading day")
                
                df_tf = add_indicators(df_tf)
                
                cmp_datetime = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s))
                
                fname = f"{security_id}_{chart_type}_{date_obj.strftime('%Y%m%d')}_{h:02d}{m:02d}{s:02d}.png"
                save_path = os.path.join(charts_folder, fname)
                
                meta = {
                    "SHORT NAME": short_name or symbol,
                    "CHART TYPE": chart_type,
                    "EXCHANGE": exchange
                }
                
                make_premium_chart(df_tf, meta, save_path, cmp, cmp_datetime)
                
                relative_path = f"charts/{fname}"
                df.at[idx, 'CHART PATH'] = relative_path
                df.at[idx, 'CHART TYPE'] = chart_type
                
                print(f"      ✅ Chart saved: {fname}")
                success_count += 1
                
                time.sleep(1.5)
                
            except Exception as e:
                error_msg = str(e)
                print(f"      ❌ Error: {error_msg}")
                df.at[idx, 'CHART PATH'] = ''
                failed_charts.append({
                    'index': idx,
                    'stock_name': stock_name,
                    'symbol': symbol,
                    'short_name': short_name,
                    'security_id': security_id,
                    'error': error_msg
                })
                failed_count += 1
        
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        if failed_charts:
            with open(failed_charts_file, 'w', encoding='utf-8') as f:
                json.dump(failed_charts, f, indent=2)
            print(f"\n📋 Failed charts info saved to: {failed_charts_file}")
        
        print(f"\n📊 Chart Generation Results:")
        print(f"   ✓ Success: {success_count}")
        print(f"   ✗ Failed: {failed_count}")
        print(f"\n💾 Saved to: {output_file}")
        
        return {
            'success': True,
            'output_file': output_file,
            'success_count': success_count,
            'failed_count': failed_count,
            'failed_charts': failed_charts
        }
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_folder = sys.argv[1]
    else:
        test_folder = "backend/job_files/test_bulk_job"
    
    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
