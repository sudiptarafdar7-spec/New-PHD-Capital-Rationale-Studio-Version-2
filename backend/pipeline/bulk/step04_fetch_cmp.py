"""
Bulk Rationale Step 4: Fetch CMP
Fetches Current Market Price using Dhan API
"""

import os
import re
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from backend.utils.database import get_db_cursor


def normalize_date_format(date_str):
    """
    Normalize date to YYYY-MM-DD format.
    Handles ALL possible input formats from Windows/Excel:
    
    Standard formats:
    - YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    - MM/DD/YYYY, MM-DD-YYYY
    
    Two-digit year formats:
    - DD/MM/YY, DD-MM-YY, MM/DD/YY
    - D/M/YY, M/D/YY (single digit day/month)
    
    Month name formats:
    - 31-Dec-2025, 31 Dec 2025, Dec 31, 2025
    - 31-Dec-25, 31 Dec 25
    - December 31, 2025
    
    Excel serial numbers:
    - 45123 (days since 1899-12-30)
    
    Returns date in YYYY-MM-DD format or None if parsing fails.
    """
    if not date_str or pd.isna(date_str):
        return None
    
    date_str = str(date_str).strip()
    
    if not date_str or date_str.lower() in ['nan', 'none', 'nat', '']:
        return None
    
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
    
    try:
        num_val = float(date_str)
        if 40000 < num_val < 60000:
            excel_epoch = datetime(1899, 12, 30)
            dt = excel_epoch + timedelta(days=int(num_val))
            return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        pass
    
    date_formats = [
        '%d/%m/%Y',
        '%d-%m-%Y',
        '%d.%m.%Y',
        '%Y/%m/%d',
        '%Y.%m.%d',
        '%m/%d/%Y',
        '%m-%d-%Y',
        
        '%d/%m/%y',
        '%d-%m-%y',
        '%d.%m.%y',
        '%m/%d/%y',
        '%m-%d-%y',
        '%y/%m/%d',
        '%y-%m-%d',
        
        '%d-%b-%Y',
        '%d %b %Y',
        '%d-%b-%y',
        '%d %b %y',
        '%b %d, %Y',
        '%b %d %Y',
        '%B %d, %Y',
        '%B %d %Y',
        '%d %B %Y',
        '%d-%B-%Y',
        
        '%Y-%m-%d %H:%M:%S',
        '%d/%m/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M:%S',
        '%d-%m-%Y %H:%M:%S',
    ]
    
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    
    try:
        dt = pd.to_datetime(date_str, dayfirst=True)
        if not pd.isna(dt):
            return dt.strftime('%Y-%m-%d')
    except:
        pass
    
    try:
        dt = pd.to_datetime(date_str, dayfirst=False)
        if not pd.isna(dt):
            return dt.strftime('%Y-%m-%d')
    except:
        pass
    
    return None


def normalize_time_format(time_str):
    """
    Normalize time to HH:MM:SS format (24-hour).
    Handles ALL possible input formats from Windows/Excel:
    
    Standard formats:
    - HH:MM:SS, H:MM:SS (21:09:00, 9:30:00)
    - HH:MM, H:MM (21:09, 9:30)
    
    Period/dash separators (Excel corruption):
    - HH.MM.SS, H.MM.SS (21.09.00)
    - HH-MM-SS, H-MM-SS (21-09-00)
    - HH.MM, H.MM (21.09)
    
    AM/PM formats (with/without space):
    - 9:30:00 AM, 9:30 AM, 9:30AM, 9.30AM
    - 9 AM, 9AM (hour only)
    
    Numeric formats (no separators):
    - HHMMSS (093000, 210900)
    - HHMM (0930, 2109)
    - HMM (930)
    
    Excel fractional time:
    - 0.3958 (fraction of day = 09:30:00)
    
    Returns time in HH:MM:SS format or default '10:00:00' if parsing fails.
    """
    if not time_str or pd.isna(time_str):
        return '10:00:00'
    
    time_str = str(time_str).strip()
    
    if not time_str or time_str.lower() in ['nan', 'none', 'nat', '']:
        return '10:00:00'
    
    try:
        num_val = float(time_str)
        if 0 <= num_val < 1:
            total_seconds = int(num_val * 24 * 60 * 60)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        pass
    
    match = re.match(r'^(\d{1,2}):(\d{2}):(\d{2})$', time_str)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
            return f"{h:02d}:{m:02d}:{s:02d}"
    
    match = re.match(r'^(\d{1,2})[.\-](\d{2})[.\-](\d{2})$', time_str)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
            return f"{h:02d}:{m:02d}:{s:02d}"
    
    match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}:00"
    
    match = re.match(r'^(\d{1,2})[.\-](\d{2})$', time_str)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}:00"
    
    match = re.match(r'^(\d{1,2})[:.\-]?(\d{2})[:.\-]?(\d{2})?\s*(AM|PM|am|pm|A\.M\.|P\.M\.)$', time_str, re.IGNORECASE)
    if match:
        h = int(match.group(1))
        m = int(match.group(2)) if match.group(2) else 0
        s = int(match.group(3)) if match.group(3) else 0
        period = match.group(4).upper().replace('.', '')
        
        if period == 'PM' and h != 12:
            h += 12
        elif period == 'AM' and h == 12:
            h = 0
        
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
            return f"{h:02d}:{m:02d}:{s:02d}"
    
    match = re.match(r'^(\d{1,2})\s*(AM|PM|am|pm|A\.M\.|P\.M\.)$', time_str, re.IGNORECASE)
    if match:
        h = int(match.group(1))
        period = match.group(2).upper().replace('.', '')
        
        if period == 'PM' and h != 12:
            h += 12
        elif period == 'AM' and h == 12:
            h = 0
        
        if 0 <= h <= 23:
            return f"{h:02d}:00:00"
    
    if re.match(r'^\d{5,6}$', time_str):
        time_str = time_str.zfill(6)
        h, m, s = int(time_str[0:2]), int(time_str[2:4]), int(time_str[4:6])
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59:
            return f"{h:02d}:{m:02d}:{s:02d}"
    
    if re.match(r'^\d{3,4}$', time_str):
        time_str = time_str.zfill(4)
        h, m = int(time_str[0:2]), int(time_str[2:4])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}:00"
    
    time_formats = [
        '%I:%M:%S %p',
        '%I:%M %p',
        '%I %p',
        '%I:%M:%S%p',
        '%I:%M%p',
        '%I%p',
        '%H:%M:%S',
        '%H:%M',
    ]
    
    for fmt in time_formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime('%H:%M:%S')
        except ValueError:
            continue
    
    return '10:00:00'


def get_dhan_api_key():
    """Get Dhan API key from database"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'dhan'")
        result = cursor.fetchone()
        if result and result['key_value']:
            return result['key_value'].strip()
    return None


def fetch_cmp_for_stock(security_id, exchange, date_str, time_str, headers):
    """
    Fetch CMP for a single stock using Dhan intraday API
    """
    try:
        exchange_segment = f"{exchange}_EQ"
        
        dt_str = f"{date_str} {time_str}"
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        
        from_time = dt.replace(hour=9, minute=15, second=0)
        to_time = dt + timedelta(minutes=10)
        
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "interval": "5",
            "fromDate": from_time.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": to_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        response = requests.post(
            "https://api.dhan.co/v2/charts/intraday",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('close') and len(data['close']) > 0:
                return data['close'][-1]
        
        historical_payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": "EQUITY",
            "expiryCode": 0,
            "fromDate": (dt - timedelta(days=5)).strftime("%Y-%m-%d"),
            "toDate": dt.strftime("%Y-%m-%d")
        }
        
        response = requests.post(
            "https://api.dhan.co/v2/charts/historical",
            headers=headers,
            json=historical_payload,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('close') and len(data['close']) > 0:
                return data['close'][-1]
        
        return None
        
    except Exception as e:
        print(f"      Error fetching CMP: {str(e)}")
        return None


def run(job_folder):
    """
    Fetch CMP for all stocks from Dhan API
    
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
    print("BULK STEP 4: FETCH CMP (CURRENT MARKET PRICE)")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_file = os.path.join(analysis_folder, 'mapped_master_file.csv')
        output_file = os.path.join(analysis_folder, 'stocks_with_cmp.csv')
        
        if not os.path.exists(input_file):
            return {
                'success': False,
                'error': f'Mapped file not found: {input_file}'
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
        
        print(f"📖 Loading mapped stocks: {input_file}")
        df = pd.read_csv(input_file)
        print(f"✅ Loaded {len(df)} stocks")
        
        if 'CMP' not in df.columns:
            df['CMP'] = None
        
        print("\n💹 Fetching Current Market Prices...")
        print("-" * 60)
        
        success_count = 0
        failed_count = 0
        
        for i, row in df.iterrows():
            stock_name = row.get('INPUT STOCK', row.get('STOCK NAME', f'Row {i}'))
            security_id = str(row.get('SECURITY ID', '')).strip()
            
            if '.' in security_id:
                security_id = security_id.split('.')[0]
            
            if not security_id or security_id == '' or security_id == 'nan':
                print(f"  ⚠️ {stock_name:30} | Missing SECURITY ID, skipping")
                failed_count += 1
                continue
            
            exchange = str(row.get('EXCHANGE', 'NSE')).strip()
            raw_date = str(row.get('DATE', '')).strip()
            raw_time = str(row.get('TIME', '10:00:00')).strip()
            
            # Normalize date format to YYYY-MM-DD
            date_str = normalize_date_format(raw_date)
            if not date_str:
                print(f"  ⚠️ {stock_name:30} | Invalid date format: {raw_date}, skipping")
                failed_count += 1
                continue
            
            # Normalize time format to HH:MM:SS (handles Excel's period format)
            time_str = normalize_time_format(raw_time)
            
            # Update the dataframe with normalized date and time
            df.at[i, 'DATE'] = date_str
            df.at[i, 'TIME'] = time_str
            
            # Log if date or time was converted
            if raw_date != date_str or raw_time != time_str:
                print(f"  📅 Normalized: {raw_date} {raw_time} → {date_str} {time_str}")
            
            cmp = fetch_cmp_for_stock(security_id, exchange, date_str, time_str, headers)
            
            if cmp:
                df.at[i, 'CMP'] = round(cmp, 2)
                success_count += 1
                print(f"  ✓ {stock_name:30} | CMP: ₹{cmp:.2f}")
            else:
                failed_count += 1
                print(f"  ✗ {stock_name:30} | Failed to fetch CMP")
            
            time.sleep(0.5)
        
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        print(f"\n📊 CMP Fetch Results:")
        print(f"   ✓ Success: {success_count}")
        print(f"   ✗ Failed: {failed_count}")
        print(f"\n💾 Saved to: {output_file}")
        
        return {
            'success': True,
            'output_file': output_file,
            'success_count': success_count,
            'failed_count': failed_count
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
