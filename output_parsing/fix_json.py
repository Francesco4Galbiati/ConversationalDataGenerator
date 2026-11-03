import json

INPUT_FILE = "./output_parsing/input.jsonl"
OUTPUT_FILE = "./output_parsing/output_fixed.jsonl"


def normalize_value(v):
    if isinstance(v, list):
        return v[0] if len(v) > 0 else None
    return v


count_in = 0
count_out = 0

with open(INPUT_FILE, "r", encoding="utf-8") as fin, \
     open(OUTPUT_FILE, "w", encoding="utf-8") as fout:

    for line in fin:
        count_in += 1
        line = line.strip()

        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"Skipping invalid JSON on line {count_in}: {e}")
            continue

        fixed = {}
        for k, v in data.items():
            fixed[k] = normalize_value(v)

        fout.write(json.dumps(fixed) + "\n")
        count_out += 1


print(f"Processed {count_in} lines → wrote {count_out} lines")