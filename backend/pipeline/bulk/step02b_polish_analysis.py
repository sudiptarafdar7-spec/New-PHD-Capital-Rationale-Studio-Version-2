"""
Bulk Rationale Step 2b: Polish Analysis
Polishes the ANALYSIS column from bulk-input.csv using OpenAI to create professional text.
Output: bulk-input-analysis.csv
"""

import os
import json
import openai
import pandas as pd
from backend.utils.database import get_db_cursor


def get_openai_key():
    """Get OpenAI API key from database"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'openai'")
        result = cursor.fetchone()
        if result and result['key_value']:
            return result['key_value'].strip()
    return None


def polish_analysis(client, stock_name, original_analysis):
    """
    Polish a single stock's analysis using OpenAI
    
    Args:
        client: OpenAI client
        stock_name: Name of the stock
        original_analysis: Original analysis text
        
    Returns:
        str: Polished analysis text
    """
    prompt = f"""You are a SEBI-registered Research Analyst with 15+ years of experience in Indian equity markets. 
Polish the following stock analysis to make it professional and well-structured.

STOCK NAME: {stock_name}

ORIGINAL ANALYSIS:
{original_analysis}

FORMATTING RULES:
1. Start with "For {stock_name}, ..." 
2. Include entry point, target prices, and stop-loss levels if mentioned for THIS STOCK
3. Include holding period recommendation if mentioned
4. Include risk factors or caveats if mentioned
5. Use ₹ symbol for all prices (e.g., ₹150, ₹1,250)
6. Convert spoken numbers to digits (e.g., "one fifty" → ₹150, "twelve hundred" → ₹1,200)
7. Minimum 100 words
8. Simple, professional English
9. NO first-person pronouns (I, We, Our) - use passive voice or "the view is..."
10. NO speaker names in the analysis

CRITICAL RULES:
- Do NOT change any price values, targets, stop-loss, or numerical data for {stock_name}
- Do NOT invent new information - only polish what is given
- Keep all technical levels and recommendations exactly as stated
- Just restructure and professionalize the language
- **IMPORTANT**: If the original analysis mentions MULTIPLE stocks, extract ONLY the information relevant to {stock_name}. 
  - Remove mentions of other stocks and their specific levels
  - Keep only the targets, stop-loss, and analysis that applies to {stock_name}
  - If the analysis is shared/generic, adapt it to focus on {stock_name} only

EXAMPLE - If original mentions "HFCL target 84-85, stop loss 67.85" and "Punjab and Sind Bank target 38-40":
- For HFCL: Only mention HFCL's target (₹84-85) and stop loss (₹67.85)
- For Punjab and Sind Bank: Only mention its target (₹38-40)

EXAMPLE OUTPUT FORMAT:
For Jamna Auto, the view remains positive even though the momentum has slowed down compared to earlier moves from the ₹70–80 range. The stock looks stronger when compared to Rico Auto, as it has taken solid support around the ₹100 mark. A strict stop-loss should be maintained at ₹94–95, and as long as the stock sustains above this level, the overall outlook remains intact. The key resistance zone is around ₹110–111, and once this level is crossed, the stock has the potential to move further towards ₹125–130 levels. Holding is advisable with disciplined stop-loss management.

Return ONLY the polished analysis text, nothing else."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional financial writer. Polish stock analyses to be professional, clear, and well-structured. Never change numerical values or invent information. Always use ₹ for Indian Rupee prices."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        polished = response.choices[0].message.content.strip()
        
        if polished.startswith('"') and polished.endswith('"'):
            polished = polished[1:-1]
        if polished.startswith("'") and polished.endswith("'"):
            polished = polished[1:-1]
        
        word_count = len(polished.split())
        if word_count < 50:
            print(f"  ⚠️ Polished text too short ({word_count} words), using original")
            return original_analysis
        
        return polished
        
    except Exception as e:
        print(f"  ⚠️ Error polishing: {str(e)}")
        return original_analysis


def run(job_folder):
    """
    Polish analysis column in bulk-input.csv
    
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
    print("BULK STEP 2b: POLISH ANALYSIS")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_file = os.path.join(analysis_folder, 'bulk-input.csv')
        output_file = os.path.join(analysis_folder, 'bulk-input-analysis.csv')
        
        if not os.path.exists(input_file):
            return {
                'success': False,
                'error': f'Input file not found: {input_file}'
            }
        
        openai_key = get_openai_key()
        if not openai_key:
            return {
                'success': False,
                'error': 'OpenAI API key not found. Please add it in Settings → API Keys.'
            }
        
        print(f"📖 Loading CSV: {input_file}")
        df = pd.read_csv(input_file)
        print(f"✅ Loaded {len(df)} stocks")
        
        if 'ANALYSIS' not in df.columns:
            df.columns = df.columns.str.strip().str.upper()
        
        if 'ANALYSIS' not in df.columns:
            return {
                'success': False,
                'error': 'ANALYSIS column not found in bulk-input.csv'
            }
        
        if 'INPUT STOCK' not in df.columns:
            return {
                'success': False,
                'error': 'INPUT STOCK column not found in bulk-input.csv'
            }
        
        client = openai.OpenAI(api_key=openai_key)
        
        print("\n🔄 Polishing analysis for each stock...")
        print("-" * 60)
        
        polished_count = 0
        for idx, row in df.iterrows():
            stock_name = str(row['INPUT STOCK']).strip()
            original_analysis = str(row.get('ANALYSIS', '')).strip()
            
            if not original_analysis or original_analysis.lower() in ['nan', 'none', '']:
                print(f"  ⏭️ {stock_name}: No analysis to polish")
                continue
            
            print(f"  📝 Polishing: {stock_name}...")
            polished = polish_analysis(client, stock_name, original_analysis)
            df.at[idx, 'ANALYSIS'] = polished
            polished_count += 1
            
            word_count = len(polished.split())
            print(f"     ✅ Done ({word_count} words)")
        
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   Total stocks: {len(df)}")
        print(f"   Polished: {polished_count}")
        
        print(f"\n💾 Saving to: {output_file}")
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ Saved polished analysis CSV\n")
        
        return {
            'success': True,
            'output_file': output_file,
            'polished_count': polished_count,
            'total_stocks': len(df)
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
