"""
Premium Step 7: Generate Final Analysis

Uses OpenAI GPT-4 to generate professional investment analysis rationale 
for each stock based on technical and fundamental data.

Input: 
  - analysis/stocks_with_fundamental.csv (from Step 6)
Output: 
  - analysis/stocks_with_analysis.csv
"""

import os
import pandas as pd
from openai import OpenAI
from backend.utils.openai_config import get_model, get_premium_analysis_prompt


def safe_value(value, default="N/A"):
    """Convert value to string, handling None and NaN"""
    if pd.isna(value) or value is None or value == "":
        return default
    try:
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)
    except:
        return default


def generate_analysis_prompt(row):
    """
    Create a detailed prompt for GPT-4o Expert Analyst to generate stock analysis
    
    Args:
        row: DataFrame row with all stock data
        
    Returns:
        str: Formatted prompt for GPT-4o Expert Analyst
    """
    stock_name = safe_value(row.get('STOCK NAME'), 'Unknown Stock')
    call_type = safe_value(row.get('CALL'), 'N/A')
    cmp = safe_value(row.get('CMP'))
    targets = safe_value(row.get('TARGETS'))
    stop_loss = safe_value(row.get('STOP LOSS'))
    
    rsi = safe_value(row.get('RSI'))
    ma20 = safe_value(row.get('MA20'))
    ma50 = safe_value(row.get('MA50'))
    ma100 = safe_value(row.get('MA100'))
    ma200 = safe_value(row.get('MA200'))
    
    pe_ratio = safe_value(row.get('P/E RATIO'))
    pb_ratio = safe_value(row.get('P/B RATIO'))
    roe = safe_value(row.get('ROE (%)'))
    roce = safe_value(row.get('ROCE (%)'))
    debt_equity = safe_value(row.get('DEBT/EQUITY'))
    eps_ttm = safe_value(row.get('EPS (TTM)'))
    eps_growth = safe_value(row.get('EPS GROWTH (YoY %)'))
    revenue_growth = safe_value(row.get('REVENUE GROWTH (YoY %)'))
    dividend_yield = safe_value(row.get('DIVIDEND YIELD (%)'))
    sector = safe_value(row.get('SECTOR'))
    industry = safe_value(row.get('INDUSTRY'))
    
    prompt = f"""**SEBI-Compliant Investment Rationale Generation**

**Stock Profile:**
- Company: {stock_name}
- Sector: {sector} | Industry: {industry}
- Call Type: {call_type}
- CMP: Rs. {cmp}
- Target(s): {targets}
- Stop Loss: Rs. {stop_loss}

**Technical Data:**
| Indicator | Value |
|-----------|-------|
| RSI (14) | {rsi} |
| 20 DMA | Rs. {ma20} |
| 50 DMA | Rs. {ma50} |
| 100 DMA | Rs. {ma100} |
| 200 DMA | Rs. {ma200} |

**Fundamental Data:**
| Metric | Value |
|--------|-------|
| P/E Ratio | {pe_ratio} |
| P/B Ratio | {pb_ratio} |
| ROE | {roe}% |
| ROCE | {roce}% |
| Debt/Equity | {debt_equity} |
| EPS (TTM) | Rs. {eps_ttm} |
| EPS Growth (YoY) | {eps_growth}% |
| Revenue Growth (YoY) | {revenue_growth}% |
| Dividend Yield | {dividend_yield}% |

**Analysis Requirements:**

Generate a professional investment rationale (5-7 sentences) covering:

1. **Technical Assessment** (2 sentences):
   - RSI interpretation: Oversold (<30), Neutral (30-70), Overbought (>70)
   - Price position relative to key moving averages (20/50/100/200 DMA)
   - Key support/resistance levels

2. **Fundamental Evaluation** (2 sentences):
   - Valuation assessment (P/E, P/B vs sector average)
   - Profitability metrics (ROE, ROCE interpretation)
   - Growth trajectory (EPS, Revenue trends)

3. **Investment Thesis** (2-3 sentences):
   - Clear rationale for {call_type} recommendation
   - Target price justification with potential upside
   - Stop-loss rationale and downside risk
   - Key catalysts or risk factors

**Format Guidelines:**
- Use Rs. for all currency values
- Professional, objective tone
- No promotional language
- Data-driven insights
- Standard ASCII characters only
- Maximum 150 words

Generate the analysis:"""
    
    return prompt


def generate_stock_analysis(client, row, model=None):
    """
    Generate analysis for a single stock using OpenAI GPT-4o Expert Analyst
    
    Args:
        client: OpenAI client instance
        row: DataFrame row with stock data
        model: OpenAI model to use (defaults to centralized config)
        
    Returns:
        tuple: (success: bool, analysis: str or error_message: str)
    """
    try:
        if model is None:
            model = get_model()
            
        prompt = generate_analysis_prompt(row)
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": get_premium_analysis_prompt()
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.5,
            max_tokens=600
        )
        
        analysis = response.choices[0].message.content.strip()
        return (True, analysis)
        
    except Exception as e:
        error_msg = f"Error generating analysis: {str(e)}"
        return (False, error_msg)


def run(job_folder, openai_api_key):
    """
    Generate professional analysis rationale for all stocks using OpenAI GPT-4
    
    Args:
        job_folder: Path to job directory
        openai_api_key: OpenAI API key from database
    
    Returns:
        dict: {
            'success': bool,
            'output_file': str,
            'error': str or None
        }
    """
    print("\n" + "=" * 60)
    print("PREMIUM STEP 7: GENERATE ANALYSIS RATIONALE")
    print(f"{'='*60}\n")
    
    try:
        analysis_folder = os.path.join(job_folder, 'analysis')
        input_csv = os.path.join(analysis_folder, 'stocks_with_fundamental.csv')
        output_csv = os.path.join(analysis_folder, 'stocks_with_analysis.csv')
        
        if not os.path.exists(input_csv):
            return {
                'success': False,
                'error': f'Stocks with fundamental data file not found: {input_csv}'
            }
        
        if not openai_api_key:
            return {
                'success': False,
                'error': 'OpenAI API key not found. Please configure it in API Keys settings.'
            }
        
        print("📖 Loading stocks with fundamental data...")
        df = pd.read_csv(input_csv)
        print(f"✅ Loaded {len(df)} stocks\n")
        
        if 'ANALYSIS' not in df.columns:
            df['ANALYSIS'] = ''
        
        print("🤖 Generating AI-powered Analysis using GPT-4o Expert Analyst...")
        print("-" * 60)
        
        client = OpenAI(api_key=openai_api_key)
        
        success_count = 0
        failed_count = 0
        
        for idx, row in df.iterrows():
            try:
                stock_name = row.get('STOCK NAME', 'Unknown')
                call_type = row.get('CALL', 'N/A')
                
                print(f"  [{idx+1}/{len(df)}] {stock_name:30} | Generating {call_type} analysis...")
                
                success, analysis = generate_stock_analysis(client, row)
                
                df.at[idx, 'ANALYSIS'] = analysis
                
                if success:
                    preview = analysis[:80] + "..." if len(analysis) > 80 else analysis
                    print(f"       ✅ {preview}")
                    success_count += 1
                else:
                    print(f"  ❌ {stock_name:30} | {analysis}")
                    failed_count += 1
                
            except Exception as e:
                stock_name = row.get('STOCK NAME', f'Row {idx}')
                error_msg = f"Error generating analysis: {str(e)}"
                df.at[idx, 'ANALYSIS'] = error_msg
                print(f"  ❌ {stock_name:30} | {str(e)}")
                failed_count += 1
        
        print("-" * 60)
        print(f"\n📊 Analysis Generation Summary:")
        print(f"   Total stocks: {len(df)}")
        print(f"   Successfully generated: {success_count}")
        print(f"   Failed: {failed_count}\n")
        
        print(f"💾 Saving analysis to: {output_csv}")
        
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        df.to_csv(output_csv, index=False, encoding='utf-8')
        
        print(f"💾 Saved {len(df)} records to: {output_csv}")
        print(f"✅ Output: analysis/stocks_with_analysis.csv\n")
        
        if failed_count > 0:
            error_msg = f"Analysis generation failed for {failed_count} stock(s). OpenAI API error or quota issue. Check ANALYSIS column for error details."
            print(f"\n❌ STEP FAILED: {error_msg}\n")
            return {
                'success': False,
                'error': error_msg
            }
        
        print(f"✅ All {success_count} stocks analyzed successfully!\n")
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
    
    test_api_key = os.environ.get("OPENAI_API_KEY", "")
    
    result = run(test_folder, test_api_key)
    print(f"\n{'='*60}")
    print(f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    print(f"{'='*60}")
