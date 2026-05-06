"""
Bulk Rationale Step 2: Convert to CSV
Converts bulk-input-english.txt to structured CSV
- Direct parsing without AI validation
- User provides stock symbols/short names directly
- Splits multi-stock entries by comma
- Handles flexible input formats (with/without empty lines)
- Cleans up special characters like (CALL), (BUY), etc.
"""

import os
import re
import pandas as pd


def clean_stock_symbol(raw_symbol):
    """
    Clean a stock symbol by removing special characters and suffixes.
    
    Removes:
    - Content inside brackets: "HUL (Hindustan Unilever)" -> "HUL"
    - (CALL), (BUY), (SELL), (HOLD), (ADD), (FRESH), (EXIT) etc.
    - Trailing dashes and colons
    - Extra whitespace
    - Special characters except & and spaces
    
    Args:
        raw_symbol: Raw stock symbol string
        
    Returns:
        Cleaned stock symbol in uppercase
    """
    if not raw_symbol:
        return ""
    
    symbol = raw_symbol.strip()
    
    symbol = re.sub(r'\s*\([^)]*\)\s*', ' ', symbol)
    
    symbol = re.sub(r'\s*\[[^\]]*\]\s*', ' ', symbol)
    
    symbol = re.sub(r'[\-–—:]+\s*$', '', symbol)
    symbol = re.sub(r'^[\-–—:]+\s*', '', symbol)
    
    symbol = re.sub(r'[^\w\s&]', ' ', symbol)
    
    symbol = re.sub(r'\s+', ' ', symbol).strip()
    
    symbol = symbol.upper()
    
    return symbol


def is_stock_line(line):
    """
    Determine if a line is likely a stock symbol line (not analysis text).
    
    Stock lines are typically:
    - Short (< 100 characters)
    - Don't contain common analysis words
    - May end with - or :
    - May contain comma-separated stocks
    
    Args:
        line: Text line to check
        
    Returns:
        True if likely a stock line, False if likely analysis
    """
    if not line or not line.strip():
        return False
    
    line = line.strip()
    
    if line.endswith('-') or line.endswith(':') or line.endswith(' -') or line.endswith(' :'):
        return True
    
    if len(line) > 150:
        return False
    
    analysis_indicators = [
        'the stock', 'should', 'could', 'would', 'might',
        'target', 'stop loss', 'stoploss', 'support', 'resistance',
        'breakout', 'breakdown', 'trading at', 'currently',
        'buy above', 'sell below', 'hold', 'accumulate',
        'short term', 'long term', 'medium term',
        'bullish', 'bearish', 'neutral', 'positive', 'negative',
        'maintain', 'exit', 'book profit', 'stay invested',
        'looking good', 'looking weak', 'consolidating',
        'moving average', 'rsi', 'macd', 'volume',
        'fundamental', 'technical', 'chart', 'pattern',
        'i think', 'we think', 'my view', 'our view',
        'price is', 'cmp is', 'current price',
        'recommended', 'recommendation', 'advised',
        'range of', 'zone of', 'levels of',
        'will reach', 'can reach', 'may reach',
        'expected', 'expecting', 'anticipate',
        'upside', 'downside', 'potential',
        'investment', 'investor', 'portfolio'
    ]
    
    line_lower = line.lower()
    
    indicator_count = sum(1 for indicator in analysis_indicators if indicator in line_lower)
    if indicator_count >= 2:
        return False
    
    words = line.split()
    if len(words) <= 6:
        return True
    
    if len(words) <= 10 and indicator_count == 0:
        return True
    
    return False


def parse_bulk_input(input_text):
    """
    Parse bulk input text into stock entries.
    
    Supports multiple formats:
    1. Stock Symbol -
       Analysis text...
       
    2. SYMBOL1, SYMBOL2
       Shared analysis text...
       
    3. Stock Symbol
       Analysis text (no dash, directly followed)
    
    Args:
        input_text: Raw input text
        
    Returns:
        List of tuples: [(stock_symbols_string, analysis_text), ...]
    """
    lines = input_text.strip().split('\n')
    entries = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            i += 1
            continue
        
        if not is_stock_line(line):
            i += 1
            continue
        
        stock_line = line.rstrip(' -–—:').strip()
        
        if not stock_line:
            i += 1
            continue
        
        i += 1
        
        while i < len(lines) and not lines[i].strip():
            i += 1
        
        analysis_lines = []
        while i < len(lines):
            next_line = lines[i].strip()
            
            if not next_line:
                i += 1
                if i < len(lines) and lines[i].strip():
                    peek_line = lines[i].strip()
                    if is_stock_line(peek_line):
                        break
                    else:
                        analysis_lines.append(peek_line)
                        i += 1
                        continue
                else:
                    break
            
            if is_stock_line(next_line) and len(analysis_lines) > 0:
                break
            
            analysis_lines.append(next_line)
            i += 1
        
        analysis_text = ' '.join(analysis_lines).strip()
        
        if analysis_text and len(analysis_text) >= 10:
            entries.append((stock_line, analysis_text))
        elif stock_line:
            print(f"⚠️ Skipping '{stock_line}' - no analysis found or too short")
    
    return entries


def split_and_clean_stocks(stock_line):
    """
    Split comma-separated stocks and clean each symbol.
    
    Args:
        stock_line: Raw stock line (may contain multiple stocks)
        
    Returns:
        List of cleaned stock symbols
    """
    separators = [',', '/', '&', ' and ', ' AND ', ' And ']
    
    stocks = [stock_line]
    
    for sep in [',', '/']:
        new_stocks = []
        for stock in stocks:
            if sep in stock:
                parts = stock.split(sep)
                for part in parts:
                    cleaned = part.strip()
                    if cleaned:
                        new_stocks.append(cleaned)
            else:
                new_stocks.append(stock)
        stocks = new_stocks
    
    cleaned_stocks = []
    for stock in stocks:
        cleaned = clean_stock_symbol(stock)
        if cleaned and len(cleaned) >= 2:
            if ' AND ' in cleaned:
                sub_parts = cleaned.split(' AND ')
                for sub in sub_parts:
                    sub_cleaned = sub.strip()
                    if sub_cleaned and len(sub_cleaned) >= 2 and len(sub_cleaned) <= 50:
                        cleaned_stocks.append(sub_cleaned)
                    elif sub_cleaned and len(sub_cleaned) > 50:
                        cleaned_stocks.append(cleaned)
                        break
            else:
                cleaned_stocks.append(cleaned)
    
    return cleaned_stocks


def deduplicate_stocks(rows):
    """
    Remove duplicate stock entries, keeping first occurrence.
    
    Args:
        rows: List of row dictionaries
        
    Returns:
        Deduplicated list of rows
    """
    seen = set()
    unique_rows = []
    
    for row in rows:
        stock = row['INPUT STOCK']
        if stock not in seen:
            seen.add(stock)
            unique_rows.append(row)
        else:
            print(f"⚠️ Removing duplicate: {stock}")
    
    return unique_rows


def run(job_folder, call_date, call_time):
    """
    Convert translated text to structured CSV
    
    Args:
        job_folder: Path to job directory
        call_date: Date of the call (YYYY-MM-DD format)
        call_time: Time of the call (HH:MM:SS format)
        
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("BULK STEP 2: CONVERT TO CSV")
    print("=" * 60 + "\n")
    
    try:
        input_file = os.path.join(job_folder, 'bulk-input-english.txt')
        analysis_folder = os.path.join(job_folder, 'analysis')
        os.makedirs(analysis_folder, exist_ok=True)
        output_file = os.path.join(analysis_folder, 'bulk-input.csv')
        
        if not os.path.exists(input_file):
            return {
                'success': False,
                'error': f'Translated file not found: {input_file}'
            }
        
        print(f"📖 Reading input file: {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            input_text = f.read()
        
        print(f"📝 Text length: {len(input_text)} characters")
        print(f"📅 Call Date: {call_date}, Time: {call_time}")
        
        print("\n🔄 Parsing input text...")
        entries = parse_bulk_input(input_text)
        print(f"✅ Found {len(entries)} stock entries")
        
        if not entries:
            return {
                'success': False,
                'error': 'No stock entries found in input. Check input format: each stock should have a name line followed by analysis text.'
            }
        
        print("\n📋 Processing stocks:")
        print("-" * 60)
        
        rows = []
        for idx, (stock_line, analysis) in enumerate(entries):
            stock_symbols = split_and_clean_stocks(stock_line)
            
            for symbol in stock_symbols:
                print(f"  {len(rows)+1}. {symbol}")
                rows.append({
                    "DATE": call_date,
                    "TIME": call_time,
                    "INPUT STOCK": symbol,
                    "ANALYSIS": analysis
                })
        
        print("-" * 60)
        
        print("\n🔍 Removing duplicates...")
        rows = deduplicate_stocks(rows)
        
        if not rows:
            return {
                'success': False,
                'error': 'No valid stocks extracted from input text'
            }
        
        df = pd.DataFrame(rows)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        print(f"\n✅ Created {len(df)} stock entries")
        print(f"💾 Saved to: {output_file}")
        
        print("\n📋 Final Stock List:")
        print("-" * 40)
        for idx, (_, row) in enumerate(df.iterrows()):
            print(f"  {idx+1}. {row['INPUT STOCK']}")
        print("-" * 40)
        
        return {
            'success': True,
            'output_file': output_file,
            'stock_count': len(df)
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
    
    result = run(test_folder, "2025-01-01", "10:00:00")
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
