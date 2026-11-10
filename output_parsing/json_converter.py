import json

input_file = "./resources/output/HealthEQKG/gpt-oss:120b/1to1/10000t/1/triples.json"
output_file = "./output_parsing/input.jsonl"

with open(input_file, "r") as f, open(output_file, "w") as out:
    for line in f:
        if ":" not in line:
            continue

        intent, json_part = line.split(":", 1)
        intent = intent.strip()
        data = json.loads(json_part.strip())

        data["intent"] = intent

        out.write(json.dumps(data) + "\n")