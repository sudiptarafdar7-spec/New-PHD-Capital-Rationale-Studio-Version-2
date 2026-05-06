"""
Chart Generator Service - Standalone chart generation
Uses Dhan API and chart generation logic from premium rationale
"""
import os
import uuid
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
MARKET_OPEN_TIME = (9, 15)
MARKET_CLOSE_TIME = (15, 30)

CHARTS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'generated_charts')
os.makedirs(CHARTS_FOLDER, exist_ok=True)


class ChartGeneratorService:
    def __init__(self):
        self.dhan_api_key = self._get_dhan_api_key()
    
    def _get_dhan_api_key(self):
        """Get Dhan API key from database"""
        try:
            with get_db_cursor() as cursor:
                cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'dhan'")
                result = cursor.fetchone()
                if result and result['key_value']:
                    return result['key_value']
        except Exception as e:
            print(f"Error getting Dhan API key: {e}")
        return None
    
    def _post(self, path: str, payload: dict, max_retries: int = 4) -> dict:
        """POST with retry on typical transient errors"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": self.dhan_api_key
        }
        
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
    
    def _is_empty_payload(self, d: dict) -> bool:
        """Detect if Dhan returned empty arrays payload"""
        if not isinstance(d, dict) or not d:
            return True
        for key in ("open", "high", "low", "close", "volume", "timestamp"):
            arr = d.get(key, [])
            if isinstance(arr, list) and len(arr) > 0:
                return False
        return True
    
    def _zip_candles(self, d: dict) -> pd.DataFrame:
        """Convert Dhan arrays to DataFrame with IST index"""
        if self._is_empty_payload(d):
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
    
    def _get_daily_history(self, security_id: str, start_date, end_date_non_inclusive,
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
        data = self._post("/charts/historical", payload)
        return self._zip_candles(data)
    
    def _get_intraday_1m(self, security_id: str, from_dt_local: datetime, to_dt_local: datetime,
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
        data = self._post("/charts/intraday", payload)
        return self._zip_candles(data)
    
    def _get_last_trading_day_close(self, dt_local: datetime) -> datetime:
        """Find the last trading day's closing time (3:30 PM)"""
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
    
    def _parse_date(self, s: str) -> datetime.date:
        """Accept YYYY-MM-DD or DD-MM-YYYY or DD/MM/YYYY"""
        s = str(s).strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unrecognized DATE format: {s!r}")
    
    def _parse_time(self, s: str):
        """Accept HH:MM:SS, HH:MM or HH.MM.SS"""
        s = str(s).strip().replace(".", ":")
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.hour, dt.minute, getattr(dt, "second", 0)
            except ValueError:
                continue
        raise ValueError(f"Unrecognized TIME format: {s!r}")
    
    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
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
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MA 20/50/100/200 and RSI(14)"""
        out = df.copy()
        for n in [20, 50, 100, 200]:
            out[f"MA{n}"] = out["close"].rolling(n, min_periods=1).mean()
        out["RSI14"] = self._rsi(out["close"], 14)
        return out
    
    def _aggregate_partial(self, df_1m: pd.DataFrame) -> pd.Series:
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
    
    def _resample_to(self, df_daily: pd.DataFrame, chart_type: str,
                    intraday_partial: pd.DataFrame) -> pd.DataFrame:
        """Resample daily to requested timeframe with partial last candle"""
        if df_daily is None or df_daily.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        chart_type = (chart_type or "").strip().lower()

        if chart_type == "daily":
            df = df_daily.copy()
            part = self._aggregate_partial(intraday_partial)
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
    
    def _pad_right(self, df: pd.DataFrame, n_steps: int = 6) -> pd.DataFrame:
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
    
    def _make_chart(self, df: pd.DataFrame, meta: dict, save_path: str,
                   cmp_value: float = None, cmp_datetime: datetime = None):
        """Generate premium chart with candles, volume, RSI and MAs"""
        if df is None or df.empty or len(df) == 0:
            raise ValueError("No data to plot.")

        df_plot = df[["open", "high", "low", "close", "volume"]].copy()
        df_plot = self._pad_right(df_plot, n_steps=3)
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
    
    def generate_chart(self, security_id: str, symbol: str, short_name: str,
                      exchange: str, chart_type: str, date_str: str, time_str: str) -> dict:
        """
        Generate a stock chart
        
        Returns:
            dict: {
                'success': bool,
                'chart_id': str (unique ID for the chart file),
                'cmp': float,
                'cmp_datetime': str,
                'error': str or None
            }
        """
        try:
            if not self.dhan_api_key:
                return {
                    'success': False,
                    'error': 'Dhan API key not found. Please add it in Settings → API Keys.'
                }
            
            chart_id = f"{symbol}_{chart_type}_{uuid.uuid4().hex[:8]}"
            save_path = os.path.join(CHARTS_FOLDER, f"{chart_id}.png")
            
            if '.' in security_id:
                security_id = security_id.split('.')[0]
            
            exchange_segment = f"{exchange}_EQ" if exchange in ["NSE", "BSE"] else "NSE_EQ"
            
            date_obj = self._parse_date(date_str)
            h, m, s = self._parse_time(time_str)
            end_dt_local = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, h, m, s))
            
            print(f"📊 Generating chart for {symbol} ({chart_type}) at {date_str} {time_str}...")
            
            try:
                start_hist = date_obj - relativedelta(months=8)
                end_hist_non_inclusive = date_obj + timedelta(days=1)
                
                daily = self._get_daily_history(security_id, start_hist,
                                               end_hist_non_inclusive,
                                               exchange_segment)
                
                market_open = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 9, 15, 0))
                if end_dt_local <= market_open:
                    intraday = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                else:
                    intraday = self._get_intraday_1m(security_id, market_open,
                                                    end_dt_local,
                                                    exchange_segment)
                
                df_tf = self._resample_to(daily, chart_type, intraday)
                
                if df_tf.empty or len(df_tf) == 0:
                    raise ValueError("No data for requested date/time")
                
            except Exception as primary_error:
                print(f"  ℹ️ No data for {date_obj} {h:02d}:{m:02d}, fetching last trading day...")
                
                last_close = self._get_last_trading_day_close(end_dt_local)
                last_date = last_close.date()
                
                print(f"  ℹ️ Using last trading day: {last_date.strftime('%Y-%m-%d')} 3:30 PM")
                
                start_hist = last_date - relativedelta(months=8)
                end_hist_non_inclusive = last_date + timedelta(days=1)
                
                daily = self._get_daily_history(security_id, start_hist,
                                               end_hist_non_inclusive,
                                               exchange_segment)
                
                market_open = IST.localize(datetime(last_date.year, last_date.month, last_date.day, 9, 15, 0))
                intraday = self._get_intraday_1m(security_id, market_open,
                                                last_close,
                                                exchange_segment)
                
                df_tf = self._resample_to(daily, chart_type, intraday)
                
                if df_tf.empty:
                    raise ValueError("No data available even for last trading day")
            
            df_tf = self._add_indicators(df_tf)
            
            cmp_value = float(df_tf["close"].iloc[-1])
            cmp_datetime = end_dt_local
            
            meta = {
                "SHORT NAME": short_name,
                "CHART TYPE": chart_type,
                "EXCHANGE": exchange
            }
            
            self._make_chart(df_tf, meta, save_path, cmp_value, cmp_datetime)
            
            print(f"✅ Chart generated: {chart_id}")
            
            return {
                'success': True,
                'chart_id': chart_id,
                'cmp': cmp_value,
                'cmp_datetime': cmp_datetime.isoformat()
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
