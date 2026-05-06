"""
Premium Step 5: Fetch Technical Indicators

Extracts key technical indicators (RSI, MA20, MA50, MA100, MA200)
from historical data using the same source as chart generation (Dhan API).

Input: 
  - analysis/stocks_with_chart.csv (from Step 4)
  - Dhan API key from database
Output: 
  - analysis/stocks_with_technical.csv
"""

import os
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta


def calculate_rsi(prices, period=14):
    """Calculate RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return None
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


def calculate_sma(prices, period):
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return None
    return round(np.mean(prices[-period:]), 2)


def fetch_historical_data_dhan(api_key, security_id, exchange, instrument, months=11):
    """
    Fetch historical daily data from Dhan API (same as Step 4)
    
    Args:
        api_key: Dhan API access token
        security_id: Security ID from master file
        exchange: Exchange (NSE/BSE)
        instrument: Instrument type (EQUITY)
        months: Number of months of historical data (default 11 for MA200 calculation)
        
    Returns:
        list: List of close prices (oldest to newest)
    """
    url = "https://api.dhan.co/v2/charts/historical"
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "access-token": api_key
    }
    
    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=months * 30)
        
        exchange = str(exchange).upper()
        if instrument == "EQUITY":
            exchange_segment = f"{exchange}_EQ"
        else:
            exchange_segment = f"{exchange}_EQ"
        
        security_id_str = str(security_id).split(".")[0]
        
        payload = {
            "securityId": security_id_str,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "fromDate": from_date.strftime("%Y-%m-%d"),
            "toDate": to_date.strftime("%Y-%m-%d")
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if response.status_code != 200:
            print(f"    ⚠️ API error ({response.status_code}): {response.text}")
            return None
        
        data = response.json()
        
        if "close" in data and len(data["close"]) > 0:
            return data["close"]
        else:
            return None
            
    except Exception as e:
        print(f"    ⚠️ API error: {str(e)}")
        return None


def compute_indicators(close_prices):
    """
    Compute technical indicators from close prices
    
    Args:
        close_prices: List of close prices (oldest to newest)
        
    Returns:
        dict: {'RSI': float, 'MA20': float, 'MA50': float, 'MA100': float, 'MA200': float}
    """
    if not close_prices or len(close_prices) == 0:
        return {
            'RSI': None,
            'MA20': None,
            'MA50': None,
            'MA100': None,
            'MA200': None
        }
    
    prices = np.array(close_prices, dtype=float)
    
    return {
        'RSI': calculate_rsi(prices, period=14),
        'MA20': calculate_sma(prices, 20),
        'MA50': calculate_sma(prices, 50),
        'MA100': calculate_sma(prices, 100),
        'MA200': calculate_sma(prices, 200)
    }


def run(job_folder, dhan_api_key):
    """
    Fetch technical indicators for all stocks
    
    Args:
        job_folder: Path to job directory
        dhan_api_key: Dhan API access token
        
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("PREMIUM STEP 5: FETCH TECHNICAL INDICATORS")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_csv = os.path.join(analysis_folder, 'stocks_with_chart.csv')
        output_csv = os.path.join(analysis_folder, 'stocks_with_technical.csv')
        
        if not os.path.exists(input_csv):
            return {
                'success': False,
                'error': f'Stocks with chart file not found: {input_csv}'
            }
        
        if not dhan_api_key:
            return {
                'success': False,
                'error': 'Dhan API key not found in database. Please add it in API Keys settings.'
            }
        
        print(f"🔑 Dhan API key found")
        
        print("📖 Loading stocks with charts...")
        df = pd.read_csv(input_csv)
        print(f"✅ Loaded {len(df)} stocks\n")
        
        for col in ['RSI', 'MA20', 'MA50', 'MA100', 'MA200']:
            if col not in df.columns:
                df[col] = None
        
        print("📈 Fetching Technical Indicators from Dhan API...")
        print("-" * 60)
        
        success_count = 0
        failed_count = 0
        
        for i, row in df.iterrows():
            try:
                stock_name = row.get("STOCK NAME", "")
                security_id = row.get("SECURITY ID", "")
                exchange = row.get("EXCHANGE", "NSE")
                instrument = row.get("INSTRUMENT", "EQUITY")
                
                if not security_id or pd.isna(security_id) or str(security_id).strip() == "":
                    print(f"  ⚠️ {stock_name:25} | Missing Security ID, skipping")
                    failed_count += 1
                    continue
                
                print(f"  [{i+1}/{len(df)}] {stock_name:25} | Fetching historical data...")
                
                close_prices = fetch_historical_data_dhan(
                    dhan_api_key, 
                    security_id, 
                    exchange, 
                    instrument,
                    months=11
                )
                
                if close_prices is None or len(close_prices) == 0:
                    print(f"       ⚠️ No historical data available")
                    failed_count += 1
                    continue
                
                indicators = compute_indicators(close_prices)
                
                df.at[i, "RSI"] = indicators['RSI']
                df.at[i, "MA20"] = indicators['MA20']
                df.at[i, "MA50"] = indicators['MA50']
                df.at[i, "MA100"] = indicators['MA100']
                df.at[i, "MA200"] = indicators['MA200']
                
                rsi_str = f"{indicators['RSI']:.2f}" if indicators['RSI'] is not None else "N/A"
                ma20_str = f"{indicators['MA20']:.2f}" if indicators['MA20'] is not None else "N/A"
                ma50_str = f"{indicators['MA50']:.2f}" if indicators['MA50'] is not None else "N/A"
                
                print(f"       ✅ RSI: {rsi_str:>6} | MA20: {ma20_str:>8} | MA50: {ma50_str:>8}")
                
                success_count += 1
                
                time.sleep(1.5)
                
            except Exception as e:
                stock_name = row.get("STOCK NAME", f"Row {i}")
                print(f"  ❌ {stock_name:25} | Error: {str(e)}")
                failed_count += 1
        
        print("-" * 60)
        print(f"\n📊 Technical Indicators Summary:")
        print(f"   Total stocks: {len(df)}")
        print(f"   Successfully fetched: {success_count}")
        print(f"   Failed/No data: {failed_count}\n")
        
        print(f"💾 Saving technical indicators to: {output_csv}")
        
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        
        df.to_csv(output_csv, index=False)
        
        print(f"✅ Saved {len(df)} records with technical indicators")
        print(f"✅ Output: analysis/stocks_with_technical.csv\n")
        
        return {
            'success': True,
            'output_file': output_csv,
            'error': None
        }
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
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
        test_folder = "backend/job_files/test_premium_job"
    
    result = run(test_folder, None)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
