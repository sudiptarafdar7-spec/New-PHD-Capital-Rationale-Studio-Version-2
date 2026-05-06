"""
Premium Step 3: Fetch CMP (Current Market Price)

Fetches current market price from Dhan API for each stock at the time
of the call.

Input: 
  - analysis/mapped_master_file.csv (from Step 2)
  - Dhan API key from database
Output: 
  - analysis/stocks_with_cmp.csv
"""

import os
import pandas as pd
import requests
import time
from datetime import datetime, timedelta


def fetch_last_closing_price(api_key, security_id, exchange, instrument, dt):
    """
    Fetch last closing price from Dhan historical API (fallback for outside market hours)
    
    Args:
        api_key: Dhan API access token
        security_id: Security ID from master file
        exchange: Exchange (NSE/BSE)
        instrument: Instrument type (EQUITY)
        dt: Reference datetime
        
    Returns:
        float: Last closing price or None
    """
    url = "https://api.dhan.co/v2/charts/historical"
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "access-token": api_key
    }
    
    try:
        # Exchange segment formatting
        exchange = str(exchange).upper()
        instrument = str(instrument).upper()
        
        if instrument == "EQUITY":
            exchange_segment = f"{exchange}_EQ"
        else:
            exchange_segment = f"{exchange}_EQ"  # Default to EQ
        
        # Remove .0 if security_id is float-like
        security_id_str = str(security_id).split(".")[0]
        
        # Fetch last 7 days to ensure we get closing price
        to_date = dt.strftime("%Y-%m-%d")
        from_date = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
        
        payload = {
            "securityId": security_id_str,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # Check for authentication errors
        if response.status_code == 401:
            raise RuntimeError(
                "❌ Dhan API authentication failed (401 Unauthorized).\n"
                "   Your Dhan API key is invalid or expired.\n"
                "   Please update it in Settings → API Keys → Dhan"
            )
        
        response.raise_for_status()
        data = response.json()
        
        # Extract last available closing price
        if "close" in data and len(data["close"]) > 0:
            # Get the most recent closing price (last element)
            closing_price = data["close"][-1]
            return closing_price
        else:
            return None
            
    except Exception as e:
        print(f"    ⚠️ Historical API error: {str(e)}")
        return None


def fetch_cmp_from_dhan(api_key, security_id, exchange, instrument, dt):
    """
    Fetch CMP from Dhan API for a specific stock at a specific time.
    Falls back to last closing price if outside market hours.
    
    Args:
        api_key: Dhan API access token
        security_id: Security ID from master file
        exchange: Exchange (NSE/BSE)
        instrument: Instrument type (EQUITY)
        dt: Datetime when stock was called
        
    Returns:
        tuple: (price, source) where source is 'intraday' or 'closing'
    """
    url = "https://api.dhan.co/v2/charts/intraday"

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "access-token": api_key
    }

    try:
        # Format datetime range (call time + 10 minutes)
        from_date = dt.strftime("%Y-%m-%d %H:%M:00")
        to_date = (dt + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:00")

        # Exchange segment formatting
        exchange = str(exchange).upper()
        instrument = str(instrument).upper()

        if instrument == "EQUITY":
            exchange_segment = f"{exchange}_EQ"
        else:
            exchange_segment = f"{exchange}_EQ"  # Default to EQ

        # Remove .0 if security_id is float-like
        security_id_str = str(security_id).split(".")[0]

        # API payload
        payload = {
            "securityId": security_id_str,
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "interval": "5",
            "oi": False,
            "fromDate": from_date,
            "toDate": to_date
        }

        # Make API request
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # Check for authentication errors
        if response.status_code == 401:
            raise RuntimeError(
                "❌ Dhan API authentication failed (401 Unauthorized).\n"
                "   Your Dhan API key is invalid or expired.\n"
                "   Please update it in Settings → API Keys → Dhan"
            )
        
        # Log detailed error if request fails
        if response.status_code != 200:
            print(f"    ⚠️ API error ({response.status_code}): {response.text}")
            # Try fallback to closing price
            print(f"    ℹ️ Trying last closing price...")
            closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, dt)
            if closing_price:
                return (closing_price, "closing")
            return (None, None)

        data = response.json()

        # Extract CMP from response
        if "close" in data and len(data["close"]) > 0:
            cmp_value = data["close"][0]
            return (cmp_value, "intraday")
        else:
            # No intraday data - try fetching last closing price
            print(f"    ℹ️ No intraday data (market closed), fetching last closing price...")
            closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, dt)
            if closing_price:
                return (closing_price, "closing")
            else:
                return (None, None)

    except RuntimeError:
        raise  # Re-raise authentication errors
    except Exception as e:
        print(f"    ⚠️ API error: {str(e)}")
        # Try fallback to closing price
        closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, dt)
        if closing_price:
            return (closing_price, "closing")
        return (None, None)


def run(job_folder, dhan_api_key):
    """
    Fetch CMP for all stocks from Dhan API
    
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
    print("PREMIUM STEP 3: FETCH CMP (CURRENT MARKET PRICE)")
    print(f"{'='*60}\n")

    try:
        # Input/Output paths
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_csv = os.path.join(analysis_folder, 'mapped_master_file.csv')
        output_csv = os.path.join(analysis_folder, 'stocks_with_cmp.csv')

        # Verify input file exists
        if not os.path.exists(input_csv):
            return {
                'success': False,
                'error': f'Mapped stocks file not found: {input_csv}'
            }

        # Verify Dhan API key
        if not dhan_api_key:
            return {
                'success': False,
                'error': 'Dhan API key not found in database. Please add it in API Keys settings.'
            }

        print(f"🔑 Dhan API key found")

        # Load stocks file
        print("📖 Loading mapped stocks...")
        df = pd.read_csv(input_csv)
        print(f"✅ Loaded {len(df)} stocks\n")

        # Ensure CMP column exists
        if "CMP" not in df.columns:
            df["CMP"] = None

        # Fetch CMP for each stock
        print("💹 Fetching Current Market Prices from Dhan API...")
        print("-" * 60)

        success_count = 0
        failed_count = 0

        for i, row in df.iterrows():
            try:
                # Parse datetime from DATE and TIME columns
                date_str = str(row.get('DATE', '')).strip()
                time_str = str(row.get('TIME', '')).strip()
                
                if not date_str or not time_str:
                    stock_name = row.get("STOCK NAME", f"Row {i}")
                    print(f"  ⚠️ {stock_name:25} | Missing DATE or TIME, skipping")
                    failed_count += 1
                    continue

                # Combine date and time
                dt_str = f"{date_str} {time_str}"
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Try alternative format
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

                stock_name = row.get("STOCK NAME", "")
                stock_symbol = row.get("STOCK SYMBOL", "")
                security_id = row.get("SECURITY ID", "")
                exchange = row.get("EXCHANGE", "")
                instrument = row.get("INSTRUMENT", "")

                # Skip if missing required data
                if not security_id or pd.isna(security_id) or str(security_id).strip() == "":
                    print(f"  ⚠️ {stock_name:25} | Missing Security ID, skipping")
                    failed_count += 1
                    continue

                # Fetch CMP from Dhan API (with fallback to closing price)
                result = fetch_cmp_from_dhan(dhan_api_key, security_id, exchange, instrument, dt)
                cmp_value, source = result

                if cmp_value is not None:
                    df.at[i, "CMP"] = cmp_value
                    source_label = "💰" if source == "intraday" else "📊"  # intraday vs closing
                    source_text = "" if source == "intraday" else " (Last Close)"
                    print(f"  ✅ {stock_name:25} | {source_label} ₹{cmp_value:,.2f}{source_text} @ {dt_str}")
                    success_count += 1
                else:
                    print(f"  ⚠️ {stock_name:25} | No data available @ {dt_str}")
                    failed_count += 1

                # Add delay to avoid API rate limiting (429 errors)
                time.sleep(1.5)

            except Exception as e:
                stock_name = row.get("STOCK NAME", f"Row {i}")
                print(f"  ❌ {stock_name:25} | Error: {str(e)}")
                failed_count += 1

        print("-" * 60)
        print(f"\n📊 CMP Fetch Summary:")
        print(f"   Total stocks: {len(df)}")
        print(f"   Successfully fetched: {success_count}")
        print(f"   Failed/No data: {failed_count}\n")

        # Save output
        print(f"💾 Saving CMP data to: {output_csv}")

        # Ensure analysis directory exists
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)

        df.to_csv(output_csv, index=False)

        print(f"✅ Saved {len(df)} records")
        print(f"✅ Output: analysis/stocks_with_cmp.csv\n")

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
