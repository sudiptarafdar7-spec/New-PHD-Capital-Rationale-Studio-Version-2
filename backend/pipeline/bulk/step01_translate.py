"""
Bulk Rationale Step 1: Translate Input Text
Translates bulk-input.txt to English using OpenAI
"""

import os
import openai
from backend.utils.database import get_db_cursor


def get_openai_key():
    """Get OpenAI API key from database"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT key_value FROM api_keys WHERE provider = 'openai'")
        result = cursor.fetchone()
        if result and result['key_value']:
            return result['key_value'].strip()
    return None


def run(job_folder):
    """
    Translate bulk-input.txt to English using OpenAI
    
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
    print("BULK STEP 1: TRANSLATE INPUT TEXT")
    print(f"{'='*60}\n")
    
    try:
        input_file = os.path.join(job_folder, 'bulk-input.txt')
        output_file = os.path.join(job_folder, 'bulk-input-english.txt')
        
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
        
        print(f"📖 Reading input file: {input_file}")
        with open(input_file, 'r', encoding='utf-8') as f:
            input_text = f.read()
        
        print(f"📝 Input text length: {len(input_text)} characters")
        
        if not input_text.strip():
            return {
                'success': False,
                'error': 'Input text is empty'
            }
        
        print("🌐 Translating to English using OpenAI...")
        
        client = openai.OpenAI(api_key=openai_key)
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional translator specializing in financial content. 
Translate the following text to English while:
1. Preserving all stock names, symbols, numbers, and financial terms accurately
2. Maintaining the original structure and formatting (preserve all sections and stock entries)
3. Keeping any dates, times, and price targets exactly as they appear
4. If the text is already in English, return it as-is with minor cleanup
5. Do not add any explanations or commentary - just translate
6. IMPORTANT: Translate ALL content completely - do not skip or truncate any sections
7. If a stock name appears to be gibberish or random characters, keep it as-is"""
                },
                {
                    "role": "user",
                    "content": input_text
                }
            ],
            temperature=0.1,
            max_tokens=16384
        )
        
        translated_text = response.choices[0].message.content.strip()
        
        print(f"✅ Translation complete: {len(translated_text)} characters")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(translated_text)
        
        print(f"💾 Saved translated text to: {output_file}")
        
        print("\n📋 Preview (first 500 chars):")
        print("-" * 40)
        print(translated_text[:500] + "..." if len(translated_text) > 500 else translated_text)
        
        return {
            'success': True,
            'output_file': output_file
        }
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
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
