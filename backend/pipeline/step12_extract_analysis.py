"""
Step 12: Extract Analysis

Uses OpenAI GPT-4o to extract detailed stock analysis given by Pradip
from the filtered transcription.

Input: 
  - analysis/detected_speakers.txt (from Step 6)
  - transcripts/filtered_transcription.txt (from Step 7)
  - analysis/stocks_with_cmp.csv (from Step 11)
  - OpenAI API key from database
Output: 
  - analysis/stocks_with_analysis.csv
"""

import os
import json
import pandas as pd
import psycopg2
from openai import OpenAI
from backend.utils.openai_config import get_model, get_analysis_extraction_prompt


def get_openai_api_key():
    """Fetch OpenAI API key from database"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()

        cursor.execute("""
            SELECT key_value 
            FROM api_keys 
            WHERE LOWER(provider) = 'openai'
            LIMIT 1
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            return result[0]
        else:
            raise ValueError(
                "OpenAI API key not found in database. Please add it in API Keys settings."
            )

    except Exception as e:
        raise Exception(f"Failed to fetch OpenAI API key: {str(e)}")


def run(job_folder):
    """
    Extract Pradip's stock analysis using GPT-4o
    
    Args:
        job_folder: Path to job directory
        
    Returns:
        dict: Status, message, and output files
    """
    print("\n" + "=" * 60)
    print("STEP 12: Extract Analysis")
    print(f"{'='*60}\n")

    try:
        # Input paths
        speakers_file = os.path.join(job_folder, "analysis",
                                     "detected_speakers.txt")
        transcript_file = os.path.join(job_folder, "transcripts",
                                       "filtered_transcription.txt")
        stocks_csv = os.path.join(job_folder, "analysis",
                                  "stocks_with_cmp.csv")
        output_csv = os.path.join(job_folder, "analysis",
                                  "stocks_with_analysis.csv")

        # Verify input files exist
        if not os.path.exists(speakers_file):
            return {
                'status': 'failed',
                'message': f'Detected speakers file not found: {speakers_file}'
            }

        if not os.path.exists(transcript_file):
            return {
                'status':
                'failed',
                'message':
                f'Filtered transcription file not found: {transcript_file}'
            }

        if not os.path.exists(stocks_csv):
            return {
                'status': 'failed',
                'message': f'Stocks with CMP file not found: {stocks_csv}'
            }

        # Load detected speakers
        print("👥 Loading detected speakers...")
        with open(speakers_file, "r", encoding="utf-8") as f:
            detected = f.read().strip().splitlines()

        anchor_speaker = detected[0].split(":")[1].strip()
        pradip_speaker = detected[1].split(":")[1].strip()
        print(f"✅ Anchor = {anchor_speaker}")
        print(f"✅ Pradip = {pradip_speaker}\n")

        # Load filtered transcript
        print("📖 Loading filtered transcription...")
        with open(transcript_file, "r", encoding="utf-8") as f:
            convo_text = f.read()
        print(f"✅ Loaded transcript ({len(convo_text)} characters)\n")

        # Load stocks
        print("📊 Loading stocks with CMP...")
        stocks_df = pd.read_csv(stocks_csv)
        stock_names = stocks_df["STOCK NAME"].tolist()
        stock_cmp = stocks_df["CMP"].tolist()
        print(f"✅ Loaded {len(stock_names)} stocks\n")

        # Get OpenAI API key
        print("🔑 Retrieving OpenAI API key from database...")
        api_key = get_openai_api_key()
        client = OpenAI(api_key=api_key)
        print(f"✅ OpenAI API key found\n")

        # Build GPT prompt with Expert Financial Analyst persona
        print("🤖 Building Expert Financial Analyst prompt...")
        prompt = f"""**Investment Rationale Extraction Task**

**Analyst Speaking:** {pradip_speaker}
**Stocks to Analyze:** {', '.join(stock_names)}
**Current Market Prices:** {', '.join([f'{name} = ₹{cmp}' for name, cmp in zip(stock_names, stock_cmp)])}

**Transcript:**
{convo_text}

**Extraction Guidelines:**

1. **Content Source:** Extract ONLY {pradip_speaker}'s analysis. Ignore other speakers.

2. **Analysis Format:** For each stock, provide:
   - Start with "For [STOCK NAME], ..."
   - Technical view (support, resistance, chart patterns)
   - Entry point, target prices, and stop-loss levels
   - Holding period recommendation
   - Risk factors or caveats

3. **Price Formatting:**
   - Use ₹ symbol for all prices
   - Convert spoken numbers to digits (e.g., "one fifty" → ₹150)
   - Validate prices against CMP (fix transcription errors if targets/stop-loss seem unrealistic)

4. **Chart Type Classification:**
   - "Daily" for short-term/intraday views
   - "Weekly" for swing/medium-term views  
   - "Monthly" for positional/long-term views
   - Default to "Daily" if not specified

5. **Quality Standards:**
   - Minimum 100 words per stock analysis
   - Simple, professional English
   - No first-person pronouns (I, We)
   - No speaker names in the analysis text
   - Keep only the FINAL/latest version if revised

**Example Output Format:**
For Jamna Auto, the view remains positive even though the momentum has slowed down compared to earlier moves from the ₹70–80 range. The stock looks stronger when compared to Rico Auto, as it has taken solid support around the ₹100 mark. A strict stop-loss should be maintained at ₹94–95, and as long as the stock sustains above this level, the overall outlook remains intact. The key resistance zone is around ₹110–111, and once this level is crossed, the stock has the potential to move further towards ₹125–130 levels. Holding is advisable with disciplined stop-loss management.

**Output Format (JSON only):**
{{
  "STOCK NAME": {{"chart_type": "Daily/Weekly/Monthly", "analysis": "detailed analysis text..."}}
}}
"""

        print("✅ Expert prompt built\n")

        # Call GPT-4o with Expert Financial Analyst system prompt
        print("🚀 Calling OpenAI GPT-4o Expert Analyst API...")
        print("⏳ This may take 30-60 seconds...\n")

        response = client.chat.completions.create(
            model=get_model(),
            messages=[
                {
                    "role": "system",
                    "content": get_analysis_extraction_prompt()
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=4000)

        content = response.choices[0].message.content.strip()
        print("✅ Received response from GPT-4o\n")

        # Parse JSON response
        print("📝 Parsing analysis data...")

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing error: {str(e)}")
            print(f"Response content:\n{content[:500]}...")
            return {
                'status': 'failed',
                'message': f'Failed to parse GPT response as JSON: {str(e)}'
            }

        print(f"✅ Parsed analysis for {len(data)} stocks\n")

        # Add columns to dataframe
        print("📊 Adding CHART TYPE and ANALYSIS columns...")
        chart_types = []
        analyses = []

        for stock in stocks_df["STOCK NAME"]:
            if stock in data:
                chart_types.append(data[stock].get("chart_type", "Daily"))
                analysis = data[stock].get("analysis",
                                           "").replace("\n",
                                                       " ").replace("|", " ")
                analyses.append(analysis)
                print(
                    f"  ✅ {stock:20} | Chart: {data[stock].get('chart_type', 'Daily')}"
                )
            else:
                chart_types.append("Daily")
                analyses.append("")
                print(f"  ⚠️ {stock:20} | No analysis found")

        stocks_df["CHART TYPE"] = chart_types
        stocks_df["ANALYSIS"] = analyses

        print()

        # Save output with UTF-8 BOM for Excel compatibility
        print(f"💾 Saving analysis to: {output_csv}")

        # Ensure analysis directory exists
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)

        stocks_df.to_csv(output_csv, index=False, encoding="utf-8-sig")

        print(f"✅ Saved {len(stocks_df)} records with analysis")
        print(f"✅ Output: analysis/stocks_with_analysis.csv\n")

        return {
            'status': 'success',
            'message':
            f'Extracted analysis for {len(data)} of {len(stock_names)} stocks using GPT-4o',
            'output_files': ['analysis/stocks_with_analysis.csv']
        }

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Analysis extraction failed: {str(e)}'
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
