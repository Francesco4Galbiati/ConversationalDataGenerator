import json

input_file = "./resources/output/noria/llama3.3:70b/1to1/5000t/triples.json"
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