# Premium Rationale Pipeline - Steps Input/Output Documentation

## Overview
The Premium Rationale pipeline processes manually entered stock calls through 8 sequential steps to generate a professional SEBI-compliant PDF report.

---

## Step 1: Generate CSV from Input Text

**Purpose**: Parse raw stock calls text and generate structured CSV file using OpenAI GPT-4

**Inputs**:
- `job_folder`: Path to job directory
- `input_text`: Raw text with stock calls from `input.txt` file (includes DATE, TIME, PLATFORM, CHANNEL, STOCK CALLS)
- `openai_api_key`: OpenAI API key from database

**Outputs**:
- **CSV File**: `analysis/premium_rationale_stocks.csv`
- **Columns**: DATE, TIME, STOCK NAME, TARGETS, STOP LOSS, HOLDING PERIOD, CALL, CHART TYPE
- **CHART TYPE Values**: Strictly one of: "Daily", "Weekly", "Monthly" (auto-sanitized to "Daily" if invalid)
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to generated CSV
  - `stocks_count`: Number of stock calls parsed
  - `error`: Error message if failed

**Example Output CSV**:
```csv
DATE,TIME,STOCK NAME,TARGETS,STOP LOSS,HOLDING PERIOD,CALL,CHART TYPE
2025-11-11,14:30:00,RELIANCE,"2500, 2550, 2600",2400,Short Term,BUY,Daily
2025-11-11,14:30:00,TATASTEEL,"140, 135",150,Intraday,SELL,Daily
```

---

## Step 2: Map Stock Symbols (Master File Matching)

**Purpose**: Match stock names to master file using fuzzy matching to get exchange symbols and security IDs

**Inputs**:
- `job_folder`: Path to job directory
- Master file path fetched internally from `uploaded_files` table (file_type = 'master_csv')

**Matching Logic**:
1. Filter master data → only rows where `SEM_INSTRUMENT_NAME == "EQUITY"`
2. Match `STOCK NAME` sequentially by:
   - Primary: `SEM_CUSTOM_SYMBOL` (exact → fuzzy >= 85%)
   - Secondary: `SEM_TRADING_SYMBOL` (exact → fuzzy >= 85%)
   - Tertiary: `SM_SYMBOL_NAME` (exact → fuzzy >= 85%)
3. If both NSE and BSE found → Prefer NSE (`SEM_EXM_EXCH_ID == "NSE"`)

**Processing**:
- Reads `analysis/premium_rationale_stocks.csv` (from Step 1)
- Normalizes text fields for matching (removes special chars)
- Uses rapidfuzz with 85% similarity threshold
- Maps master columns to output columns

**Outputs**:
- **CSV File**: `analysis/mapped_master_file.csv`
- **New Columns Added**:
  - `STOCK SYMBOL` ← `SEM_TRADING_SYMBOL`
  - `LISTED NAME` ← `SM_SYMBOL_NAME`
  - `SHORT NAME` ← `SEM_CUSTOM_SYMBOL`
  - `SECURITY ID` ← `SEM_SMST_SECURITY_ID`
  - `EXCHANGE` ← `SEM_EXM_EXCH_ID`
  - `INSTRUMENT` ← `SEM_INSTRUMENT_NAME`
- **Return Data**:
  - `status`: 'success' or 'failed'
  - `message`: Summary message
  - `output_files`: ['analysis/mapped_master_file.csv']

---

## Step 3: Fetch CMP (Current Market Price)

**Purpose**: Fetch current market price for each stock using Dhan Intraday Charts API

**Inputs**:
- `job_folder`: Path to job directory
- `dhan_api_key`: Dhan API access token from database

**API Details**:
- **Endpoint**: `https://api.dhan.co/v2/charts/intraday`
- **Method**: POST
- **Time Window**: Call time + 10 minutes
- **Interval**: 5-minute candles
- **Exchange Segment**: `{EXCHANGE}_EQ` (e.g., NSE_EQ, BSE_EQ)

**Processing**:
- Reads `analysis/mapped_master_file.csv` (from Step 2)
- Parses DATE and TIME to create datetime
- For each stock:
  - Fetches intraday data from Dhan API using SECURITY ID and EXCHANGE
  - Extracts closing price from first candle
  - Handles rate limiting with 1.5s delay between requests
- Skips stocks with missing SECURITY ID

**Outputs**:
- **CSV File**: `analysis/stocks_with_cmp.csv`
- **New Column Added**: CMP (Current Market Price in ₹)
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to CSV with CMP
  - `error`: Error message if failed

---

## Step 4: Generate Stock Charts

**Purpose**: Generate premium candlestick charts with technical indicators using Dhan API

**Inputs**:
- `job_folder`: Path to job directory
- `dhan_api_key`: Dhan API access token from database

**API Details**:
- **Historical Data**: `/charts/historical` (last 8 months of daily data)
- **Intraday Data**: `/charts/intraday` (1-minute candles from market open to call time)
- **Exchange Segment**: `{EXCHANGE}_EQ` (e.g., NSE_EQ, BSE_EQ)

**Chart Features**:
- **Candlesticks**: OHLCV data with green (up) and red (down) candles
- **Moving Averages**: MA20, MA50, MA100, MA200 (color-coded lines)
- **RSI Indicator**: RSI(14) with 30/70 overbought/oversold levels
- **Volume Panel**: Bar chart showing trading volume
- **CMP Line**: Horizontal dotted line showing Current Market Price
- **Time Resolution**: Determined by HOLDING PERIOD (defaults to Daily)

**Processing**:
- Reads `analysis/stocks_with_cmp.csv` (from Step 3)
- For each stock:
  - Fetches 8 months of historical daily data
  - Fetches intraday 1-minute data (market open → call time)
  - Resamples data to chart timeframe (Daily)
  - Adds technical indicators (MA20/50/100/200, RSI14)
  - Generates premium chart with mplfinance
  - Saves as PNG image in `charts/` folder
- Rate limiting: 1.5s delay between requests

**Outputs**:
- **CSV File**: `analysis/stocks_with_chart.csv`
- **New Column Added**:
  - `CHART PATH` ← Relative path to chart image
- **CHART TYPE Usage**: Uses value from CSV (from Step 1), defaults to "Daily" if empty/invalid
- **Chart Files**: `charts/{SECURITY_ID}_{CHART_TYPE}_{DATE}_{TIME}.png`
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to CSV with chart paths
  - `error`: Error message if failed

---

## Step 5: Fetch Technical Indicators

**Purpose**: Extract technical indicators (RSI, MA20/50/100/200) from historical data and add to CSV

**Inputs**:
- `job_folder`: Path to job directory
- `dhan_api_key`: Dhan API access token from database

**API Details**:
- **Endpoint**: `https://api.dhan.co/v2/charts/historical`
- **Method**: POST
- **Data Range**: 11 months of daily data (≈230 trading days, sufficient for MA200)
- **Timeframe**: Daily candles

**Processing**:
- Reads `analysis/stocks_with_chart.csv` (from Step 4)
- For each stock:
  - Fetches 11 months of historical daily close prices from Dhan API
  - Computes RSI(14) using standard momentum formula
  - Computes Simple Moving Averages: MA20, MA50, MA100, MA200
  - Extracts latest values (as of most recent candle)
  - Appends indicator values to CSV row
- Rate limiting: 1.5s delay between requests

**Outputs**:
- **CSV File**: `analysis/stocks_with_technical.csv`
- **New Columns Added**:
  - `RSI` ← Relative Strength Index (14-period)
  - `MA20` ← 20-day Simple Moving Average
  - `MA50` ← 50-day Simple Moving Average
  - `MA100` ← 100-day Simple Moving Average
  - `MA200` ← 200-day Simple Moving Average
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to CSV with technical indicators
  - `error`: Error message if failed

**Technical Indicators**:
- **RSI(14)**: Measures momentum, range 0-100 (>70 = overbought, <30 = oversold)
- **MA20**: Short-term trend (20 trading days ≈ 1 month)
- **MA50**: Medium-term trend (50 trading days ≈ 2.5 months)
- **MA100**: Medium-long term trend (100 trading days ≈ 5 months)
- **MA200**: Long-term trend (200 trading days ≈ 10 months)

**Note**: Uses same Dhan API data source as Step 4 for consistency

---

## Step 6: Fetch Fundamental Data

**Purpose**: Fetch comprehensive fundamental analysis data from Yahoo Finance

**Inputs**:
- `job_folder`: Path to job directory
- Uses yfinance library (no API key required)

**Symbol Handling**:
- Reads `STOCK SYMBOL` and `EXCHANGE` from CSV
- Automatically adds suffix: `.NS` for NSE, `.BO` for BSE
- Example: `RELIANCE` + `NSE` → `RELIANCE.NS` for Yahoo Finance

**Processing**:
- Reads `analysis/stocks_with_technical.csv` (from Step 5)
- For each stock:
  - Converts symbol to Yahoo Finance format (adds .NS/.BO)
  - Fetches fundamental data using yfinance library
  - Extracts 13 key metrics from stock info
  - Appends fundamental values to CSV row
- Rate limiting: 0.5s delay between requests

**Outputs**:
- **CSV File**: `analysis/stocks_with_fundamental.csv`
- **New Columns Added**:
  - `COMPANY NAME` ← Official company name
  - `MARKET CAP` ← Market capitalization
  - `P/E RATIO` ← Price to Earnings (trailing)
  - `P/B RATIO` ← Price to Book
  - `ROE (%)` ← Return on Equity (percentage)
  - `ROCE (%)` ← Return on Assets (proxy for ROCE)
  - `DEBT/EQUITY` ← Debt to Equity Ratio
  - `EPS (TTM)` ← Earnings Per Share (trailing twelve months)
  - `EPS GROWTH (YoY %)` ← Year-over-Year EPS growth
  - `REVENUE GROWTH (YoY %)` ← Year-over-Year revenue growth
  - `DIVIDEND YIELD (%)` ← Dividend yield percentage
  - `SECTOR` ← Business sector
  - `INDUSTRY` ← Industry classification
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to CSV with fundamental data
  - `error`: Error message if failed

**Note**: 
- Yahoo Finance doesn't provide ROCE directly, so `returnOnAssets` (ROA) is used as a proxy
- All percentage values are automatically converted (multiplied by 100)
- Missing data is handled gracefully with `None` values

---

## Step 7: Generate Analysis Rationale

**Purpose**: Generate professional investment analysis using OpenAI GPT-4o

**Inputs**:
- `job_folder`: Path to job directory
- `openai_api_key`: OpenAI API key retrieved from database (api_keys table)

**Processing**:
- Reads `analysis/stocks_with_fundamental.csv` (from Step 6)
- For each stock:
  - Constructs comprehensive prompt with all technical & fundamental data
  - Sends to OpenAI GPT-4o with specialized system prompt
  - Receives 5-7 sentence professional analysis
  - Appends to ANALYSIS column
- Uses GPT-4o model with temperature=0.7, max_tokens=500

**Prompt Structure**:
Each prompt includes:
- **Stock Info**: Company, Sector, Industry, Call Type, CMP, Targets, Stop Loss
- **Technical Indicators**: RSI, MA20, MA50, MA100, MA200
- **Fundamental Metrics**: P/E, P/B, ROE, ROCE, Debt/Equity, EPS (TTM), EPS Growth, Revenue Growth, Dividend Yield
- **Task Instructions**: Generate SEBI-compliant rationale covering technical setup, fundamentals, call justification, target/SL reasoning, and risks

**Outputs**:
- **CSV File**: `analysis/stocks_with_analysis.csv`
- **New Column Added**: 
  - `ANALYSIS` ← AI-generated professional investment rationale (5-7 sentences)
- **Return Data**:
  - `success`: bool
  - `output_file`: Path to CSV with analysis
  - `error`: Error message if failed

**Analysis Quality Features**:
- Professional Indian equity market terminology (Rs., Nifty, BSE/NSE)
- Data-driven insights combining technicals + fundamentals
- SEBI-compliant language
- Objective and balanced tone
- Uses standard ASCII characters for better compatibility
- Covers: Technical setup, Fundamental strength, Call justification, Target/SL reasoning, Risk considerations

**Error Handling**:
- Missing data handled gracefully with "N/A" values
- Failed analyses logged with error messages in ANALYSIS column
- Requires OpenAI API key to be configured in system

---

## Step 8: Generate PDF Report

**Purpose**: Create final professional PDF report with premium burgundy design

**Inputs**:
- `job_folder`: Path to job directory
- Auto-fetches configuration from database (pdf_template, channels, uploaded_files tables)

**Color Scheme** (Premium differentiation):
- **Primary**: Burgundy (#8B1538) - Distinguishes from Media Rationale's blue
- **Accent**: Gold (#D4AF37)
- Professional, premium aesthetic

**Database Integration**:
- Extracts job_id from folder path
- Fetches: channel name, channel logo, platform link, company details, disclaimers
- Loads custom fonts if available, fallback to Helvetica
- Creates round channel logo for footer

**Processing**:
- Reads `analysis/stocks_with_analysis.csv` (from Step 7)
- Generates PDF filename: `{channel-name}-Premium-{YYYYMMDD}-{HHMMSS}.pdf`
- For each stock:
  - Creates dedicated page with Positional chip + date/time
  - Adds stock title (LISTED NAME + SYMBOL)
  - Embeds chart image from charts folder
  - Renders stock details table (7 columns)
  - Displays rationale analysis
- Appends disclaimer/disclosure/company data pages
- Uses custom letterhead header (burgundy) on first page
- Adds burgundy stripe header on subsequent pages
- Renders footer with channel logo, name, and platform link

**Outputs**:
- **PDF File**: `pdf/{channel-name}-Premium-{date}-{time}.pdf`
- **Return Data**:
  - `success`: bool
  - `output_file`: Full path to generated PDF
  - `error`: Error message if failed

**PDF Structure**:
1. **First Page Header**: Burgundy letterhead with company name, registration details, company logo
2. **For Each Stock** (one page per stock):
   - Positional chip (burgundy) + Date/Time (right-aligned)
   - Stock title: Listed Name (Symbol)
   - Full-width chart image
   - **Stock Details Table** (burgundy header):
     - Script | Sector | Targets | Stop Loss | Holding | Call | CMP
   - **Rationale Section** (burgundy heading):
     - "Rationale - Our General View"
     - AI-generated analysis paragraph (from Step 7)
3. **Final Pages**:
   - Disclaimer (if configured)
   - Disclosure (if configured)
   - Additional Information (company_data if configured)
4. **All Pages Footer**:
   - Left: Round channel logo + channel name + "Premium Analysis"
   - Center: Page number
   - Right: Platform link

**Special Features**:
- **Encoding Safety**: Uses `safe_str()` helper to avoid special characters (no â‚¹ issues)
- **Smart Logo Handling**: Creates circular channel logo from square images
- **HTML Parsing**: Strips HTML from registration_details for clean rendering
- **Dynamic Wrapping**: Registration text wraps across multiple lines if needed
- **Fallback Fonts**: Uses custom fonts if available, otherwise Helvetica
- **Premium Typography**: 10.5pt body, 15.5pt headings, justified alignment
- **Professional Tables**: Alternating row colors, centered alignment, grid borders

---

## Data Flow Summary

```
User Input Text
    ↓
Step 1: premium_rationale_stocks.csv (DATE, TIME, STOCK NAME, TARGETS, STOP LOSS, HOLDING PERIOD, CALL)
    ↓
Step 2: mapped_master_file.csv (+STOCK SYMBOL, LISTED NAME, SHORT NAME, SECURITY ID, EXCHANGE, INSTRUMENT)
    ↓
Step 3: stocks_with_cmp.csv (+CMP)
    ↓
Step 4: stocks_with_chart.csv (+CHART PATH) + chart images in charts/
    ↓
Step 5: stocks_with_technical.csv (+RSI, MA20, MA50, MA100, MA200)
    ↓
Step 6: stocks_with_fundamental.csv (+ROE, ROCE, P/E, P/B, Debt/Equity, EPS Growth)
    ↓
Step 7: stocks_with_analysis.csv (+ANALYSIS)
    ↓
Step 8: premium_rationale.pdf
```

---

## CSV Review Point

After **Step 7** completes, the pipeline pauses with status `awaiting_csv_review`.

**User Actions**:
1. Download `stocks_with_analysis.csv`
2. Review/edit stock data and analysis
3. Upload edited CSV (optional)
4. Continue to PDF generation (Step 8)

**Purpose**: Allows manual verification and correction before final PDF generation.

---

## External Dependencies

| Step | API/Service | Purpose |
|------|-------------|---------|
| 1 | OpenAI GPT-4 | Parse stock calls from text |
| 2 | Master File (CSV) | Stock symbol mapping |
| 3 | Dhan Quote API | Fetch current market prices |
| 4 | Dhan Chart API | Generate candlestick charts |
| 5 | Dhan Historical API | Fetch price data for indicators |
| 6 | Yahoo Finance | Fetch fundamental metrics |
| 7 | OpenAI GPT-4 | Generate analysis rationale |
| 8 | ReportLab | PDF generation |

---

## Error Handling

Each step returns a result dictionary with:
- `success`: True/False
- `error`: Error message if failed
- Additional metadata (file paths, counts, etc.)

If any step fails:
- Job status set to `failed`
- Step status set to `failed`
- Error message stored in `job_steps.error_message`
- Pipeline stops execution
- User can restart from failed step using restart button (↻)

---

## Notes

- All CSV files use UTF-8 encoding
- Chart images are PNG format (1200x800px recommended)
- Analysis text is plain text (no HTML/markdown)
- PDF uses custom fonts and styling from template config
- All file paths are relative to job folder
