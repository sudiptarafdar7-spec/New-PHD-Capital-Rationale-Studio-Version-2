"""
Step 9: Map Master File

Maps extracted stocks from Step 8 to the master reference file to get:
- Securities ID
- Exchange (NSE/BSE)
- Listed Name
- Short Name
- Instrument type
- Segment

Uses exact and fuzzy matching with multiple fallback strategies.

Input: 
  - analysis/extracted_stocks.csv (from Step 8)
  - Master CSV file from uploaded_files
Output: 
  - analysis/mapped_master_file.csv
"""

import os
import re
import pandas as pd
import psycopg2
from rapidfuzz import fuzz, process
from backend.utils.path_utils import resolve_uploaded_file_path


def normalize_text(s):
    """Clean text for matching (remove special chars, multiple spaces)."""
    if not isinstance(s, str):
        s = str(s)
    s = re.sub(r"[^A-Z0-9]", "", s.upper())  # Keep only alphanumerics
    return s.strip()


def fuzzy_match(value, target_series, threshold=80):
    """Return best fuzzy match index or None."""
    if not value or not isinstance(value, str):
        return None
    value_norm = normalize_text(value)
    choices = target_series.tolist()
    result = process.extractOne(value_norm, choices, scorer=fuzz.token_sort_ratio)
    if result and result[1] >= threshold:
        matched_value = result[0]
        idx_list = target_series[target_series == matched_value].index
        if len(idx_list) > 0:
            return idx_list[0]
    return None


def get_master_file_path():
    """Fetch master file path from database and resolve to current system path"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT file_path 
            FROM uploaded_files 
            WHERE file_type = 'masterFile'
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            db_path = result[0]
            resolved_path = resolve_uploaded_file_path(db_path)
            print(f"📂 Master file path from DB: {db_path}")
            print(f"📂 Resolved to: {resolved_path}")
            return resolved_path
        else:
            raise ValueError("Master file not found in database. Please upload it first.")
    
    except Exception as e:
        raise Exception(f"Failed to fetch master file path: {str(e)}")


def run(job_folder):
    """
    Map extracted stocks to master file
    
    Args:
        job_folder: Path to job directory
        
    Returns:
        dict: Status, message, and output files
    """
    print("\n" + "="*60)
    print("STEP 9: Map Master File")
    print(f"{'='*60}\n")

    try:
        # Input/Output paths
        input_csv = os.path.join(job_folder, "analysis", "extracted_stocks.csv")
        output_csv = os.path.join(job_folder, "analysis", "mapped_master_file.csv")
        
        # Verify input file exists
        if not os.path.exists(input_csv):
            return {
                'status': 'failed',
                'message': f'Extracted stocks file not found: {input_csv}'
            }
        
        # Get master file path from database
        print("🔑 Retrieving master file path from database...")
        master_file_path = get_master_file_path()
        
        if not os.path.exists(master_file_path):
            return {
                'status': 'failed',
                'message': f'Master file not found at: {master_file_path}'
            }
        
        print(f"✅ Master file found: {master_file_path}\n")
        
        # Load master file
        print("📖 Loading master file...")
        df_api = pd.read_csv(master_file_path, low_memory=False)
        print(f"✅ Loaded {len(df_api)} records from master file\n")
        
        # Filter for EQUITY only
        print("🔍 Filtering for EQUITY instruments...")
        df_api = df_api[df_api["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == "EQUITY"].copy()
        print(f"✅ {len(df_api)} EQUITY records found\n")
        
        # Normalize text fields in master file
        print("🔧 Normalizing master file fields...")
        for col in ["SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "SM_SYMBOL_NAME", "SEM_EXM_EXCH_ID"]:
            if col in df_api.columns:
                df_api[col] = df_api[col].astype(str).str.strip().str.upper()
            else:
                df_api[col] = ""
        
        # Add normalized matching columns
        df_api["SEM_CUSTOM_SYMBOL_NORM"] = df_api["SEM_CUSTOM_SYMBOL"].apply(normalize_text)
        df_api["SM_SYMBOL_NAME_NORM"] = df_api["SM_SYMBOL_NAME"].apply(normalize_text)
        df_api["SEM_TRADING_SYMBOL_NORM"] = df_api["SEM_TRADING_SYMBOL"].apply(normalize_text)
        
        # Add Exchange priority: NSE > BSE > Others
        df_api["exchange_priority"] = df_api["SEM_EXM_EXCH_ID"].apply(
            lambda x: 1 if x == "NSE" else (2 if x == "BSE" else 3)
        )
        print("✅ Master file normalized\n")
        
        # Load input file (extracted stocks)
        print("📖 Loading extracted stocks...")
        df_input = pd.read_csv(input_csv)
        df_input.columns = df_input.columns.str.strip().str.upper().str.replace("  ", " ")
        
        # Identify columns
        possible_symbol_cols = [c for c in df_input.columns if "SYMBOL" in c]
        possible_name_cols = [c for c in df_input.columns if "NAME" in c and "STOCK" in c]
        
        if not possible_symbol_cols:
            return {
                'status': 'failed',
                'message': 'Could not find STOCK SYMBOL column in extracted stocks'
            }
        if not possible_name_cols:
            return {
                'status': 'failed',
                'message': 'Could not find STOCK NAME column in extracted stocks'
            }
        
        symbol_col = possible_symbol_cols[0]
        name_col = possible_name_cols[0]
        
        df_input[symbol_col] = df_input[symbol_col].astype(str).str.strip().str.upper()
        df_input[name_col] = df_input[name_col].astype(str).str.strip().str.upper()
        
        # Add normalized versions for fuzzy matching
        df_input["SYMBOL_NORM"] = df_input[symbol_col].apply(normalize_text)
        df_input["NAME_NORM"] = df_input[name_col].apply(normalize_text)
        
        print(f"✅ Loaded {len(df_input)} stocks to map\n")
        
        # Matching logic
        print("🔗 Starting stock matching process...")
        print("-" * 60)
        
        results = []
        matched_count = 0
        
        for idx, row in df_input.iterrows():
            stock_symbol = row[symbol_col]
            stock_name = row[name_col]
            start_time = row.get("START TIME", "")

            match = None
            match_source = ""
            candidates = pd.DataFrame()

            # 1. Exact match on SEM_TRADING_SYMBOL
            candidates = df_api[df_api["SEM_TRADING_SYMBOL"] == stock_symbol]
            if not candidates.empty:
                match_source = "SEM_TRADING_SYMBOL (exact)"

            # 2. Exact match on SEM_CUSTOM_SYMBOL
            if candidates.empty:
                candidates = df_api[df_api["SEM_CUSTOM_SYMBOL"] == stock_symbol]
                if not candidates.empty:
                    match_source = "SEM_CUSTOM_SYMBOL (exact)"

            # 3. Exact match on SM_SYMBOL_NAME
            if candidates.empty:
                candidates = df_api[df_api["SM_SYMBOL_NAME"] == stock_symbol]
                if not candidates.empty:
                    match_source = "SM_SYMBOL_NAME (exact)"

            # 4. Fuzzy match on SEM_CUSTOM_SYMBOL using symbol
            if candidates.empty:
                idx_match = fuzzy_match(stock_symbol, df_api["SEM_CUSTOM_SYMBOL_NORM"])
                if idx_match is not None:
                    candidates = df_api.loc[[idx_match]]
                    match_source = "SEM_CUSTOM_SYMBOL (fuzzy symbol)"

            # 5. Fuzzy match on SM_SYMBOL_NAME using symbol
            if candidates.empty:
                idx_match = fuzzy_match(stock_symbol, df_api["SM_SYMBOL_NAME_NORM"])
                if idx_match is not None:
                    candidates = df_api.loc[[idx_match]]
                    match_source = "SM_SYMBOL_NAME (fuzzy symbol)"

            # 6. Fuzzy match on SEM_CUSTOM_SYMBOL using name
            if candidates.empty:
                idx_match = fuzzy_match(stock_name, df_api["SEM_CUSTOM_SYMBOL_NORM"])
                if idx_match is not None:
                    candidates = df_api.loc[[idx_match]]
                    match_source = "SEM_CUSTOM_SYMBOL (fuzzy name)"

            # 7. Fuzzy match on SM_SYMBOL_NAME using name
            if candidates.empty:
                idx_match = fuzzy_match(stock_name, df_api["SM_SYMBOL_NAME_NORM"])
                if idx_match is not None:
                    candidates = df_api.loc[[idx_match]]
                    match_source = "SM_SYMBOL_NAME (fuzzy name)"

            # 8. FINAL FALLBACK: Normalize STOCK NAME & match SEM_TRADING_SYMBOL
            if candidates.empty:
                stock_name_norm = normalize_text(stock_name)
                idx_list = df_api[df_api["SEM_TRADING_SYMBOL_NORM"] == stock_name_norm].index
                if len(idx_list) > 0:
                    candidates = df_api.loc[idx_list]
                    match_source = "SEM_TRADING_SYMBOL (normalized name fallback)"

            # Pick best match (NSE preferred)
            if not candidates.empty:
                candidates = candidates.sort_values(by="exchange_priority")
                match = candidates.iloc[0]

            # Prepare output
            if match is not None:
                listed_name = match.get("SM_SYMBOL_NAME", "")
                short_name = match.get("SEM_CUSTOM_SYMBOL", "")
                security_id = match.get("SEM_SMST_SECURITY_ID", "")
                exchange = match.get("SEM_EXM_EXCH_ID", "")
                instrument = match.get("SEM_INSTRUMENT_NAME", "")
                segment = match.get("SEM_SEGMENT", "")

                # Adjust names based on match source
                if "SEM_CUSTOM_SYMBOL" in match_source:
                    short_name = stock_symbol or short_name
                elif "SM_SYMBOL_NAME" in match_source:
                    listed_name = stock_symbol or listed_name

                results.append({
                    "STOCK NAME": stock_name,
                    "STOCK SYMBOL": stock_symbol,
                    "LISTED NAME": listed_name,
                    "SHORT NAME": short_name,
                    "SECURITY ID": security_id,
                    "EXCHANGE": exchange,
                    "INSTRUMENT": instrument,
                    "SEGMENT": segment,
                    "START TIME": start_time
                })
                matched_count += 1
                print(f"✅ {stock_symbol:15} → {match_source:40} ({exchange})")
            else:
                print(f"❌ {stock_symbol:15} → No match found")
                results.append({
                    "STOCK NAME": stock_name,
                    "STOCK SYMBOL": stock_symbol,
                    "LISTED NAME": "",
                    "SHORT NAME": "",
                    "SECURITY ID": "",
                    "EXCHANGE": "",
                    "INSTRUMENT": "",
                    "SEGMENT": "",
                    "START TIME": start_time
                })

        print("-" * 60)
        print(f"\n📊 Matching Summary:")
        print(f"   Total stocks: {len(df_input)}")
        print(f"   Matched: {matched_count}")
        print(f"   Unmatched: {len(df_input) - matched_count}\n")
        
        # Save final output
        print(f"💾 Saving mapped data to: {output_csv}")
        final_df = pd.DataFrame(results)
        
        # Ensure analysis directory exists
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        
        final_df.to_csv(output_csv, index=False)
        
        print(f"✅ Saved {len(final_df)} records")
        print(f"✅ Output: analysis/mapped_master_file.csv\n")
        
        return {
            'status': 'success',
            'message': f'Mapped {matched_count} of {len(df_input)} stocks to master file',
            'output_files': ['analysis/mapped_master_file.csv']
        }
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Master file mapping failed: {str(e)}'
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
