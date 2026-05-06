"""
Bulk Rationale Step 4: Map Master File

Maps INPUT STOCK from Step 2/3 CSV to the master reference file to get:
- Stock Symbol (SEM_TRADING_SYMBOL)
- Listed Name (SM_SYMBOL_NAME)
- Short Name (SEM_CUSTOM_SYMBOL)
- Security ID (SEM_SMST_SECURITY_ID)
- Exchange (SEM_EXM_EXCH_ID)
- Instrument (SEM_INSTRUMENT_NAME)

Matching Logic (Priority Order):
1. EXACT match (normalized): INPUT STOCK → SEM_TRADING_SYMBOL
2. EXACT match (normalized): INPUT STOCK → SEM_CUSTOM_SYMBOL
3. EXACT match (normalized): INPUT STOCK → SM_SYMBOL_NAME
4. PREFIX match: INPUT STOCK starts with SEM_TRADING_SYMBOL (or vice versa)
5. PREFIX match: INPUT STOCK starts with SEM_CUSTOM_SYMBOL (or vice versa)
6. WORD FUZZY match: Split INPUT STOCK into words, match word prefixes to symbol
   - Example: "DEEPK FERTILIZER" → "DEEPAKFERT"
   - "DEEPK" matches start of "DEEPAK", "FERT" from "FERTILIZER" matches in symbol

Normalization: Remove ALL spaces and special characters for comparison
This handles user mistakes like "TATA MOTORS" vs "TATAMOTORS"

If both NSE and BSE found → Prefer NSE

Input:
  - analysis/bulk-input-analysis.csv (from Step 3) or analysis/bulk-input.csv (from Step 2)
  - Master CSV from uploaded_files
Output:
  - analysis/mapped_master_file.csv
"""

import os
import re
import pandas as pd
import psycopg2
from backend.utils.path_utils import resolve_uploaded_file_path


def normalize_for_exact_match(s):
    """
    Normalize text for EXACT matching.
    Removes ALL spaces, special characters, keeps only alphanumeric.
    This handles cases like:
    - "TATA MOTORS" vs "TATAMOTORS"
    - "HDFC BANK" vs "HDFCBANK"
    - "M&M" vs "M AND M"
    """
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    s = s.upper().strip()
    s = re.sub(r'[^A-Z0-9]', '', s)
    return s


def normalize_for_display(s):
    """Normalize text for display (uppercase, trimmed)."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return s.upper().strip()


def prefix_match_score(input_norm, target_norm):
    """
    Calculate prefix match score.
    Returns score based on how well the strings match from the beginning.
    
    Rules:
    - One must start with the other (at least 3 chars overlap)
    - Score is based on length of overlap
    - Longer overlap = higher score
    
    Returns: (is_match, overlap_length, score_percentage)
    """
    if not input_norm or not target_norm:
        return False, 0, 0
    
    min_overlap = 3
    
    if input_norm.startswith(target_norm):
        overlap = len(target_norm)
        if overlap >= min_overlap:
            score = (overlap / len(input_norm)) * 100
            return True, overlap, score
    
    if target_norm.startswith(input_norm):
        overlap = len(input_norm)
        if overlap >= min_overlap:
            score = (overlap / len(target_norm)) * 100
            return True, overlap, score
    
    return False, 0, 0


def word_fuzzy_match_score(input_stock_raw, target_symbol_norm, min_chars=3):
    """
    Word-based fuzzy matching for cases like:
    - "DEEPK FERTILIZER" → "DEEPAKFERT" 
    - "TATA POWER" → "TATAPOWER"
    
    CRITICAL RULE: First word MUST match the BEGINNING of target symbol!
    - "HUL" must NOT match "MEHUL" (HUL doesn't start MEHUL)
    - "DEEPK" CAN match "DEEPAKFERT" (DEEP starts DEEPAKFERT)
    
    Logic:
    1. Split input into words: ["DEEPK", "FERTILIZER"]
    2. FIRST word prefix MUST start the target symbol
    3. Subsequent words can be found within remaining part
    
    Returns: (is_match, match_score, matched_words_count)
    """
    if not input_stock_raw or not target_symbol_norm:
        return False, 0, 0
    
    words = re.split(r'[\s\-_&]+', input_stock_raw.upper().strip())
    words = [w.strip() for w in words if w.strip() and len(w.strip()) >= min_chars]
    
    if not words:
        return False, 0, 0
    
    first_word = words[0]
    first_word_matched = False
    first_match_len = 0
    
    for prefix_len in range(len(first_word), min_chars - 1, -1):
        prefix = first_word[:prefix_len]
        if target_symbol_norm.startswith(prefix):
            first_word_matched = True
            first_match_len = prefix_len
            break
    
    if not first_word_matched:
        return False, 0, 0
    
    matched_words = 1
    total_matched_chars = first_match_len
    
    remaining_target = target_symbol_norm[first_match_len:]
    
    for word in words[1:]:
        word_matched = False
        
        for prefix_len in range(min(len(word), 6), min_chars - 1, -1):
            prefix = word[:prefix_len]
            if prefix in remaining_target:
                word_matched = True
                total_matched_chars += prefix_len
                pos = remaining_target.find(prefix)
                remaining_target = remaining_target[pos + prefix_len:]
                break
        
        if word_matched:
            matched_words += 1
    
    if matched_words == 0:
        return False, 0, 0
    
    match_ratio = matched_words / len(words)
    char_coverage = total_matched_chars / len(target_symbol_norm) if target_symbol_norm else 0
    
    if match_ratio >= 0.5 and char_coverage >= 0.4:
        score = (match_ratio * 50) + (char_coverage * 50)
        return True, score, matched_words
    
    return False, 0, 0


def find_word_fuzzy_match(input_stock_raw, input_stock_norm, df_master, min_score=50):
    """
    Find best word-based fuzzy match when exact/prefix matching fails.
    
    Examples this handles:
    - "DEEPK FERTILIZER" → "DEEPAKFERT"
    - "BHARTI AIR" → "BHARTIARTL"
    
    Args:
        input_stock_raw: Original input stock name (with spaces)
        input_stock_norm: Normalized input (no spaces)
        df_master: Master DataFrame
        min_score: Minimum score threshold
    
    Returns:
        (best_match_row, score, matched_words) or (None, 0, 0)
    """
    best_match = None
    best_score = 0
    best_matched_words = 0
    
    for idx, row in df_master.iterrows():
        for col_norm in ["SEM_TRADING_SYMBOL_NORM", "SEM_CUSTOM_SYMBOL_NORM"]:
            target_norm = row.get(col_norm, "")
            if not target_norm or len(target_norm) < 4:
                continue
            
            is_match, score, matched_words = word_fuzzy_match_score(
                input_stock_raw, target_norm, min_chars=3
            )
            
            if is_match and score > best_score and score >= min_score:
                best_match = row
                best_score = score
                best_matched_words = matched_words
    
    return best_match, best_score, best_matched_words


def get_master_file_path():
    """Fetch master file path from database and resolve to current system path"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT file_path 
            FROM uploaded_files 
            WHERE file_type = 'masterFile'
            ORDER BY uploaded_at DESC
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
            raise ValueError("Master file not found in database. Please upload it first in Settings.")
    
    except Exception as e:
        raise Exception(f"Failed to fetch master file path: {str(e)}")


def find_exact_match(input_norm, df_master, column_norm):
    """
    Find exact match in normalized column.
    Returns DataFrame of matching rows (may have multiple for NSE/BSE).
    """
    matches = df_master[df_master[column_norm] == input_norm]
    return matches


def find_prefix_match(input_norm, df_master, column_norm, min_score=70):
    """
    Find best prefix match in a column.
    Returns best matching row or None.
    
    Args:
        input_norm: Normalized input stock name
        df_master: Master DataFrame
        column_norm: Normalized column name to search
        min_score: Minimum score threshold (percentage)
    
    Returns:
        (best_match_row, overlap_length) or (None, 0)
    """
    best_match = None
    best_overlap = 0
    best_score = 0
    
    for idx, row in df_master.iterrows():
        target_norm = row.get(column_norm, "")
        if not target_norm:
            continue
        
        is_match, overlap, score = prefix_match_score(input_norm, target_norm)
        
        if is_match and overlap > best_overlap and score >= min_score:
            best_match = row
            best_overlap = overlap
            best_score = score
        elif is_match and overlap == best_overlap and score > best_score:
            best_match = row
            best_score = score
    
    return best_match, best_overlap


def run(job_folder):
    """
    Match stocks to master file and add symbol/exchange data
    
    Args:
        job_folder: Path to job folder
    
    Returns:
        dict: Status, message, and output files
    """
    print("\n" + "="*60)
    print("BULK STEP 4: MAP MASTER FILE (SYMBOL MAPPING)")
    print("="*60 + "\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        polished_csv = os.path.join(analysis_folder, 'bulk-input-analysis.csv')
        original_csv = os.path.join(analysis_folder, 'bulk-input.csv')
        input_csv = polished_csv if os.path.exists(polished_csv) else original_csv
        output_csv = os.path.join(analysis_folder, 'mapped_master_file.csv')
        
        if not os.path.exists(input_csv):
            return {
                'success': False,
                'error': f'Bulk input CSV not found: {input_csv}'
            }
        
        print(f"📖 Using input file: {os.path.basename(input_csv)}")
        
        print("\n🔑 Retrieving master file path from database...")
        master_file_path = get_master_file_path()
        
        if not os.path.exists(master_file_path):
            return {
                'success': False,
                'error': f'Master file not found at: {master_file_path}'
            }
        
        print(f"✅ Master file found\n")
        
        print("📖 Loading master file...")
        df_master = pd.read_csv(master_file_path, low_memory=False)
        print(f"✅ Loaded {len(df_master)} records from master file\n")
        
        print("🔍 Filtering for EQUITY instruments...")
        df_master = df_master[df_master["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == "EQUITY"].copy()
        print(f"✅ {len(df_master)} EQUITY records found\n")
        
        print("🔧 Normalizing master file fields...")
        for col in ["SEM_TRADING_SYMBOL", "SEM_CUSTOM_SYMBOL", "SM_SYMBOL_NAME", "SEM_EXM_EXCH_ID"]:
            if col in df_master.columns:
                df_master[col] = df_master[col].astype(str).str.strip().str.upper()
            else:
                df_master[col] = ""
        
        df_master["SEM_TRADING_SYMBOL_NORM"] = df_master["SEM_TRADING_SYMBOL"].apply(normalize_for_exact_match)
        df_master["SEM_CUSTOM_SYMBOL_NORM"] = df_master["SEM_CUSTOM_SYMBOL"].apply(normalize_for_exact_match)
        df_master["SM_SYMBOL_NAME_NORM"] = df_master["SM_SYMBOL_NAME"].apply(normalize_for_exact_match)
        
        df_master["exchange_priority"] = df_master["SEM_EXM_EXCH_ID"].apply(
            lambda x: 1 if x == "NSE" else (2 if x == "BSE" else 3)
        )
        print("✅ Master file normalized\n")
        
        print("📖 Loading bulk input stocks...")
        df_input = pd.read_csv(input_csv)
        df_input.columns = df_input.columns.str.strip().str.upper()
        
        if 'INPUT STOCK' not in df_input.columns:
            if 'STOCK NAME' in df_input.columns:
                df_input.rename(columns={'STOCK NAME': 'INPUT STOCK'}, inplace=True)
            else:
                return {
                    'success': False,
                    'error': 'INPUT STOCK column not found in bulk-input.csv'
                }
        
        df_input['INPUT STOCK'] = df_input['INPUT STOCK'].astype(str).str.strip().str.upper()
        df_input["INPUT_STOCK_NORM"] = df_input['INPUT STOCK'].apply(normalize_for_exact_match)
        
        print(f"✅ Loaded {len(df_input)} stocks to map\n")
        
        print("🔗 Starting stock matching process...")
        print("-" * 80)
        print(f"{'INPUT STOCK':<25} {'MATCHED SYMBOL':<18} {'METHOD':<35} {'EXCH':<5}")
        print("-" * 80)
        
        results = []
        matched_count = 0
        
        for idx, row in df_input.iterrows():
            input_stock = row['INPUT STOCK']
            input_stock_norm = row['INPUT_STOCK_NORM']
            date = row.get('DATE', '')
            time = row.get('TIME', '')
            analysis = row.get('ANALYSIS', row.get('RATIONALE', ''))
            chart_type = row.get('CHART TYPE', 'Daily')
            
            match = None
            match_source = ""
            candidates = pd.DataFrame()
            
            candidates = find_exact_match(input_stock_norm, df_master, "SEM_TRADING_SYMBOL_NORM")
            if not candidates.empty:
                match_source = "SEM_TRADING_SYMBOL (exact)"
            
            if candidates.empty:
                candidates = find_exact_match(input_stock_norm, df_master, "SEM_CUSTOM_SYMBOL_NORM")
                if not candidates.empty:
                    match_source = "SEM_CUSTOM_SYMBOL (exact)"
            
            if candidates.empty:
                candidates = find_exact_match(input_stock_norm, df_master, "SM_SYMBOL_NAME_NORM")
                if not candidates.empty:
                    match_source = "SM_SYMBOL_NAME (exact)"
            
            if candidates.empty:
                prefix_match, overlap = find_prefix_match(input_stock_norm, df_master, "SEM_TRADING_SYMBOL_NORM", min_score=70)
                if prefix_match is not None:
                    candidates = pd.DataFrame([prefix_match])
                    match_source = f"SEM_TRADING_SYMBOL (prefix {overlap} chars)"
            
            if candidates.empty:
                prefix_match, overlap = find_prefix_match(input_stock_norm, df_master, "SEM_CUSTOM_SYMBOL_NORM", min_score=70)
                if prefix_match is not None:
                    candidates = pd.DataFrame([prefix_match])
                    match_source = f"SEM_CUSTOM_SYMBOL (prefix {overlap} chars)"
            
            if candidates.empty:
                fuzzy_match, score, matched_words = find_word_fuzzy_match(
                    input_stock, input_stock_norm, df_master, min_score=50
                )
                if fuzzy_match is not None:
                    candidates = pd.DataFrame([fuzzy_match])
                    match_source = f"WORD FUZZY (score:{score:.0f}, words:{matched_words})"
            
            if not candidates.empty:
                candidates = candidates.sort_values(by="exchange_priority")
                match = candidates.iloc[0]
            
            if match is not None:
                stock_symbol = match.get("SEM_TRADING_SYMBOL", "")
                listed_name = match.get("SM_SYMBOL_NAME", "")
                short_name = match.get("SEM_CUSTOM_SYMBOL", "")
                security_id = match.get("SEM_SMST_SECURITY_ID", "")
                exchange = match.get("SEM_EXM_EXCH_ID", "")
                instrument = match.get("SEM_INSTRUMENT_NAME", "")
                
                results.append({
                    "DATE": date,
                    "TIME": time,
                    "INPUT STOCK": input_stock,
                    "ANALYSIS": analysis,
                    "CHART TYPE": chart_type,
                    "STOCK SYMBOL": stock_symbol,
                    "LISTED NAME": listed_name,
                    "SHORT NAME": short_name,
                    "SECURITY ID": security_id,
                    "EXCHANGE": exchange,
                    "INSTRUMENT": instrument
                })
                matched_count += 1
                print(f"✅ {input_stock:<25} {stock_symbol:<18} {match_source:<35} {exchange:<5}")
            else:
                print(f"❌ {input_stock:<25} {'NO MATCH':<18} {'':<35} {'':<5}")
                results.append({
                    "DATE": date,
                    "TIME": time,
                    "INPUT STOCK": input_stock,
                    "ANALYSIS": analysis,
                    "CHART TYPE": chart_type,
                    "STOCK SYMBOL": "",
                    "LISTED NAME": "",
                    "SHORT NAME": "",
                    "SECURITY ID": "",
                    "EXCHANGE": "",
                    "INSTRUMENT": ""
                })
        
        print("-" * 80)
        print(f"\n📊 Mapping Summary:")
        print(f"   Total stocks: {len(df_input)}")
        print(f"   Matched: {matched_count}")
        print(f"   Unmatched: {len(df_input) - matched_count}")
        
        if len(df_input) - matched_count > 0:
            print("\n⚠️  Unmatched stocks (please check spelling):")
            for r in results:
                if not r.get("STOCK SYMBOL"):
                    print(f"   - {r['INPUT STOCK']}")
        
        print(f"\n💾 Saving mapped data to: {output_csv}")
        final_df = pd.DataFrame(results)
        
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        
        final_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        
        print(f"✅ Saved {len(final_df)} records")
        print(f"✅ Output: analysis/mapped_master_file.csv\n")
        
        return {
            'success': True,
            'output_file': output_csv,
            'matched_count': matched_count,
            'total_stocks': len(df_input),
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
        test_folder = "backend/job_files/test_bulk_job"
    
    result = run(test_folder)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
