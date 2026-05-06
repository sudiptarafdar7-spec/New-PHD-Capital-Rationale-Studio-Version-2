import os
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from backend.utils.database import get_db_cursor


def fetch_last_closing_price(api_key: str, security_id: str, exchange: str, instrument: str, dt: datetime):
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


def fetch_cmp_from_dhan(api_key: str, security_id: str, exchange: str, instrument: str, call_datetime: datetime):
    """
    Fetch CMP from Dhan API for a specific stock at a specific time.
    Falls back to last closing price if outside market hours.
    
    Args:
        api_key: Dhan API access token
        security_id: Security ID from master file
        exchange: Exchange (NSE/BSE)
        instrument: Instrument type (EQUITY)
        call_datetime: Datetime when stock was called
        
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
        from_date = call_datetime.strftime("%Y-%m-%d %H:%M:00")
        to_date = (call_datetime + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:00")
        
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
            closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, call_datetime)
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
            closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, call_datetime)
            if closing_price:
                return (closing_price, "closing")
            else:
                return (None, None)
            
    except RuntimeError:
        raise  # Re-raise authentication errors
    except Exception as e:
        print(f"    ⚠️ API error: {str(e)}")
        # Try fallback to closing price
        closing_price = fetch_last_closing_price(api_key, security_id, exchange, instrument, call_datetime)
        if closing_price:
            return (closing_price, "closing")
        return (None, None)


def fetch_cmp_for_stocks(job_id: str, job_folder: str):
    """
    Fetch CMP for all stocks from input.csv and create stocks_with_cmp.csv
    
    Args:
        job_id: Job ID
        job_folder: Path to job directory
        
    Returns:
        List of stock dictionaries with CMP data
    """
    print("\n" + "=" * 60)
    print("MANUAL RATIONALE STEP 1: FETCH CMP (CURRENT MARKET PRICE)")
    print("=" * 60 + "\n")
    
    try:
        # Input/Output paths
        input_csv = os.path.join(job_folder, 'input.csv')
        output_csv = os.path.join(job_folder, 'analysis', 'stocks_with_cmp.csv')
        
        # Verify input file exists
        if not os.path.exists(input_csv):
            raise ValueError(f'Input CSV file not found: {input_csv}')
        
        # Get Dhan API key
        with get_db_cursor() as cursor:
            cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'dhan'")
            api_key_row = cursor.fetchone()
            dhan_api_key = api_key_row['key_value'] if api_key_row else None
        
        # Verify Dhan API key
        if not dhan_api_key:
            raise ValueError('Dhan API key not found in database. Please add it in API Keys settings.')
        
        print(f"🔑 Dhan API key found")
        
        # Load input CSV
        print(f"📖 Loading stocks from input.csv...")
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
                    stock_name = row.get("LISTED NAME", row.get("STOCK SYMBOL", f"Row {i}"))
                    print(f"  ⚠️ {stock_name:25} | Missing DATE or TIME, skipping")
                    failed_count += 1
                    continue
                
                # Combine date and time
                dt_str = f"{date_str} {time_str}"
                try:
                    # Try YYYY-MM-DD HH:MM:SS format
                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        # Try YYYY-MM-DD HH:MM format
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        # Try parsing just date and use current time
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                
                stock_symbol = row.get("STOCK SYMBOL", "")
                listed_name = row.get("LISTED NAME", "")
                security_id = row.get("SECURITY ID", "")
                exchange = row.get("EXCHANGE", "")
                instrument = row.get("INSTRUMENT", "")
                
                display_name = listed_name if listed_name else stock_symbol
                
                # Skip if missing required data
                if not security_id or pd.isna(security_id) or str(security_id).strip() == "":
                    print(f"  ⚠️ {display_name:25} | Missing Security ID, skipping")
                    failed_count += 1
                    continue
                
                # Fetch CMP from Dhan API (with fallback to closing price)
                result = fetch_cmp_from_dhan(dhan_api_key, security_id, exchange, instrument, dt)
                cmp_value, source = result
                
                if cmp_value is not None:
                    df.at[i, "CMP"] = cmp_value
                    source_label = "💰" if source == "intraday" else "📊"  # intraday vs closing
                    source_text = "" if source == "intraday" else " (Last Close)"
                    print(f"  ✅ {display_name:25} | {source_label} ₹{cmp_value:,.2f}{source_text} @ {dt_str}")
                    success_count += 1
                else:
                    print(f"  ⚠️ {display_name:25} | No data available @ {dt_str}")
                    df.at[i, "CMP"] = None
                    failed_count += 1
                
                # Add delay to avoid API rate limiting (429 errors)
                time.sleep(1.5)
                
            except Exception as e:
                display_name = row.get("LISTED NAME", row.get("STOCK SYMBOL", f"Row {i}"))
                print(f"  ❌ {display_name:25} | Error: {str(e)}")
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
        
        # Convert to list of dicts for return
        stocks_with_cmp = df.to_dict('records')
        
        return stocks_with_cmp
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise e
