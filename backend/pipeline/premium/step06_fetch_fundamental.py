"""
Premium Step 6: Fetch Fundamental Data

Fetches comprehensive fundamental data from Yahoo Finance including:
Market Cap, P/E, P/B, ROE, ROCE, Debt/Equity, EPS, Growth metrics, etc.

Input: 
  - analysis/stocks_with_technical.csv (from Step 5)
Output: 
  - analysis/stocks_with_fundamental.csv
"""

import os
import pandas as pd
import yfinance as yf
import time


def get_yfinance_symbol(stock_symbol, exchange):
    """
    Convert stock symbol to Yahoo Finance format
    
    Args:
        stock_symbol: Stock symbol (e.g., "RELIANCE")
        exchange: Exchange (NSE/BSE)
        
    Returns:
        str: Yahoo Finance symbol (e.g., "RELIANCE.NS" for NSE)
    """
    exchange = str(exchange).strip().upper()
    
    if exchange == "NSE":
        return f"{stock_symbol}.NS"
    elif exchange == "BSE":
        return f"{stock_symbol}.BO"
    else:
        return f"{stock_symbol}.NS"


def safe_get(info, key, multiplier=1):
    """Safely extract value from Yahoo Finance info dict"""
    value = info.get(key)
    if value is not None and value != "":
        try:
            if multiplier != 1:
                return round(float(value) * multiplier, 2)
            return value
        except (ValueError, TypeError):
            return None
    return None


def fetch_fundamental_data(yf_symbol):
    """
    Fetch fundamental data for a single stock from Yahoo Finance
    
    Args:
        yf_symbol: Yahoo Finance symbol (e.g., "RELIANCE.NS")
        
    Returns:
        dict: Fundamental data or None if error
    """
    try:
        stock = yf.Ticker(yf_symbol)
        info = stock.info
        
        if not info or len(info) == 0:
            return None
        
        data = {
            'COMPANY NAME': safe_get(info, 'longName'),
            'MARKET CAP': safe_get(info, 'marketCap'),
            'P/E RATIO': safe_get(info, 'trailingPE'),
            'P/B RATIO': safe_get(info, 'priceToBook'),
            'ROE (%)': safe_get(info, 'returnOnEquity', multiplier=100),
            'ROCE (%)': safe_get(info, 'returnOnAssets', multiplier=100),
            'DEBT/EQUITY': safe_get(info, 'debtToEquity'),
            'EPS (TTM)': safe_get(info, 'trailingEps'),
            'EPS GROWTH (YoY %)': safe_get(info, 'earningsGrowth', multiplier=100),
            'REVENUE GROWTH (YoY %)': safe_get(info, 'revenueGrowth', multiplier=100),
            'DIVIDEND YIELD (%)': safe_get(info, 'dividendYield', multiplier=100),
            'SECTOR': safe_get(info, 'sector'),
            'INDUSTRY': safe_get(info, 'industry')
        }
        
        return data
        
    except Exception as e:
        print(f"       ⚠️ Error fetching data: {str(e)}")
        return None


def run(job_folder):
    """
    Fetch fundamental data for all stocks from Yahoo Finance
    
    Args:
        job_folder: Path to job directory
    
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("PREMIUM STEP 6: FETCH FUNDAMENTAL DATA")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_csv = os.path.join(analysis_folder, 'stocks_with_technical.csv')
        output_csv = os.path.join(analysis_folder, 'stocks_with_fundamental.csv')
        
        if not os.path.exists(input_csv):
            return {
                'success': False,
                'error': f'Stocks with technical data file not found: {input_csv}'
            }
        
        print("📖 Loading stocks with technical data...")
        df = pd.read_csv(input_csv)
        print(f"✅ Loaded {len(df)} stocks\n")
        
        # Add fundamental columns if they don't exist
        fundamental_cols = [
            'COMPANY NAME', 'MARKET CAP', 'P/E RATIO', 'P/B RATIO',
            'ROE (%)', 'ROCE (%)', 'DEBT/EQUITY', 'EPS (TTM)',
            'EPS GROWTH (YoY %)', 'REVENUE GROWTH (YoY %)',
            'DIVIDEND YIELD (%)', 'SECTOR', 'INDUSTRY'
        ]
        
        for col in fundamental_cols:
            if col not in df.columns:
                df[col] = None
        
        print("💼 Fetching Fundamental Data from Yahoo Finance...")
        print("-" * 60)
        
        success_count = 0
        failed_count = 0
        
        for i, row in df.iterrows():
            try:
                stock_symbol = row.get("STOCK SYMBOL", "")
                stock_name = row.get("STOCK NAME", "")
                exchange = row.get("EXCHANGE", "NSE")
                
                if not stock_symbol or pd.isna(stock_symbol) or str(stock_symbol).strip() == "":
                    print(f"  ⚠️ {stock_name:25} | Missing stock symbol, skipping")
                    failed_count += 1
                    continue
                
                yf_symbol = get_yfinance_symbol(stock_symbol, exchange)
                print(f"  [{i+1}/{len(df)}] {stock_name:25} | Fetching {yf_symbol}...")
                
                fundamental_data = fetch_fundamental_data(yf_symbol)
                
                if fundamental_data:
                    for key, value in fundamental_data.items():
                        df.at[i, key] = value
                    
                    pe_ratio = fundamental_data.get('P/E RATIO', 'N/A')
                    roe = fundamental_data.get('ROE (%)', 'N/A')
                    
                    pe_str = f"{pe_ratio:.2f}" if isinstance(pe_ratio, (int, float)) else "N/A"
                    roe_str = f"{roe:.2f}%" if isinstance(roe, (int, float)) else "N/A"
                    
                    print(f"       ✅ P/E: {pe_str:>8} | ROE: {roe_str:>8}")
                    success_count += 1
                else:
                    print(f"       ⚠️ No fundamental data available")
                    failed_count += 1
                
                time.sleep(0.5)
                
            except Exception as e:
                stock_name = row.get("STOCK NAME", f"Row {i}")
                print(f"  ❌ {stock_name:25} | Error: {str(e)}")
                failed_count += 1
        
        print("-" * 60)
        print(f"\n📊 Fundamental Data Summary:")
        print(f"   Total stocks: {len(df)}")
        print(f"   Successfully fetched: {success_count}")
        print(f"   Failed/No data: {failed_count}\n")
        
        print(f"💾 Saving fundamental data to: {output_csv}")
        
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        
        df.to_csv(output_csv, index=False)
        
        print(f"✅ Saved {len(df)} records with fundamental data")
        print(f"✅ Output: analysis/stocks_with_fundamental.csv\n")
        
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
    
    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
