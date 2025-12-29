"""
CNO-2017 to ESCO Full Matching Pipeline

Steps:
  1A: ISCO-constrained semantic matching (use crosswalk to limit ESCO candidates)
  1B: Unconstrained high-confidence upgrade (>=95% match anywhere in ESCO)
  2A: LLM binary validation (APPROVE/REJECT remaining candidates)
  2B: Hybrid candidate search (present multiple candidates for LLM selection)

Input:
  - data/cno2017_embeddings.json
  - shared_data/esco_embeddings_es_gemini.json
  - outputs/arg_cno2017_group_crosswalk.csv
  - data/cno2017_complete.xlsx

Output:
  - outputs/arg_cno2017_matches_final.json
  - outputs/arg_cno2017_matches_final.xlsx
  - outputs/arg_cno2017_review_items.json
  - outputs/arg_cno2017_review_items.xlsx
"""

import json
import os
import re
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm
import google.generativeai as genai
from dotenv import load_dotenv

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = Path(__file__).parent.parent  # argentina_cno2017/
ROOT_DIR = BASE_DIR.parent.parent  # TabiyaESCO_Localization/
load_dotenv(ROOT_DIR / '.env')

# Input files
CNO_EMBEDDINGS_FILE = BASE_DIR / 'data' / 'cno2017_embeddings.json'
ESCO_EMBEDDINGS_FILE = ROOT_DIR / 'shared_data' / 'esco_embeddings_es_gemini.json'
CROSSWALK_FILE = BASE_DIR / 'outputs' / 'arg_cno2017_group_crosswalk.csv'
CNO_SOURCE_FILE = BASE_DIR / 'data' / 'cno2017_complete.xlsx'

# Output files
OUTPUT_JSON = BASE_DIR / 'outputs' / 'arg_cno2017_matches_final.json'
OUTPUT_EXCEL = BASE_DIR / 'outputs' / 'arg_cno2017_matches_final.xlsx'
OUTPUT_REVIEW_JSON = BASE_DIR / 'outputs' / 'arg_cno2017_review_items.json'
OUTPUT_REVIEW_EXCEL = BASE_DIR / 'outputs' / 'arg_cno2017_review_items.xlsx'
CHECKPOINT_FILE = BASE_DIR / 'outputs' / 'arg_cno2017_pipeline_checkpoint.json'

# Thresholds
STEP_1B_THRESHOLD = 0.95  # Unconstrained upgrade threshold
STEP_2B_MAX_CANDIDATES = 8

# LLM
MODEL_NAME = 'models/gemini-2.0-flash'


# =============================================================================
# DATA LOADING
# =============================================================================

def load_all_data():
    """Load all required data files."""
    print("=" * 80)
    print("LOADING DATA")
    print("=" * 80)

    # CNO embeddings
    print(f"\nLoading CNO embeddings...")
    with open(CNO_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
        cno_data = json.load(f)
    cno_occupations = cno_data['occupations']
    cno_matrix = np.array([occ['embedding'] for occ in cno_occupations])
    print(f"  {len(cno_occupations)} CNO occupations, {cno_matrix.shape[1]} dimensions")

    # ESCO embeddings
    print(f"\nLoading ESCO embeddings...")
    with open(ESCO_EMBEDDINGS_FILE, 'r', encoding='utf-8') as f:
        esco_data = json.load(f)
    esco_embeddings = esco_data['embeddings']
    esco_matrix = np.array([e['embedding'] for e in esco_embeddings])
    print(f"  {len(esco_embeddings)} ESCO label embeddings, {esco_matrix.shape[1]} dimensions")

    # Build ESCO metadata and indices
    esco_metadata = []
    isco_prefix_to_indices = defaultdict(list)
    preferred_labels = {}

    for idx, e in enumerate(esco_embeddings):
        code = e['esco_code']
        esco_metadata.append({
            'esco_code': code,
            'label': e['label'],
            'label_type': e['label_type'],
            'description': e.get('description', '')[:300]
        })

        # Build ISCO prefix index
        if code:
            for prefix_len in [1, 2]:
                if len(code) >= prefix_len:
                    isco_prefix_to_indices[code[:prefix_len]].append(idx)

        # Track preferred labels
        if e['label_type'] == 'preferred':
            preferred_labels[code] = e['label']

    print(f"  {len(preferred_labels)} unique ESCO occupations")

    # Crosswalk
    print(f"\nLoading crosswalk...")
    crosswalk = {}
    if CROSSWALK_FILE.exists():
        df = pd.read_csv(CROSSWALK_FILE)
        for _, row in df.iterrows():
            crosswalk[int(row['cno_code'])] = str(row['isco_08_code'])
    print(f"  {len(crosswalk)} CNO->ISCO mappings")

    # CNO context and unit codes
    print(f"\nLoading CNO context...")
    cno_df = pd.read_excel(CNO_SOURCE_FILE)
    cno_context = {}
    unit_codes = {}
    for _, row in cno_df.iterrows():
        code = row['occupation_code']
        parts = []
        if pd.notna(row.get('subgroup_title_es')):
            parts.append(row['subgroup_title_es'])
        if pd.notna(row.get('minor_title_es')):
            parts.append(row['minor_title_es'])
        cno_context[code] = ' > '.join(parts) if parts else ''
        unit_codes[code] = str(row.get('unit_code', ''))
    print(f"  {len(cno_context)} CNO context entries")

    return {
        'cno_occupations': cno_occupations,
        'cno_matrix': cno_matrix,
        'esco_metadata': esco_metadata,
        'esco_matrix': esco_matrix,
        'isco_prefix_to_indices': dict(isco_prefix_to_indices),
        'preferred_labels': preferred_labels,
        'crosswalk': crosswalk,
        'cno_context': cno_context,
        'unit_codes': unit_codes
    }


def build_crosswalk_key(unit_code: str):
    """Build crosswalk lookup key from unit code (MM.S.M.Q -> integer)."""
    if not unit_code or unit_code == 'nan':
        return None
    parts = unit_code.split('.')
    if len(parts) < 4:
        return None
    key_str = parts[0].zfill(2) + parts[1] + parts[2] + parts[3]
    return int(key_str)


def get_best_match_per_occupation(similarities, esco_metadata, mask=None, top_k=5):
    """Get best-matching label per unique ESCO occupation."""
    if mask is not None:
        valid_indices = np.where(mask)[0]
        if len(valid_indices) == 0:
            return []
        valid_sims = similarities[valid_indices]
    else:
        valid_indices = np.arange(len(similarities))
        valid_sims = similarities

    code_to_best = {}
    for i, idx in enumerate(valid_indices):
        meta = esco_metadata[idx]
        code = meta['esco_code']
        sim = valid_sims[i]
        if code not in code_to_best or sim > code_to_best[code][0]:
            code_to_best[code] = (sim, idx)

    sorted_codes = sorted(code_to_best.items(), key=lambda x: x[1][0], reverse=True)[:top_k]

    results = []
    for code, (sim, idx) in sorted_codes:
        meta = esco_metadata[idx]
        results.append({
            'esco_code': code,
            'label': meta['label'],
            'label_type': meta['label_type'],
            'description': meta['description'],
            'similarity': float(sim)
        })
    return results


def normalize_text(text: str) -> set:
    """Normalize text to word set for comparison."""
    if not text:
        return set()
    text = text.lower()
    stopwords = {'de', 'la', 'el', 'los', 'las', 'en', 'para', 'y', 'del', 'con', 'a', 'un', 'una'}
    words = set(re.findall(r'\w+', text))
    return words - stopwords


def calculate_word_overlap(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between word sets."""
    words1 = normalize_text(text1)
    words2 = normalize_text(text2)
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


# =============================================================================
# STEP 1A: ISCO-CONSTRAINED SEMANTIC MATCHING
# =============================================================================

def step_1a_constrained_matching(data):
    """Match CNO to ESCO within ISCO constraints from crosswalk."""
    print("\n" + "=" * 80)
    print("STEP 1A: ISCO-CONSTRAINED SEMANTIC MATCHING")
    print("=" * 80)

    cno_occupations = data['cno_occupations']
    cno_matrix = data['cno_matrix']
    esco_metadata = data['esco_metadata']
    esco_matrix = data['esco_matrix']
    isco_prefix_to_indices = data['isco_prefix_to_indices']
    preferred_labels = data['preferred_labels']
    crosswalk = data['crosswalk']
    unit_codes = data['unit_codes']

    # Precompute ISCO masks
    isco_masks = {}
    for prefix, indices in isco_prefix_to_indices.items():
        mask = np.zeros(len(esco_metadata), dtype=bool)
        mask[indices] = True
        isco_masks[prefix] = mask

    # Compute full similarity matrix
    print("\nComputing similarity matrix...")
    similarity_matrix = cosine_similarity(cno_matrix, esco_matrix)
    print(f"  Shape: {similarity_matrix.shape}")

    # Match each CNO occupation
    print("\nMatching occupations...")
    matches = []

    for i, cno_occ in enumerate(tqdm(cno_occupations, desc="  Step 1A")):
        cno_code = cno_occ['occupation_code']
        cno_label_es = cno_occ.get('occupation_es', '')
        cno_label_en = cno_occ.get('occupation_en', '')
        similarities = similarity_matrix[i]

        # Get ISCO code from crosswalk
        unit_code = unit_codes.get(cno_code, '')
        crosswalk_key = build_crosswalk_key(unit_code)
        isco_code = crosswalk.get(crosswalk_key) if crosswalk_key else None

        # Find best match within ISCO constraint
        candidates = []
        search_strategy = 'unconstrained'

        if isco_code and isco_code not in ['0', '99', '*']:
            isco_prefix = isco_code.replace('*', '') if '*' in isco_code else isco_code[:2]
            if isco_prefix in isco_masks:
                mask = isco_masks[isco_prefix]
                candidates = get_best_match_per_occupation(similarities, esco_metadata, mask, top_k=1)
                search_strategy = f'isco_constrained_{isco_prefix}'

        if not candidates:
            candidates = get_best_match_per_occupation(similarities, esco_metadata, None, top_k=1)
            search_strategy = 'unconstrained'

        # Categorize match
        if candidates:
            top = candidates[0]
            esco_code = top['esco_code']
            matched_label = top['label']
            similarity = top['similarity']
            label_type = top['label_type']

            word_overlap = calculate_word_overlap(cno_label_es, matched_label)

            # Categorization rules
            if similarity >= 0.98 and word_overlap >= 0.8:
                category = 'exact'
            elif similarity >= 0.98:
                category = 'alt_label'
            elif word_overlap >= 0.95 and similarity >= 0.90:
                category = 'exact'
            else:
                category = 'NEEDS_LLM'

            matches.append({
                'cno_code': cno_code,
                'cno_label_es': cno_label_es,
                'cno_label_en': cno_label_en,
                'esco_code': esco_code,
                'esco_label': preferred_labels.get(esco_code, matched_label),
                'matched_label': matched_label,
                'label_type': label_type,
                'similarity': similarity,
                'isco_code': isco_code,
                'category': category,
                'search_strategy': search_strategy
            })
        else:
            matches.append({
                'cno_code': cno_code,
                'cno_label_es': cno_label_es,
                'cno_label_en': cno_label_en,
                'esco_code': None,
                'esco_label': None,
                'matched_label': None,
                'label_type': None,
                'similarity': 0,
                'isco_code': isco_code,
                'category': 'NEEDS_LLM',
                'search_strategy': 'no_match'
            })

    # Summary
    categories = defaultdict(int)
    for m in matches:
        categories[m['category']] += 1

    print(f"\nStep 1A Results:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} ({100*count/len(matches):.1f}%)")

    return matches, similarity_matrix


# =============================================================================
# STEP 1B: UNCONSTRAINED HIGH-CONFIDENCE UPGRADE
# =============================================================================

def step_1b_unconstrained_upgrade(matches, similarity_matrix, data):
    """Upgrade NEEDS_LLM matches if >=95% unconstrained match exists."""
    print("\n" + "=" * 80)
    print("STEP 1B: UNCONSTRAINED HIGH-CONFIDENCE UPGRADE (>= 95%)")
    print("=" * 80)

    esco_metadata = data['esco_metadata']
    preferred_labels = data['preferred_labels']
    cno_occupations = data['cno_occupations']

    # Build CNO code to index mapping
    cno_code_to_idx = {occ['occupation_code']: i for i, occ in enumerate(cno_occupations)}

    upgraded = 0
    for match in tqdm(matches, desc="  Step 1B"):
        if match['category'] != 'NEEDS_LLM':
            continue

        cno_code = match['cno_code']
        idx = cno_code_to_idx.get(cno_code)
        if idx is None:
            continue

        similarities = similarity_matrix[idx]
        candidates = get_best_match_per_occupation(similarities, esco_metadata, None, top_k=1)

        if candidates and candidates[0]['similarity'] >= STEP_1B_THRESHOLD:
            top = candidates[0]
            # Store previous match info
            match['previous_match'] = {
                'esco_code': match['esco_code'],
                'similarity': match['similarity'],
                'search_strategy': match['search_strategy']
            }
            # Update to unconstrained match
            match['esco_code'] = top['esco_code']
            match['esco_label'] = preferred_labels.get(top['esco_code'], top['label'])
            match['matched_label'] = top['label']
            match['label_type'] = top['label_type']
            match['similarity'] = top['similarity']
            match['category'] = 'high_conf_unconstrained'
            match['search_strategy'] = 'unconstrained_95'
            upgraded += 1

    print(f"\nStep 1B Results:")
    print(f"  Upgraded to high_conf_unconstrained: {upgraded}")

    # Updated category counts
    categories = defaultdict(int)
    for m in matches:
        categories[m['category']] += 1

    print(f"\nUpdated distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} ({100*count/len(matches):.1f}%)")

    return matches


# =============================================================================
# STEP 2A: LLM BINARY VALIDATION
# =============================================================================

def step_2a_llm_validation(matches, data):
    """LLM validates NEEDS_LLM matches: APPROVE or REJECT."""
    print("\n" + "=" * 80)
    print("STEP 2A: LLM BINARY VALIDATION (APPROVE/REJECT)")
    print("=" * 80)

    cno_context = data['cno_context']
    esco_metadata = data['esco_metadata']

    # Build ESCO description lookup
    esco_descriptions = {}
    for meta in esco_metadata:
        if meta['esco_code'] not in esco_descriptions:
            esco_descriptions[meta['esco_code']] = meta['description']

    # Configure Gemini
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction="""You are an expert at matching occupational classifications.

A match is APPROVED if:
1. The two occupations describe the SAME work, just worded differently
2. The CNO occupation is a MORE SPECIFIC version of the ESCO occupation

A match is REJECTED if:
- The occupations describe MEANINGFULLY DIFFERENT work

Reply with ONLY one word: APPROVE or REJECT"""
    )

    # Load checkpoint
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            checkpoint = json.load(f)
    step_2a_processed = checkpoint.get('step_2a', {})

    # Process NEEDS_LLM matches
    needs_llm = [m for m in matches if m['category'] == 'NEEDS_LLM']
    print(f"\nProcessing {len(needs_llm)} NEEDS_LLM matches...")

    approved = 0
    rejected = 0

    for match in tqdm(needs_llm, desc="  Step 2A"):
        cno_code = match['cno_code']

        if cno_code in step_2a_processed:
            decision = step_2a_processed[cno_code]
        else:
            prompt = f"""Evaluate this occupation match:

CNO (Argentina):
- Label (Spanish): {match['cno_label_es']}
- Label (English): {match['cno_label_en']}
- Group context: {cno_context.get(cno_code, '')}

ESCO (European):
- Preferred Label: {match['esco_label']}
- Matched via: {match['matched_label']}
- Description: {esco_descriptions.get(match['esco_code'], '')[:400]}

Is this match acceptable? Reply with only APPROVE or REJECT."""

            decision = 'ERROR'
            for attempt in range(3):
                try:
                    response = model.generate_content(
                        prompt,
                        generation_config=genai.types.GenerationConfig(temperature=0, max_output_tokens=10)
                    )
                    result = response.text.strip().upper()
                    if 'APPROVE' in result:
                        decision = 'APPROVE'
                        break
                    elif 'REJECT' in result:
                        decision = 'REJECT'
                        break
                except Exception as e:
                    if '429' in str(e):
                        time.sleep(30 * (attempt + 1))
                    else:
                        time.sleep(5)

            step_2a_processed[cno_code] = decision
            time.sleep(0.1)

            # Checkpoint every 50
            if len(step_2a_processed) % 50 == 0:
                checkpoint['step_2a'] = step_2a_processed
                with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(checkpoint, f)

        match['llm_decision'] = decision
        if decision == 'APPROVE':
            match['category'] = 'llm_approved'
            approved += 1
        elif decision == 'REJECT':
            match['category'] = 'llm_rejected'
            rejected += 1

    # Save checkpoint
    checkpoint['step_2a'] = step_2a_processed
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f)

    print(f"\nStep 2A Results:")
    print(f"  APPROVED: {approved} ({100*approved/len(needs_llm):.1f}%)")
    print(f"  REJECTED: {rejected} ({100*rejected/len(needs_llm):.1f}%)")

    return matches


# =============================================================================
# STEP 2B: HYBRID CANDIDATE SEARCH
# =============================================================================

def step_2b_hybrid_candidate_search(matches, similarity_matrix, data):
    """For rejected matches, present hybrid candidates for LLM selection."""
    print("\n" + "=" * 80)
    print("STEP 2B: HYBRID CANDIDATE SEARCH")
    print("=" * 80)

    cno_occupations = data['cno_occupations']
    esco_metadata = data['esco_metadata']
    isco_prefix_to_indices = data['isco_prefix_to_indices']
    preferred_labels = data['preferred_labels']
    crosswalk = data['crosswalk']
    unit_codes = data['unit_codes']
    cno_context = data['cno_context']

    # Build CNO code to index mapping
    cno_code_to_idx = {occ['occupation_code']: i for i, occ in enumerate(cno_occupations)}

    # Precompute ISCO masks
    isco_masks = {}
    for prefix, indices in isco_prefix_to_indices.items():
        mask = np.zeros(len(esco_metadata), dtype=bool)
        mask[indices] = True
        isco_masks[prefix] = mask

    # Configure Gemini
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction="""You are an expert at matching occupational classifications.

Select the BEST matching ESCO occupation from the candidates, or indicate none are suitable.

A match is GOOD if:
1. The occupations describe the SAME work
2. The CNO occupation is a more specific version of the ESCO

Reply with ONLY:
- A single number (1-8) indicating your choice, OR
- "NONE" if no candidate is suitable"""
    )

    # Load checkpoint
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            checkpoint = json.load(f)
    step_2b_processed = checkpoint.get('step_2b', {})

    # Process llm_rejected matches
    rejected = [m for m in matches if m['category'] == 'llm_rejected']
    print(f"\nProcessing {len(rejected)} llm_rejected matches...")

    selected = 0
    none_count = 0

    for match in tqdm(rejected, desc="  Step 2B"):
        cno_code = match['cno_code']

        if cno_code in step_2b_processed:
            cached = step_2b_processed[cno_code]
            if cached['decision'] == 'SELECT':
                match['esco_code'] = cached['esco_code']
                match['esco_label'] = cached['esco_label']
                match['matched_label'] = cached['matched_label']
                match['similarity'] = cached['similarity']
                match['category'] = 'phase3_matched'
                selected += 1
            else:
                match['category'] = 'new_local'
                none_count += 1
            continue

        idx = cno_code_to_idx.get(cno_code)
        if idx is None:
            match['category'] = 'new_local'
            step_2b_processed[cno_code] = {'decision': 'NONE'}
            none_count += 1
            continue

        similarities = similarity_matrix[idx]

        # Get unconstrained candidates
        unconstrained = get_best_match_per_occupation(similarities, esco_metadata, None, top_k=5)

        # Get ISCO-constrained candidates
        unit_code = unit_codes.get(cno_code, '')
        crosswalk_key = build_crosswalk_key(unit_code)
        isco_code = crosswalk.get(crosswalk_key) if crosswalk_key else None

        constrained = []
        if isco_code and isco_code not in ['0', '99', '*']:
            isco_prefix = isco_code.replace('*', '') if '*' in isco_code else isco_code[:2]
            if isco_prefix in isco_masks:
                constrained = get_best_match_per_occupation(similarities, esco_metadata, isco_masks[isco_prefix], top_k=5)

        # Merge and deduplicate
        seen = set()
        candidates = []
        for c in unconstrained + constrained:
            if c['esco_code'] not in seen:
                c['preferred_label'] = preferred_labels.get(c['esco_code'], c['label'])
                candidates.append(c)
                seen.add(c['esco_code'])
            if len(candidates) >= STEP_2B_MAX_CANDIDATES:
                break

        if not candidates:
            match['category'] = 'new_local'
            step_2b_processed[cno_code] = {'decision': 'NONE'}
            none_count += 1
            continue

        # Format candidates for LLM
        cand_text = []
        for i, c in enumerate(candidates, 1):
            cand_text.append(f"{i}. {c['preferred_label']} ({c['similarity']*100:.0f}%)")
            if c['description']:
                cand_text.append(f"   {c['description'][:120]}...")

        prompt = f"""CNO Occupation (Argentina):
- Spanish: {match['cno_label_es']}
- English: {match['cno_label_en']}
- Group: {cno_context.get(cno_code, '')}

Candidate ESCO Occupations:
{chr(10).join(cand_text)}

Which candidate (1-{len(candidates)}) is the best match? Or reply "NONE" if none are suitable."""

        decision = 'ERROR'
        selected_candidate = None

        for attempt in range(3):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(temperature=0, max_output_tokens=10)
                )
                result = response.text.strip().upper()

                if 'NONE' in result:
                    decision = 'NONE'
                    break

                for i in range(1, len(candidates) + 1):
                    if str(i) in result:
                        decision = 'SELECT'
                        selected_candidate = candidates[i - 1]
                        break

                if decision != 'ERROR':
                    break
            except Exception as e:
                if '429' in str(e):
                    time.sleep(30 * (attempt + 1))
                else:
                    time.sleep(5)

        if decision == 'SELECT' and selected_candidate:
            match['esco_code'] = selected_candidate['esco_code']
            match['esco_label'] = selected_candidate['preferred_label']
            match['matched_label'] = selected_candidate['label']
            match['similarity'] = selected_candidate['similarity']
            match['category'] = 'phase3_matched'
            step_2b_processed[cno_code] = {
                'decision': 'SELECT',
                'esco_code': selected_candidate['esco_code'],
                'esco_label': selected_candidate['preferred_label'],
                'matched_label': selected_candidate['label'],
                'similarity': selected_candidate['similarity']
            }
            selected += 1
        else:
            match['category'] = 'new_local'
            step_2b_processed[cno_code] = {'decision': 'NONE'}
            none_count += 1

        time.sleep(0.1)

        # Checkpoint every 50
        if len(step_2b_processed) % 50 == 0:
            checkpoint['step_2b'] = step_2b_processed
            with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
                json.dump(checkpoint, f)

    # Save checkpoint
    checkpoint['step_2b'] = step_2b_processed
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f)

    print(f"\nStep 2B Results:")
    print(f"  Selected ESCO match: {selected} ({100*selected/len(rejected):.1f}%)")
    print(f"  No match (new_local): {none_count} ({100*none_count/len(rejected):.1f}%)")

    return matches


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 80)
    print("CNO-2017 TO ESCO FULL MATCHING PIPELINE")
    print("=" * 80)
    print(f"Started: {datetime.now().isoformat()}")

    # Load data
    data = load_all_data()

    # Step 1A: ISCO-constrained semantic matching
    matches, similarity_matrix = step_1a_constrained_matching(data)

    # Step 1B: Unconstrained high-confidence upgrade
    matches = step_1b_unconstrained_upgrade(matches, similarity_matrix, data)

    # Step 2A: LLM binary validation
    matches = step_2a_llm_validation(matches, data)

    # Step 2B: Hybrid candidate search
    matches = step_2b_hybrid_candidate_search(matches, similarity_matrix, data)

    # Final summary
    print("\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)

    categories = defaultdict(int)
    for m in matches:
        categories[m['category']] += 1

    print(f"\nCategory distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} ({100*count/len(matches):.1f}%)")

    esco_matched = sum(1 for m in matches if m['category'] != 'new_local')
    new_local = sum(1 for m in matches if m['category'] == 'new_local')

    print(f"\nSummary:")
    print(f"  ESCO-matched: {esco_matched} ({100*esco_matched/len(matches):.1f}%)")
    print(f"  New local: {new_local} ({100*new_local/len(matches):.1f}%)")

    # Save results
    print(f"\nSaving results...")
    os.makedirs(OUTPUT_JSON.parent, exist_ok=True)

    output_data = {
        'metadata': {
            'pipeline': 'CNO-2017 to ESCO Full Matching',
            'generated_at': datetime.now().isoformat(),
            'total_matches': len(matches),
            'esco_matched': esco_matched,
            'new_local': new_local,
            'category_counts': dict(categories)
        },
        'matches': matches
    }

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved JSON: {OUTPUT_JSON}")

    # Excel export
    excel_data = []
    for m in matches:
        excel_data.append({
            'cno_code': m['cno_code'],
            'cno_label_es': m['cno_label_es'],
            'cno_label_en': m['cno_label_en'],
            'esco_code': m.get('esco_code', ''),
            'esco_label': m.get('esco_label', ''),
            'matched_label': m.get('matched_label', ''),
            'similarity': m.get('similarity', 0),
            'category': m['category']
        })

    df = pd.DataFrame(excel_data)
    df.to_excel(OUTPUT_EXCEL, index=False)
    print(f"  Saved Excel: {OUTPUT_EXCEL}")

    # Save review items (new_local category)
    review_items = [m for m in matches if m['category'] == 'new_local']
    review_data = {
        'metadata': {
            'source': 'CNO-2017 Matching Pipeline',
            'generated_at': datetime.now().isoformat(),
            'total_items': len(review_items),
            'description': 'Occupations requiring human review (no suitable ESCO match found)'
        },
        'items': review_items
    }
    with open(OUTPUT_REVIEW_JSON, 'w', encoding='utf-8') as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved review JSON: {OUTPUT_REVIEW_JSON}")

    review_excel_data = []
    for m in review_items:
        review_excel_data.append({
            'cno_code': m['cno_code'],
            'cno_label_es': m['cno_label_es'],
            'cno_label_en': m['cno_label_en'],
            'isco_code': m.get('isco_code', ''),
            'suggested_esco_code': m.get('esco_code', ''),
            'suggested_esco_label': m.get('esco_label', ''),
            'similarity': m.get('similarity', 0)
        })
    pd.DataFrame(review_excel_data).to_excel(OUTPUT_REVIEW_EXCEL, index=False)
    print(f"  Saved review Excel: {OUTPUT_REVIEW_EXCEL}")

    # Clean up checkpoint
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print("  Removed checkpoint file")

    print(f"\nCompleted: {datetime.now().isoformat()}")
    print("=" * 80)


if __name__ == '__main__':
    main()
