import os
import csv
import json
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from backend.utils.path_utils import resolve_uploaded_file_path

def get_master_csv_path() -> Optional[str]:
    """Fetch master file path from database and resolve to current system path"""
    from backend.utils.database import get_db_cursor
    
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT file_path FROM uploaded_files WHERE file_type = 'masterFile' ORDER BY uploaded_at DESC LIMIT 1"
        )
        result = cursor.fetchone()
        if result:
            db_path = result['file_path']
            resolved_path = resolve_uploaded_file_path(db_path)
            print(f"📂 Master file path from DB: {db_path}")
            print(f"📂 Resolved to: {resolved_path}")
            return resolved_path
    return None

def enrich_stocks_with_master_data(stocks: List[Dict]) -> List[Dict]:
    master_csv_path = get_master_csv_path()
    
    if not master_csv_path or not os.path.exists(master_csv_path):
        raise ValueError("Master CSV file not found. Please upload master file in Settings.")
    
    try:
        df = pd.read_csv(master_csv_path)
        
        df_equity = df[
            (df['SEM_INSTRUMENT_NAME'] == 'EQUITY') & 
            (df['SEM_EXCH_INSTRUMENT_TYPE'] == 'ES')
        ].copy()
        
        enriched_stocks = []
        for stock in stocks:
            symbol = stock['symbol'].upper()
            
            matching_row = df_equity[
                df_equity['SEM_TRADING_SYMBOL'].str.upper() == symbol
            ]
            
            if matching_row.empty:
                raise ValueError(f"Stock symbol '{symbol}' not found in master CSV")
            
            row = matching_row.iloc[0]
            
            enriched_stock = {
                'symbol': stock['symbol'],
                'security_id': str(row['SEM_SMST_SECURITY_ID']) if pd.notna(row['SEM_SMST_SECURITY_ID']) else '',
                'listed_name': str(row['SM_SYMBOL_NAME']) if pd.notna(row['SM_SYMBOL_NAME']) else '',
                'short_name': str(row['SEM_CUSTOM_SYMBOL']) if pd.notna(row['SEM_CUSTOM_SYMBOL']) else '',
                'exchange': str(row['SEM_EXM_EXCH_ID']) if pd.notna(row['SEM_EXM_EXCH_ID']) else '',
                'instrument': str(row['SEM_INSTRUMENT_NAME']) if pd.notna(row['SEM_INSTRUMENT_NAME']) else '',
                'chart_type': stock.get('chart_type', 'Daily'),
                'analysis': stock.get('analysis', ''),
                'call': stock.get('call', ''),
                'entry': stock.get('entry', ''),
                'target': stock.get('target', ''),
                'stop_loss': stock.get('stop_loss', ''),
                'cmp': stock.get('cmp', ''),
                'change_percent': stock.get('change_percent', ''),
                'chart_path': stock.get('chart_path', '')
            }
            enriched_stocks.append(enriched_stock)
        
        return enriched_stocks
        
    except Exception as e:
        raise ValueError(f"Error enriching stocks with master data: {str(e)}")

def get_stock_autocomplete(query: str, limit: int = 10) -> List[Dict]:
    master_csv_path = get_master_csv_path()
    
    if not master_csv_path or not os.path.exists(master_csv_path):
        return []
    
    try:
        df = pd.read_csv(master_csv_path)
        
        df_equity = df[
            (df['SEM_INSTRUMENT_NAME'] == 'EQUITY') & 
            (df['SEM_EXCH_INSTRUMENT_TYPE'] == 'ES')
        ].copy()
        
        query_upper = query.upper()
        
        matches = df_equity[
            df_equity['SEM_TRADING_SYMBOL'].str.upper().str.contains(query_upper, na=False)
        ].head(limit)
        
        results = []
        for _, row in matches.iterrows():
            results.append({
                'symbol': str(row['SEM_TRADING_SYMBOL']) if pd.notna(row['SEM_TRADING_SYMBOL']) else '',
                'name': str(row['SM_SYMBOL_NAME']) if pd.notna(row['SM_SYMBOL_NAME']) else '',
                'securityId': str(row['SEM_SMST_SECURITY_ID']) if pd.notna(row['SEM_SMST_SECURITY_ID']) else '',
                'listedName': str(row['SM_SYMBOL_NAME']) if pd.notna(row['SM_SYMBOL_NAME']) else '',
                'shortName': str(row['SEM_CUSTOM_SYMBOL']) if pd.notna(row['SEM_CUSTOM_SYMBOL']) else '',
                'exchange': str(row['SEM_EXM_EXCH_ID']) if pd.notna(row['SEM_EXM_EXCH_ID']) else '',
                'instrument': str(row['SEM_INSTRUMENT_NAME']) if pd.notna(row['SEM_INSTRUMENT_NAME']) else ''
            })
        
        return results
        
    except Exception as e:
        print(f"Error in autocomplete: {str(e)}")
        return []

def create_input_csv(job_id: str, folder_path: str) -> str:
    """
    Create input.csv file with all stock data and master data enrichment.
    
    Columns: DATE, TIME, STOCK SYMBOL, CHART TYPE, LISTED NAME, SHORT NAME, 
             SECURITY ID, EXCHANGE, INSTRUMENT, ANALYSIS
    
    Returns the path to the created CSV file.
    """
    from backend.utils.database import get_db_cursor
    
    # Fetch job data
    with get_db_cursor() as cursor:
        cursor.execute("""
            SELECT date, payload FROM jobs WHERE id = %s
        """, (job_id,))
        job = cursor.fetchone()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
    
    # Parse payload
    payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
    stocks = payload.get('stocks', [])
    call_time = payload.get('call_time', '')
    job_date = payload.get('date', job['date'])
    
    # Create CSV file
    csv_path = os.path.join(folder_path, 'input.csv')
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'DATE', 'TIME', 'STOCK SYMBOL', 'CHART TYPE', 'LISTED NAME', 
            'SHORT NAME', 'SECURITY ID', 'EXCHANGE', 'INSTRUMENT', 'ANALYSIS'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for stock in stocks:
            # Use chart type directly from user input (Daily/Weekly/Monthly)
            chart_type = stock.get('chart_type', 'Daily')
            
            # Use analysis text directly from user input
            analysis_text = stock.get('analysis', '')
            
            writer.writerow({
                'DATE': job_date,
                'TIME': call_time,
                'STOCK SYMBOL': stock.get('symbol', ''),
                'CHART TYPE': chart_type,
                'LISTED NAME': stock.get('listed_name', ''),
                'SHORT NAME': stock.get('short_name', ''),
                'SECURITY ID': stock.get('security_id', ''),
                'EXCHANGE': stock.get('exchange', ''),
                'INSTRUMENT': stock.get('instrument', ''),
                'ANALYSIS': analysis_text
            })
    
    print(f"✓ Created input.csv at {csv_path}")
    return csv_path
