import google.generativeai as genai
import pandas as pd
import re
import time
from typing import List, Dict, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

class FastCNOParser:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        self.translation_cache = {}
        self.lock = threading.Lock()
    
    def clean_and_merge_lines(self, text: str) -> List[str]:
        """Pre-process text to merge multi-line titles"""
        lines = text.split('\n')
        merged_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and headers
            if not line or 'Clasificador Nacional' in line or 'INDEC' in line or 'Versión 2017' in line:
                i += 1
                continue
            
            # Check if this is a code line (starts with number or *)
            is_code_line = (
                re.match(r'^\d{1,2}(?:\.\d+)*\s+', line) or 
                line.startswith('*')
            )
            
            if is_code_line:
                # This is a category or occupation line
                # Check if title continues on next lines
                current_line = line
                j = i + 1
                
                # Look ahead for continuation lines
                while j < len(lines):
                    next_line = lines[j].strip()
                    
                    # Stop if we hit another code line, empty line, or clear section break
                    if (not next_line or 
                        re.match(r'^\d{1,2}(?:\.\d+)*\s+', next_line) or 
                        next_line.startswith('*') or
                        'Clasificador Nacional' in next_line or
                        next_line.startswith('INDEC')):
                        break
                    
                    # This is a continuation line
                    current_line += ' ' + next_line
                    j += 1
                
                merged_lines.append(current_line)
                i = j
            else:
                i += 1
        
        return merged_lines
        
    def extract_hierarchy(self, text: str) -> Tuple[List[Dict], List]:
        """Extract complete CNO hierarchy with proper coding"""
        # Pre-process to merge multi-line titles
        lines = self.clean_and_merge_lines(text)
        
        current_major = {'code': '', 'title_es': '', 'title_en': ''}
        current_submajor = {'code': '', 'title_es': '', 'title_en': ''}
        current_minor = {'code': '', 'title_es': '', 'title_en': ''}
        current_unit = {'code': '', 'title_es': '', 'title_en': ''}
        
        unit_counters = defaultdict(int)
        occupation_counters = defaultdict(int)
        
        data = []
        items_to_translate = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # MAJOR CATEGORY: "92 OCUPACIONES DE LA..."
            major_match = re.match(r'^(\d{1,2})\s+(.+)$', line)
            if major_match and len(major_match.group(1)) <= 2 and '.' not in major_match.group(1):
                code = major_match.group(1).zfill(2)
                title = major_match.group(2).strip()
                
                # Major categories are typically all caps or very long
                if len(title) > 20 or title.isupper():
                    current_major = {'code': code, 'title_es': title, 'title_en': ''}
                    items_to_translate.append(('major', len(items_to_translate), title))
                    print(f"Found major: {code} - {title[:80]}...")
                    continue
            
            # SUB-MAJOR CATEGORY: "92.0 Trabajadores de..."
            submajor_match = re.match(r'^(\d{1,2}\.\d)\s+(.+)$', line)
            if submajor_match and not line.startswith('*'):
                code = submajor_match.group(1)
                title = submajor_match.group(2).strip()
                current_submajor = {'code': code, 'title_es': title, 'title_en': ''}
                items_to_translate.append(('submajor', len(items_to_translate), title))
                print(f"Found submajor: {code} - {title[:80]}...")
                continue
            
            # MINOR CATEGORY: "92.0.0 Trabajadores de..."
            minor_match = re.match(r'^(\d{1,2}\.\d\.\d)\s+(.+)$', line)
            if minor_match and not line.startswith('*'):
                code = minor_match.group(1)
                title = minor_match.group(2).strip()
                current_minor = {'code': code, 'title_es': title, 'title_en': ''}
                unit_counters[code] = 0
                items_to_translate.append(('minor', len(items_to_translate), title))
                print(f"Found minor: {code} - {title[:80]}...")
                continue
            
            # UNIT GROUP: "92.0.0.1 Calificación..."
            unit_match = re.match(r'^(\d{1,2}\.\d\.\d\.\d+)\s+(.+)$', line)
            if unit_match and not line.startswith('*'):
                original_code = unit_match.group(1)
                title = unit_match.group(2).strip()
                
                unit_counters[current_minor['code']] += 1
                unique_unit_code = f"{current_minor['code']}.{unit_counters[current_minor['code']]:02d}"
                
                current_unit = {
                    'original_code': original_code,
                    'code': unique_unit_code,
                    'title_es': title,
                    'title_en': ''
                }
                
                occupation_counters[unique_unit_code] = 0
                items_to_translate.append(('unit', len(items_to_translate), title))
                continue
            
            # OCCUPATION: "* administrador de sistemas"
            if line.startswith('*'):
                occupation = line.lstrip('* ').strip()
                if occupation and current_unit['code']:
                    occupation_counters[current_unit['code']] += 1
                    occ_code = f"{current_unit['code']}.{occupation_counters[current_unit['code']]:03d}"
                    
                    data.append({
                        'major_code': current_major['code'],
                        'major_title_es': current_major['title_es'],
                        'major_title_en': '',
                        'submajor_code': current_submajor['code'],
                        'submajor_title_es': current_submajor['title_es'],
                        'submajor_title_en': '',
                        'minor_code': current_minor['code'],
                        'minor_title_es': current_minor['title_es'],
                        'minor_title_en': '',
                        'unit_code': current_unit['code'],
                        'unit_title_es': current_unit['title_es'],
                        'unit_title_en': '',
                        'occupation_code': occ_code,
                        'occupation_es': occupation,
                        'occupation_en': ''
                    })
        
        return data, items_to_translate
    
    def translate_batch(self, texts: List[str], batch_id: int = 0) -> List[str]:
        """Translate texts in a single batch - thread-safe"""
        if not texts:
            return []
        
        uncached_texts = []
        uncached_indices = []
        results = [''] * len(texts)
        
        with self.lock:
            for i, text in enumerate(texts):
                if text in self.translation_cache:
                    results[i] = self.translation_cache[text]
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)
        
        if not uncached_texts:
            return results
        
        numbered_texts = '\n'.join([f"{j+1}. {text}" for j, text in enumerate(uncached_texts)])
        
        prompt = f"""Translate the following Spanish occupational category names and job titles to English.
These are from Argentina's National Occupational Classification (CNO).
Maintain professional terminology and be precise. Keep the full meaning and length.
Provide ONLY the translations, one per line, in the same order, with the numbering.

{numbered_texts}"""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                translations = response.text.strip().split('\n')
                
                cleaned = []
                for trans in translations:
                    clean = re.sub(r'^\d+\.\s*', '', trans).strip()
                    cleaned.append(clean)
                
                with self.lock:
                    for i, trans in zip(uncached_indices, cleaned):
                        self.translation_cache[texts[i]] = trans
                        results[i] = trans
                
                print(f"✓ Batch {batch_id} complete ({len(uncached_texts)} translations)")
                return results
                
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠ Batch {batch_id} failed (attempt {attempt+1}/{max_retries}), retrying...")
                    time.sleep(2 ** attempt)
                else:
                    print(f"✗ Batch {batch_id} failed: {e}")
                    return results
    
    def translate_parallel(self, texts: List[str], batch_size: int = 100, max_workers: int = 10) -> List[str]:
        """Translate texts in parallel using thread pool"""
        if not texts:
            return []
        
        batches = [texts[i:i+batch_size] for i in range(0, len(texts), batch_size)]
        all_translations = [''] * len(texts)
        
        print(f"Translating {len(texts)} items in {len(batches)} batches using {max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(self.translate_batch, batch, i): (i, batch) 
                for i, batch in enumerate(batches)
            }
            
            completed = 0
            for future in as_completed(future_to_batch):
                batch_id, batch = future_to_batch[future]
                try:
                    translations = future.result()
                    start_idx = batch_id * batch_size
                    for i, trans in enumerate(translations):
                        all_translations[start_idx + i] = trans
                    
                    completed += 1
                    print(f"Progress: {completed}/{len(batches)} batches complete")
                    
                except Exception as e:
                    print(f"Error in batch {batch_id}: {e}")
        
        return all_translations
    
    def process_document(self, document_text: str, batch_size: int = 100, max_workers: int = 10) -> pd.DataFrame:
        """Main processing function with parallel translation"""
        print("="*80)
        print("EXTRACTING HIERARCHY")
        print("="*80)
        
        occupations, items_to_translate = self.extract_hierarchy(document_text)
        print(f"\n✓ Found {len(occupations)} occupations")
        print(f"✓ Found {len(items_to_translate)} category items")
        
        print("\n" + "="*80)
        print("TRANSLATING CATEGORIES")
        print("="*80)
        
        category_texts = [item[2] for item in items_to_translate]
        category_translations = self.translate_parallel(category_texts, batch_size=50, max_workers=max_workers)
        
        translation_map = {}
        for (cat_type, idx, original), translation in zip(items_to_translate, category_translations):
            translation_map[(cat_type, original)] = translation
        
        print("\n" + "="*80)
        print("TRANSLATING OCCUPATIONS")
        print("="*80)
        
        occupation_texts = [occ['occupation_es'] for occ in occupations]
        occupation_translations = self.translate_parallel(occupation_texts, batch_size=batch_size, max_workers=max_workers)
        
        print("\n" + "="*80)
        print("ASSEMBLING RESULTS")
        print("="*80)
        
        for occ, trans in zip(occupations, occupation_translations):
            occ['occupation_en'] = trans
            occ['unit_title_en'] = translation_map.get(('unit', occ['unit_title_es']), '')
            occ['minor_title_en'] = translation_map.get(('minor', occ['minor_title_es']), '')
            occ['submajor_title_en'] = translation_map.get(('submajor', occ['submajor_title_es']), '')
            occ['major_title_en'] = translation_map.get(('major', occ['major_title_es']), '')
        
        df = pd.DataFrame(occupations)
        
        column_order = [
            'major_code', 'major_title_es', 'major_title_en',
            'submajor_code', 'submajor_title_es', 'submajor_title_en',
            'minor_code', 'minor_title_es', 'minor_title_en',
            'unit_code', 'unit_title_es', 'unit_title_en',
            'occupation_code', 'occupation_es', 'occupation_en'
        ]
        
        df = df[column_order]
        
        print(f"✓ Complete! {len(df)} occupations processed")
        
        return df

def save_to_excel(df: pd.DataFrame, output_file: str):
    """Save DataFrame to Excel with formatting"""
    print(f"\nSaving to {output_file}...")
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='CNO_2017_Translated', index=False)
        
        worksheet = writer.sheets['CNO_2017_Translated']
        
        for idx, col in enumerate(df.columns):
            max_length = max(df[col].astype(str).apply(len).max(), len(col))
            width = min(max_length + 2, 80)  # Increased max width to 80
            column_letter = chr(65 + idx) if idx < 26 else chr(65 + idx//26 - 1) + chr(65 + idx%26)
            worksheet.column_dimensions[column_letter].width = width
        
        worksheet.freeze_panes = 'A2'
    
    print(f"✓ Saved successfully!")

# MAIN EXECUTION
if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv

    BASE_DIR = Path(__file__).parent.parent  # argentina_cno2017/
    load_dotenv(BASE_DIR.parent.parent / '.env')

    API_KEY = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not API_KEY:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set")

    file_path = BASE_DIR / 'data' / 'pdfs' / 'ARG_CNO_2017.txt'

    print("Reading document...")
    with open(file_path, 'r', encoding='utf-8') as f:
        document_text = f.read()

    start_time = time.time()

    parser = FastCNOParser(API_KEY)
    df = parser.process_document(document_text, batch_size=100, max_workers=10)

    output_path = BASE_DIR / 'data' / 'cno2017_source_translated.xlsx'
    save_to_excel(df, str(output_path))
    
    elapsed_time = time.time() - start_time
    
    print("\n" + "="*80)
    print("TRANSLATION SUMMARY")
    print("="*80)
    print(f"⏱ Total time: {elapsed_time/60:.2f} minutes")
    print(f"📊 Total occupations: {len(df)}")
    print(f"📊 Major categories: {df['major_code'].nunique()}")
    print(f"📊 Sub-major categories: {df['submajor_code'].nunique()}")
    print(f"📊 Minor categories: {df['minor_code'].nunique()}")
    print(f"📊 Unit groups: {df['unit_code'].nunique()}")
    
    # Show some examples of long titles
    print("\n" + "="*80)
    print("SAMPLE LONG TITLES (to verify completeness)")
    print("="*80)
    long_titles = df[df['major_title_es'].str.len() > 50].head(3)
    for _, row in long_titles.iterrows():
        print(f"\nCode: {row['major_code']}")
        print(f"ES: {row['major_title_es']}")
        print(f"EN: {row['major_title_en']}")