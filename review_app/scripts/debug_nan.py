"""Debug NaN values in source data."""

import json
import math
from pathlib import Path

data_file = Path(__file__).parent.parent.parent / "countries" / "argentina_cno2017" / "outputs" / "arg_cno2017_matches_final.json"

with open(data_file, "r", encoding="utf-8") as f:
    data = json.load(f)

new_locals = [m for m in data["matches"] if m.get("category") == "new_local"]

print(f"Total new_local items: {len(new_locals)}")

# Check ALL items for any NaN/inf values
problem_count = 0
for i, m in enumerate(new_locals):
    for k, v in m.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            print(f"Item {i} ({m['cno_code']}): {k} = {v}")
            problem_count += 1

print(f"\nTotal problems found: {problem_count}")

# Also check items 200-210 specifically
print("\nItems 200-210:")
for i in range(200, min(210, len(new_locals))):
    m = new_locals[i]
    print(f"  {i}: {m['cno_code']} - similarity: {m.get('similarity')}")
