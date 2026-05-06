"""
Premium Step 1: Generate Premium Rationale CSV from Input Text
Uses OpenAI GPT-4o Expert Analyst to parse stock calls and create structured CSV
"""
import os
import csv
from openai import OpenAI
from backend.utils.openai_config import get_model, get_premium_csv_prompt


def run(job_folder, input_text, openai_api_key):
    """
    Parse input text and generate premium_rationale_stocks.csv
    
    Args:
        job_folder: Path to job folder
        input_text: Raw text with stock calls
        openai_api_key: OpenAI API key
    
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'stocks_count': int,
            'error': str or None
        }
    """
    try:
        print("=" * 60)
        print("PREMIUM STEP 1: GENERATE CSV FROM INPUT TEXT")
        print("=" * 60)
        
        analysis_folder = os.path.join(job_folder, 'analysis')
        os.makedirs(analysis_folder, exist_ok=True)
        
        output_csv = os.path.join(analysis_folder, 'premium_rationale_stocks.csv')
        
        # TODO: Implement OpenAI parsing logic
        print("🤖 Calling OpenAI GPT to parse stock calls...")
        print(f"   Input length: {len(input_text)} characters")
        
        if not openai_api_key:
            raise ValueError("OpenAI API key not found in database")
        
        client = OpenAI(api_key=openai_api_key)
        
        prompt = f"""**Premium Stock Call Extraction Task**

**Required CSV Columns (EXACT header):**
DATE,TIME,STOCK NAME,TARGETS,STOP LOSS,HOLDING PERIOD,CALL,CHART TYPE

**Extraction Rules:**

1. **DATE:** Format as YYYY-MM-DD (e.g., 2025-11-25)
   - If only day mentioned, use current month/year
   - If "today", use current date

2. **TIME:** Format as HH:MM:SS (24-hour, e.g., 14:30:00)
   - If not specified, use 09:15:00 (market open)

3. **STOCK NAME:** Full company name or NSE symbol
   - Standardize names (e.g., "Reliance" → "Reliance Industries")

4. **TARGETS:** Price targets (comma-separated if multiple)
   - Format: "150, 175, 200" for multiple targets
   - Include only numeric values with commas

5. **STOP LOSS:** Stop-loss price or percentage
   - Prefer absolute price if available
   - Format percentage as "5%" if given

6. **HOLDING PERIOD:** Trading timeframe
   - Intraday, Short Term (1-5 days), Medium Term (1-4 weeks), Long Term (1+ month)

7. **CALL:** Trade action - STRICTLY one of:
   - BUY, SELL, HOLD, ACCUMULATE, BOOK PROFIT, EXIT

8. **CHART TYPE:** STRICTLY one of:
   - "Daily" → Intraday, Short Term, Swing trades
   - "Weekly" → Medium Term trades (1-4 weeks)
   - "Monthly" → Long Term, Positional trades
   - Default: "Daily" if unclear

**Output Requirements:**
- Return ONLY CSV data with header row
- NO markdown formatting (no ```csv or ``` tags)
- Proper CSV escaping for commas in values
- Empty fields: include comma but leave blank
- All rows must have exactly 8 columns

**Input Text:**
{input_text}

**Output (CSV format only):**"""
        
        response = client.chat.completions.create(
            model=get_model(),
            messages=[
                {
                    "role": "system", 
                    "content": get_premium_csv_prompt()
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=2000
        )
        
        csv_content = response.choices[0].message.content.strip()
        
        # Remove markdown formatting if present
        if csv_content.startswith("```"):
            lines = csv_content.split('\n')
            csv_content = '\n'.join([line for line in lines if not line.startswith('```')])
            csv_content = csv_content.strip()
        
        # Additional cleanup: remove "csv" tag if present
        if csv_content.lower().startswith("csv"):
            csv_content = '\n'.join(csv_content.split('\n')[1:]).strip()
        
        # Validate CSV format
        lines = csv_content.split('\n')
        if len(lines) < 2:
            raise ValueError("Generated CSV has no data rows")
        
        # Check header
        expected_header = "DATE,TIME,STOCK NAME,TARGETS,STOP LOSS,HOLDING PERIOD,CALL,CHART TYPE"
        actual_header = lines[0].strip()
        
        if actual_header != expected_header:
            print(f"⚠️  Warning: Header mismatch")
            print(f"   Expected: {expected_header}")
            print(f"   Got:      {actual_header}")
            # Try to fix common issues
            if "STOCK NAME" not in actual_header and "STOCK" in actual_header:
                csv_content = csv_content.replace("STOCK,", "STOCK NAME,", 1)
        
        # Parse and re-write CSV with proper quoting to handle commas in values
        import io
        csv_buffer = io.StringIO(csv_content)
        reader = csv.DictReader(csv_buffer)
        rows = list(reader)
        stocks_count = len(rows)
        
        # Get valid fieldnames (filter out None)
        valid_fieldnames = [fn for fn in reader.fieldnames if fn is not None]
        
        # Clean rows: remove None keys and ensure all expected fields exist
        cleaned_rows = []
        valid_chart_types = {"Daily", "Weekly", "Monthly"}
        
        for row in rows:
            # Remove None keys from row
            cleaned_row = {k: v for k, v in row.items() if k is not None}
            
            # Ensure all expected fields exist
            for field in valid_fieldnames:
                if field not in cleaned_row:
                    cleaned_row[field] = ''
            
            # Sanitize CHART TYPE
            chart_type = str(cleaned_row.get('CHART TYPE', '')).strip()
            if chart_type not in valid_chart_types:
                cleaned_row['CHART TYPE'] = 'Daily'
                print(f"   ⚠️  Invalid CHART TYPE '{chart_type}' → defaulting to 'Daily'")
            
            cleaned_rows.append(cleaned_row)
        
        # Save CSV with proper quoting
        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            if cleaned_rows:
                writer = csv.DictWriter(f, fieldnames=valid_fieldnames, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                writer.writerows(cleaned_rows)
        
        # Re-read to validate
        with open(output_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            stocks_count = len(rows)
            
            # Validate required columns
            required_columns = ['DATE', 'TIME', 'STOCK NAME', 'TARGETS', 'STOP LOSS', 'HOLDING PERIOD', 'CALL', 'CHART TYPE']
            if reader.fieldnames:
                missing_cols = [col for col in required_columns if col not in reader.fieldnames]
                if missing_cols:
                    raise ValueError(f"Missing required columns: {', '.join(missing_cols)}")
        
        print(f"✅ Generated CSV with {stocks_count} stock call(s)")
        print(f"   Output: {output_csv}")
        print(f"   Columns: {', '.join(reader.fieldnames) if reader.fieldnames else 'Unknown'}")
        
        return {
            'success': True,
            'output_file': output_csv,
            'stocks_count': stocks_count,
            'error': None
        }
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
