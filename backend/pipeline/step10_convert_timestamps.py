"""
Step 10: Convert Timestamps

Converts video-relative timestamps (START TIME) to actual clock times by adding
them to the video upload time from the database.

Input: 
  - analysis/mapped_master_file.csv (from Step 9)
  - Upload time and date from jobs table
Output: 
  - analysis/stocks_with_date_time.csv
"""

import os
import pandas as pd
import psycopg2
from datetime import datetime, timedelta


def to_timedelta(t):
    """Convert HH:MM:SS string to timedelta"""
    try:
        parts = [int(x) for x in str(t).split(":")]
        if len(parts) == 3:
            return timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])
        elif len(parts) == 2:
            return timedelta(minutes=parts[0], seconds=parts[1])
        else:
            return timedelta(seconds=parts[0])
    except:
        return timedelta(0)


def get_datetime(job_id):
    """Fetch upload date and time from database"""
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT date, time 
            FROM jobs 
            WHERE id = %s
        """, (job_id,))
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            date = result[0]
            time = result[1]
            return date, time
        else:
            raise ValueError(f"Job {job_id} not found in database")
    
    except Exception as e:
        raise Exception(f"Failed to fetch upload date/time: {str(e)}")


def run(job_folder):
    """
    Convert video timestamps to actual clock times
    
    Args:
        job_folder: Path to job directory
        
    Returns:
        dict: Status, message, and output files
    """
    print("\n" + "="*60)
    print("STEP 10: Convert Timestamps")
    print(f"{'='*60}\n")

    try:
        # Extract job_id from job_folder
        job_id = os.path.basename(job_folder)
        
        # Input/Output paths
        input_csv = os.path.join(job_folder, "analysis", "mapped_master_file.csv")
        output_csv = os.path.join(job_folder, "analysis", "stocks_with_date_time.csv")
        
        # Verify input file exists
        if not os.path.exists(input_csv):
            return {
                'status': 'failed',
                'message': f'Mapped master file not found: {input_csv}'
            }
        
        # Get upload date and time from database
        print(f"🔑 Retrieving upload date/time for job: {job_id}")
        date, time = get_datetime(job_id)
        
        # Format date as YYYY-MM-DD
        if isinstance(date, str):
            base_date_str = date
        else:
            base_date_str = date.strftime("%Y-%m-%d")
        
        # Convert time to datetime object
        if isinstance(time, str):
            base_time = datetime.strptime(time, "%H:%M:%S")
        else:
            # It's already a time object
            base_time = datetime.combine(datetime.today(), time)
        
        print(f"✅ Upload Date: {base_date_str}")
        print(f"✅ Upload Time: {base_time.strftime('%H:%M:%S')}\n")
        
        # Load mapped master file
        print("📖 Loading mapped master file...")
        df = pd.read_csv(input_csv)
        print(f"✅ Loaded {len(df)} stocks\n")
        
        # Convert START TIME to actual clock time
        print("🕐 Converting timestamps to actual clock times...")
        print("-" * 60)
        
        new_start_times = []
        for idx, t in enumerate(df["START TIME"]):
            # Video-relative offset (e.g., "00:05:23" means 5 min 23 sec into video)
            offset = to_timedelta(t)
            
            # Add offset to base time
            actual_time = (base_time + offset).strftime("%H:%M:00")  # Round seconds to 00
            new_start_times.append(actual_time)
            
            if idx < 5:  # Show first 5 conversions
                stock_symbol = df.iloc[idx].get("STOCK SYMBOL", "")
                print(f"  {stock_symbol:15} | Video: {t:8} → Actual: {actual_time}")
        
        if len(df) > 5:
            print(f"  ... and {len(df) - 5} more")
        
        print("-" * 60)
        
        # Update DataFrame
        df["START TIME"] = new_start_times
        df["DATE"] = base_date_str
        
        # Reorder columns
        final_cols = [
            "STOCK NAME", "STOCK SYMBOL", "LISTED NAME", "SHORT NAME",
            "SECURITY ID", "EXCHANGE", "INSTRUMENT", "SEGMENT",
            "START TIME", "DATE"
        ]
        
        # Only include columns that exist
        final_cols = [col for col in final_cols if col in df.columns]
        df = df.reindex(columns=final_cols)
        
        # Save output
        print(f"\n💾 Saving timestamped data to: {output_csv}")
        
        # Ensure analysis directory exists
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)
        
        df.to_csv(output_csv, index=False)
        
        print(f"✅ Saved {len(df)} records")
        print(f"✅ Output: analysis/stocks_with_date_time.csv\n")
        
        return {
            'status': 'success',
            'message': f'Converted {len(df)} timestamps to actual clock times',
            'output_files': ['analysis/stocks_with_date_time.csv']
        }
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'failed',
            'message': f'Timestamp conversion failed: {str(e)}'
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
