"""
KeSCO to ESCO Full Matching Pipeline

Complete pipeline for mapping Kenya Standard Classification of Occupations (KeSCO)
to Tabiya ESCO taxonomy using Gemini embeddings and LLM validation.

Pipeline Steps:
  1A: ISCO-constrained semantic matching (use KeSCO ISCO code to limit ESCO candidates)
  1B: Unconstrained high-confidence upgrade (>=95% match anywhere in ESCO)
  2A: LLM binary validation (APPROVE/REJECT for non-exact matches)
  2B: Hybrid candidate search (present multiple candidates for matches <90% or rejected)

Prerequisites:
  - KeSCO embeddings: data/kesco_embeddings.json
  - ESCO embeddings: shared_data/esco_embeddings_en_gemini.json
  - ESCO taxonomy files in shared_data/esco_taxonomy/

Output:
  - outputs/kesco_esco_matches_final.xlsx

Usage:
    python scripts/full_matching_pipeline.py

Note: This is a documentation script combining all steps. For actual runs,
individual step scripts were used with checkpointing for reliability.
"""

import json
import os
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

BASE_PATH = Path("C:/Users/Afsana/Dropbox/Tabiya/Taxonomy/TabiyaESCO_Localization")
load_dotenv(BASE_PATH / '.env')

# Input files
KESCO_EMBEDDINGS = BASE_PATH / 'countries' / 'kenya_kesco' / 'data' / 'kesco_embeddings.json'
ESCO_EMBEDDINGS = BASE_PATH / 'shared_data' / 'esco_embeddings_en_gemini.json'
KESCO_SOURCE = BASE_PATH / 'countries' / 'kenya_kesco' / 'data' / 'KeSCO_occupations_with_context.xlsx'
ESCO_GROUPS = BASE_PATH / 'shared_data' / 'esco_taxonomy' / 'occupation_groups.csv'
ESCO_OCCS = BASE_PATH / 'shared_data' / 'esco_taxonomy' / 'occupations.csv'

# Output files
OUTPUT_DIR = BASE_PATH / 'countries' / 'kenya_kesco' / 'outputs'
OUTPUT_JSON = OUTPUT_DIR / 'kenya_kesco_matches_final.json'
OUTPUT_EXCEL = OUTPUT_DIR / 'kenya_kesco_matches_final.xlsx'
OUTPUT_REVIEW_JSON = OUTPUT_DIR / 'kenya_kesco_review_items.json'
OUTPUT_REVIEW_EXCEL = OUTPUT_DIR / 'kenya_kesco_review_items.xlsx'

# Thresholds
EXACT_THRESHOLD = 0.95           # Step 1A: exact match threshold
STEP_1B_THRESHOLD = 0.95         # Step 1B: unconstrained upgrade threshold
HIGH_CONF_THRESHOLD = 0.85       # Step 1A: high confidence threshold
LOW_SIM_THRESHOLD = 0.90         # Step 2B: include low similarity for review
TOP_K_UNCONSTRAINED = 5          # Step 2B: unconstrained candidates
TOP_K_CONSTRAINED = 5            # Step 2B: ISCO-constrained candidates
MAX_CANDIDATES = 10              # Step 2B: max candidates for LLM

# LLM Configuration
MODEL_NAME = 'models/gemini-2.0-flash'
MAX_RETRIES = 5
CHECKPOINT_FREQUENCY = 20


# =============================================================================
# LLM PROMPTS
# =============================================================================

STEP_2A_SYSTEM_PROMPT = """You are an expert at matching occupational classifications.

You are given a KeSCO (Kenya Standard Classification of Occupations) occupation and a proposed ESCO (European Skills, Competences, Qualifications and Occupations) match.

Your task is to validate whether the match is correct.

A match is GOOD if:
1. The occupations describe the SAME or very similar work
2. The KeSCO occupation could reasonably be a local/specific version of the ESCO occupation

A match is BAD if:
1. The occupations describe different work
2. The semantic similarity is misleading (e.g., similar words but different meanings)

Reply with ONLY one word:
- APPROVE - if the match is good
- REJECT - if the match is not suitable

Do not explain your choice."""


STEP_2A_USER_PROMPT = """KeSCO Occupation (Kenya):
- Title: {kesco_title}
- Unit Group: {kesco_unit_group}
- Minor Group: {kesco_minor_group}
- ISCO Code: {isco_code}

Proposed ESCO Match:
- Label: {esco_label}
- Unit Group: {esco_unit_group}
- Description: {esco_description}
- Similarity: {similarity}%

Is this a good match? Reply APPROVE or REJECT."""


STEP_2B_SYSTEM_PROMPT = """You are an expert at matching occupational classifications.

You are given a KeSCO (Kenya Standard Classification of Occupations) occupation and a list of candidate ESCO (European) occupations to choose from.

Your task is to select the BEST matching ESCO occupation, or indicate that none are suitable.

A match is GOOD if:
1. The occupations describe the SAME or very similar work
2. The KeSCO occupation is a local/specific version of the ESCO occupation

Reply with ONLY:
- A single number (1-10) indicating your choice, OR
- "NONE" if no candidate is a suitable match

Do not explain your choice."""


STEP_2B_USER_PROMPT = """KeSCO Occupation (Kenya):
- Title: {kesco_title}
- Unit Group: {kesco_unit_group}
- Minor Group: {kesco_minor_group}
- ISCO Code: {isco_code}

{current_match_text}Candidate ESCO Occupations:
{candidates_text}

Which candidate (1-{num_candidates}) is the best match? Or reply "NONE" if none are suitable."""


# =============================================================================
# DATA LOADING
# =============================================================================

def load_all_data():
    """Load all required data files."""
    print("=" * 70)
    print("LOADING DATA")
    print("=" * 70)

    # KeSCO embeddings
    print(f"\nLoading KeSCO embeddings...")
    with open(KESCO_EMBEDDINGS, 'r', encoding='utf-8') as f:
        kesco_data = json.load(f)
    kesco_occupations = kesco_data['occupations']
    kesco_matrix = np.array([occ['embedding'] for occ in kesco_occupations])
    print(f"  {len(kesco_occupations)} KeSCO occupations, {kesco_matrix.shape[1]} dimensions")

    # ESCO embeddings
    print(f"\nLoading ESCO embeddings...")
    with open(ESCO_EMBEDDINGS, 'r', encoding='utf-8') as f:
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
            code_str = str(code).split('.')[0]
            for prefix_len in [1, 2, 3, 4]:
                if len(code_str) >= prefix_len:
                    isco_prefix_to_indices[code_str[:prefix_len]].append(idx)

        if e['label_type'] == 'preferred':
            preferred_labels[code] = e['label']

    print(f"  {len(preferred_labels)} unique ESCO occupations")

    # KeSCO context
    print(f"\nLoading KeSCO context...")
    kesco_df = pd.read_excel(KESCO_SOURCE)
    kesco_context = {}
    for _, row in kesco_df.iterrows():
        code = str(row['kesco_code'])
        kesco_context[code] = {
            'unit_group_label': str(row.get('unit_group_label', '')),
            'minor_group_label': str(row.get('minor_group_label', '')),
        }
    print(f"  Loaded context for {len(kesco_context)} occupations")

    # ESCO group labels
    print(f"\nLoading ESCO group labels...")
    groups = pd.read_csv(ESCO_GROUPS)
    group_labels = {str(row['CODE']): row['PREFERREDLABEL'] for _, row in groups.iterrows()}
    print(f"  Loaded {len(group_labels)} group labels")

    # ESCO occupation info
    print(f"\nLoading ESCO occupation info...")
    occs = pd.read_csv(ESCO_OCCS)
    occ_info = {}
    for _, row in occs.iterrows():
        group_code = str(row['OCCUPATIONGROUPCODE'])
        label = row['PREFERREDLABEL']
        occ_info[label.lower()] = {
            'group_code': group_code,
            'description': str(row.get('DESCRIPTION', ''))[:300],
            'group_label': group_labels.get(group_code, '')
        }
    print(f"  Loaded info for {len(occ_info)} occupations")

    return {
        'kesco_occupations': kesco_occupations,
        'kesco_matrix': kesco_matrix,
        'kesco_context': kesco_context,
        'esco_metadata': esco_metadata,
        'esco_matrix': esco_matrix,
        'isco_prefix_to_indices': dict(isco_prefix_to_indices),
        'preferred_labels': preferred_labels,
        'group_labels': group_labels,
        'occ_info': occ_info
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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


def configure_gemini():
    """Configure Gemini API."""
    api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    print(f"  Gemini API configured with model: {MODEL_NAME}")


# =============================================================================
# STEP 1A: ISCO-CONSTRAINED SEMANTIC MATCHING
# =============================================================================

def step_1a_constrained_matching(data):
    """Match KeSCO to ESCO within ISCO constraints."""
    print("\n" + "=" * 70)
    print("STEP 1A: ISCO-CONSTRAINED SEMANTIC MATCHING")
    print("=" * 70)

    kesco_occupations = data['kesco_occupations']
    kesco_matrix = data['kesco_matrix']
    esco_metadata = data['esco_metadata']
    esco_matrix = data['esco_matrix']
    isco_prefix_to_indices = data['isco_prefix_to_indices']
    preferred_labels = data['preferred_labels']

    # Precompute ISCO masks
    print("\nPrecomputing ISCO masks...")
    isco_masks = {}
    for prefix, indices in isco_prefix_to_indices.items():
        mask = np.zeros(len(esco_metadata), dtype=bool)
        mask[indices] = True
        isco_masks[prefix] = mask

    # Compute full similarity matrix
    print("Computing similarity matrix...")
    similarity_matrix = cosine_similarity(kesco_matrix, esco_matrix)
    print(f"  Shape: {similarity_matrix.shape}")

    # Match each KeSCO occupation
    print("\nMatching occupations...")
    matches = []

    for i, kesco_occ in enumerate(tqdm(kesco_occupations, desc="  Step 1A")):
        kesco_code = kesco_occ['kesco_code']
        kesco_title = kesco_occ['title']
        isco_code = kesco_occ.get('isco_code', '')

        similarities = similarity_matrix[i]

        # Try ISCO-constrained search
        candidates = []
        search_strategy = 'unconstrained'

        for prefix_len in [4, 3, 2]:
            if len(isco_code) >= prefix_len:
                prefix = isco_code[:prefix_len]
                if prefix in isco_masks:
                    candidates = get_best_match_per_occupation(
                        similarities, esco_metadata, isco_masks[prefix], top_k=1
                    )
                    if candidates:
                        search_strategy = f'isco_constrained_{prefix}'
                        break

        if not candidates:
            candidates = get_best_match_per_occupation(similarities, esco_metadata, None, top_k=1)
            search_strategy = 'unconstrained'

        if candidates:
            top = candidates[0]
            similarity = top['similarity']

            if similarity >= EXACT_THRESHOLD:
                category = 'exact'
            elif similarity >= HIGH_CONF_THRESHOLD:
                category = 'high_confidence'
            else:
                category = 'needs_review'

            matches.append({
                'kesco_code': kesco_code,
                'kesco_title': kesco_title,
                'isco_code': isco_code,
                'esco_code': top['esco_code'],
                'esco_label': preferred_labels.get(top['esco_code'], top['label']),
                'matched_label': top['label'],
                'similarity': similarity,
                'category': category,
                'search_strategy': search_strategy
            })
        else:
            matches.append({
                'kesco_code': kesco_code,
                'kesco_title': kesco_title,
                'isco_code': isco_code,
                'esco_code': None,
                'esco_label': None,
                'matched_label': None,
                'similarity': 0,
                'category': 'no_match',
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
    """Upgrade non-exact matches if >=95% unconstrained match exists."""
    print("\n" + "=" * 70)
    print("STEP 1B: UNCONSTRAINED HIGH-CONFIDENCE UPGRADE (>= 95%)")
    print("=" * 70)

    esco_metadata = data['esco_metadata']
    preferred_labels = data['preferred_labels']
    kesco_occupations = data['kesco_occupations']

    kesco_code_to_idx = {occ['kesco_code']: i for i, occ in enumerate(kesco_occupations)}

    upgraded = 0
    crosswalk_mismatches = 0

    for match in tqdm(matches, desc="  Step 1B"):
        if match['category'] == 'exact':
            match['upgraded'] = False
            match['crosswalk_mismatch'] = False
            continue

        kesco_code = match['kesco_code']
        idx = kesco_code_to_idx.get(kesco_code)
        if idx is None:
            match['upgraded'] = False
            match['crosswalk_mismatch'] = False
            continue

        similarities = similarity_matrix[idx]
        candidates = get_best_match_per_occupation(similarities, esco_metadata, None, top_k=1)

        if candidates and candidates[0]['similarity'] >= STEP_1B_THRESHOLD:
            top = candidates[0]
            original_code = match['esco_code']

            if top['esco_code'] != original_code:
                match['original_esco_code'] = original_code
                match['original_similarity'] = match['similarity']

                match['esco_code'] = top['esco_code']
                match['esco_label'] = preferred_labels.get(top['esco_code'], top['label'])
                match['matched_label'] = top['label']
                match['similarity'] = top['similarity']
                match['category'] = 'exact_upgraded'
                match['search_strategy'] = 'unconstrained_upgrade'
                match['upgraded'] = True
                match['crosswalk_mismatch'] = True
                upgraded += 1
                crosswalk_mismatches += 1
            else:
                if top['similarity'] >= EXACT_THRESHOLD and match['category'] != 'exact':
                    match['category'] = 'exact'
                match['upgraded'] = False
                match['crosswalk_mismatch'] = False
        else:
            match['upgraded'] = False
            match['crosswalk_mismatch'] = False

    print(f"\nStep 1B Results:")
    print(f"  Upgraded to exact: {upgraded}")
    print(f"  Crosswalk mismatches: {crosswalk_mismatches}")

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
    """LLM validates non-exact matches: APPROVE or REJECT."""
    print("\n" + "=" * 70)
    print("STEP 2A: LLM BINARY VALIDATION (APPROVE/REJECT)")
    print("=" * 70)

    kesco_context = data['kesco_context']
    group_labels = data['group_labels']
    occ_info = data['occ_info']

    configure_gemini()
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=STEP_2A_SYSTEM_PROMPT)

    # Get non-exact matches
    non_exact = [m for m in matches if m['category'] not in ['exact', 'exact_upgraded']]
    print(f"\nValidating {len(non_exact)} non-exact matches...")

    stats = {'approved': 0, 'rejected': 0, 'error': 0}

    for match in tqdm(non_exact, desc="  Step 2A"):
        kesco_code = str(match['kesco_code'])
        ctx = kesco_context.get(kesco_code, {})

        # Get ESCO context
        esco_label = match.get('esco_label', '')
        label_lower = esco_label.lower() if esco_label else ''
        esco_info = occ_info.get(label_lower, {})

        prompt = STEP_2A_USER_PROMPT.format(
            kesco_title=match['kesco_title'],
            kesco_unit_group=ctx.get('unit_group_label', ''),
            kesco_minor_group=ctx.get('minor_group_label', ''),
            isco_code=match.get('isco_code', ''),
            esco_label=esco_label,
            esco_unit_group=esco_info.get('group_label', ''),
            esco_description=esco_info.get('description', 'Not available'),
            similarity=f"{match.get('similarity', 0)*100:.0f}"
        )

        decision = 'ERROR'
        for attempt in range(MAX_RETRIES):
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

        match['llm_decision'] = decision
        if decision == 'APPROVE':
            match['category'] = 'llm_approved'
            stats['approved'] += 1
        elif decision == 'REJECT':
            match['category'] = 'llm_rejected'
            stats['rejected'] += 1
        else:
            match['category'] = 'llm_error'
            stats['error'] += 1

        time.sleep(0.1)

    print(f"\nStep 2A Results:")
    print(f"  Approved: {stats['approved']} ({100*stats['approved']/len(non_exact):.1f}%)")
    print(f"  Rejected: {stats['rejected']} ({100*stats['rejected']/len(non_exact):.1f}%)")
    print(f"  Errors: {stats['error']}")

    return matches


# =============================================================================
# STEP 2B: HYBRID CANDIDATE SEARCH
# =============================================================================

def step_2b_hybrid_candidate_search(matches, similarity_matrix, data):
    """For rejected/low-similarity matches, present hybrid candidates for LLM selection."""
    print("\n" + "=" * 70)
    print("STEP 2B: HYBRID CANDIDATE SEARCH (EXPANDED SCOPE)")
    print("=" * 70)

    kesco_occupations = data['kesco_occupations']
    esco_metadata = data['esco_metadata']
    isco_prefix_to_indices = data['isco_prefix_to_indices']
    preferred_labels = data['preferred_labels']
    kesco_context = data['kesco_context']
    group_labels = data['group_labels']
    occ_info = data['occ_info']

    kesco_code_to_idx = {occ['kesco_code']: i for i, occ in enumerate(kesco_occupations)}

    # Precompute ISCO masks
    isco_masks = {}
    for prefix, indices in isco_prefix_to_indices.items():
        mask = np.zeros(len(esco_metadata), dtype=bool)
        mask[indices] = True
        isco_masks[prefix] = mask

    configure_gemini()
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=STEP_2B_SYSTEM_PROMPT)

    # Get matches needing Step 2B: rejected OR low similarity
    needs_2b = []
    for m in matches:
        if m['category'] == 'llm_rejected':
            m['step_2b_reason'] = 'rejected'
            needs_2b.append(m)
        elif m['category'] not in ['exact', 'exact_upgraded'] and m.get('similarity', 0) < LOW_SIM_THRESHOLD:
            m['step_2b_reason'] = 'low_similarity'
            needs_2b.append(m)

    print(f"\nProcessing {len(needs_2b)} matches (rejected + low similarity <{LOW_SIM_THRESHOLD*100:.0f}%)...")

    stats = {'selected': 0, 'none': 0, 'error': 0}

    for match in tqdm(needs_2b, desc="  Step 2B"):
        kesco_code = str(match['kesco_code'])
        idx = kesco_code_to_idx.get(kesco_code)
        if idx is None:
            match['category'] = 'new_local'
            stats['none'] += 1
            continue

        similarities = similarity_matrix[idx]
        isco_code = match.get('isco_code', '')

        # Get unconstrained candidates
        unconstrained = get_best_match_per_occupation(similarities, esco_metadata, None, TOP_K_UNCONSTRAINED)

        # Get ISCO-constrained candidates
        constrained = []
        for prefix_len in [4, 3, 2]:
            prefix = str(isco_code)[:prefix_len]
            if prefix in isco_masks:
                constrained = get_best_match_per_occupation(
                    similarities, esco_metadata, isco_masks[prefix], TOP_K_CONSTRAINED
                )
                if constrained:
                    break

        # Merge and deduplicate
        seen = set()
        candidates = []
        for c in unconstrained:
            if c['esco_code'] not in seen:
                c['source'] = 'semantic'
                c['preferred_label'] = preferred_labels.get(c['esco_code'], c['label'])
                label_lower = c['label'].lower()
                if label_lower in occ_info:
                    c['unit_group'] = occ_info[label_lower].get('group_label', '')
                else:
                    code_prefix = str(c['esco_code']).split('.')[0][:4]
                    c['unit_group'] = group_labels.get(code_prefix, '')
                candidates.append(c)
                seen.add(c['esco_code'])

        for c in constrained:
            if c['esco_code'] not in seen and len(candidates) < MAX_CANDIDATES:
                c['source'] = 'isco_constrained'
                c['preferred_label'] = preferred_labels.get(c['esco_code'], c['label'])
                label_lower = c['label'].lower()
                if label_lower in occ_info:
                    c['unit_group'] = occ_info[label_lower].get('group_label', '')
                else:
                    code_prefix = str(c['esco_code']).split('.')[0][:4]
                    c['unit_group'] = group_labels.get(code_prefix, '')
                candidates.append(c)
                seen.add(c['esco_code'])

        if not candidates:
            match['category'] = 'new_local'
            stats['none'] += 1
            continue

        # Format candidates
        cand_lines = []
        for i, c in enumerate(candidates, 1):
            cand_lines.append(f"{i}. {c['preferred_label']} ({c['similarity']*100:.0f}%) [{c['source']}]")
            if c.get('unit_group'):
                cand_lines.append(f"   Unit Group: {c['unit_group']}")
            if c.get('description'):
                desc = c['description'][:150] + "..." if len(c['description']) > 150 else c['description']
                cand_lines.append(f"   Description: {desc}")

        ctx = kesco_context.get(kesco_code, {})
        current_match_text = ""
        if match.get('step_2b_reason') == 'low_similarity':
            current_match_text = f"Current match: {match.get('esco_label', '')} ({match.get('similarity', 0)*100:.0f}%) - reviewing for better alternatives\n\n"

        prompt = STEP_2B_USER_PROMPT.format(
            kesco_title=match['kesco_title'],
            kesco_unit_group=ctx.get('unit_group_label', ''),
            kesco_minor_group=ctx.get('minor_group_label', ''),
            isco_code=match.get('isco_code', ''),
            current_match_text=current_match_text,
            candidates_text='\n'.join(cand_lines),
            num_candidates=len(candidates)
        )

        decision = 'ERROR'
        selected = None

        for attempt in range(MAX_RETRIES):
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
                        selected = candidates[i - 1]
                        break

                if decision != 'ERROR':
                    break
            except Exception as e:
                if '429' in str(e):
                    time.sleep(30 * (attempt + 1))
                else:
                    time.sleep(5)

        match['step_2b_decision'] = decision
        if decision == 'SELECT' and selected:
            match['esco_code'] = selected['esco_code']
            match['esco_label'] = selected['preferred_label']
            match['matched_label'] = selected['label']
            match['similarity'] = selected['similarity']
            match['category'] = 'step_2b_matched'
            stats['selected'] += 1
        elif decision == 'NONE':
            match['category'] = 'new_local'
            stats['none'] += 1
        else:
            match['category'] = 'step_2b_error'
            stats['error'] += 1

        time.sleep(0.1)

    print(f"\nStep 2B Results:")
    print(f"  Selected better match: {stats['selected']} ({100*stats['selected']/max(len(needs_2b),1):.1f}%)")
    print(f"  No match (new_local): {stats['none']} ({100*stats['none']/max(len(needs_2b),1):.1f}%)")
    print(f"  Errors: {stats['error']}")

    return matches


# =============================================================================
# SAVE RESULTS
# =============================================================================

def save_results(matches):
    """Save final results to Excel and JSON."""
    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)

    # Transform to final format
    final_data = []
    decision_map = {
        'exact': 'exact',
        'exact_upgraded': 'exact_crosswalk_fix',
        'llm_approved': 'approved',
        'step_2b_matched': 'selected',
        'new_local': 'new_local'
    }
    phase_map = {
        'exact': '1A',
        'exact_upgraded': '1B',
        'llm_approved': '2A',
        'step_2b_matched': '2B',
        'new_local': '2B'
    }

    for m in matches:
        final_data.append({
            'kesco_code': m.get('kesco_code'),
            'kesco_title': m.get('kesco_title'),
            'isco_code': m.get('isco_code'),
            'esco_code': m.get('esco_code', ''),
            'esco_label': m.get('esco_label', ''),
            'matched_label': m.get('matched_label', ''),
            'similarity': round(m.get('similarity', 0), 4),
            'decision': decision_map.get(m.get('category', ''), m.get('category', '')),
            'decision_phase': phase_map.get(m.get('category', ''), 'unknown')
        })

    df = pd.DataFrame(final_data)
    df = df.sort_values('kesco_code')

    # Save Excel
    with pd.ExcelWriter(OUTPUT_EXCEL, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='All_Matches', index=False)

        matched = df[df['decision'] != 'new_local']
        matched.to_excel(writer, sheet_name='ESCO_Matched', index=False)

        new_local = df[df['decision'] == 'new_local']
        new_local.to_excel(writer, sheet_name='New_Local', index=False)

        # Summary
        summary_data = [
            {'Metric': 'Total', 'Value': len(df)},
            {'Metric': 'ESCO Matched', 'Value': len(matched)},
            {'Metric': 'New Local', 'Value': len(new_local)},
            {'Metric': 'Generated', 'Value': datetime.now().isoformat()}
        ]
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)

    print(f"  Saved Excel: {OUTPUT_EXCEL}")

    # Save JSON
    output_data = {
        'metadata': {
            'pipeline': 'KeSCO to ESCO Full Matching',
            'generated_at': datetime.now().isoformat(),
            'total_matches': len(matches),
            'esco_matched': len(matched),
            'new_local': len(new_local)
        },
        'matches': matches
    }
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved JSON: {OUTPUT_JSON}")

    # Save review items (new_local + low similarity approved items)
    review_items = []
    for m in matches:
        category = m.get('category', '')
        similarity = m.get('similarity', 0)
        # Include: new_local OR approved but low similarity
        if category == 'new_local' or (category == 'llm_approved' and similarity < LOW_SIM_THRESHOLD):
            review_items.append(m)

    review_data = {
        'metadata': {
            'source': 'KeSCO Matching Pipeline',
            'generated_at': datetime.now().isoformat(),
            'total_items': len(review_items),
            'description': 'Occupations requiring human review (new_local + low similarity approved)'
        },
        'items': review_items
    }
    with open(OUTPUT_REVIEW_JSON, 'w', encoding='utf-8') as f:
        json.dump(review_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved review JSON: {OUTPUT_REVIEW_JSON}")

    review_excel_data = []
    for m in review_items:
        review_excel_data.append({
            'kesco_code': m.get('kesco_code'),
            'kesco_title': m.get('kesco_title'),
            'isco_code': m.get('isco_code', ''),
            'suggested_esco_code': m.get('esco_code', ''),
            'suggested_esco_label': m.get('esco_label', ''),
            'similarity': m.get('similarity', 0),
            'category': m.get('category', '')
        })
    pd.DataFrame(review_excel_data).to_excel(OUTPUT_REVIEW_EXCEL, index=False)
    print(f"  Saved review Excel: {OUTPUT_REVIEW_EXCEL}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 70)
    print("KESCO TO ESCO FULL MATCHING PIPELINE")
    print("=" * 70)
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
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)

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
    save_results(matches)

    print(f"\nCompleted: {datetime.now().isoformat()}")
    print("=" * 70)


if __name__ == '__main__':
    main()
