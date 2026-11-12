#!/bin/bash
# Run OntoPFAS generations ONE AFTER ANOTHER, unattended.
#   default (10 Nov): 10,000 triples, one-to-one, code-driven intent selection,
#   full contract. Each run is then parsed to RDF and evaluated.
# usage (repo root, on the VPN, Mac plugged in with the lid open):
#   bash tools/run_night.sh
#   bash tools/run_night.sh sched_weighted_10k            # only some of the runs
# To use optional settings, put them in front, e.g.:
#   CDG_NUM_CTX=16384 CDG_THINK=low bash tools/run_night.sh
# Before each run it checks that the model answers; if not, it waits (re-checking every 10 min, up to 6 h).
# A log of what ran, when, and in which output folder: resources/output/night_<date>.log

cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate || exit 1

# long waits before retrying: survives a server outage of ~30 min on any single call
export CDG_RETRY_WAITS="${CDG_RETRY_WAITS:-30,60,120,300,600,900}"
LOG="resources/output/night_$(date +%Y%m%d_%H%M).log"
HOST='https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama'
KEY=$(grep -o "sk-[a-z0-9]*" conf.py | head -1)

echo "$(date '+%F %T') night runs; CDG_RETRY_WAITS=$CDG_RETRY_WAITS CDG_NUM_CTX=${CDG_NUM_CTX:-unset} CDG_THINK=${CDG_THINK:-unset}" | tee -a "$LOG"

# keep the Mac awake while this script runs
caffeinate -i -w $$ &

# wait for a run that is still going (it uses the same Redis)
while pgrep -f "python.*main.py" > /dev/null; do
    echo "$(date '+%T') waiting for the run in progress to finish..."; sleep 60
done

redis-cli ping > /dev/null || { echo "Redis is not running: start it with 'redis-server --daemonize yes'" | tee -a "$LOG"; exit 1; }

# returns 0 when the model answers a tiny request
server_ok() {
    curl -s -m 300 "$HOST/api/chat" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
        -d '{"model": "gpt-oss:120b", "messages": [{"role": "user", "content": "Say OK"}], "stream": false}' \
        | grep -q '"done":true'
}

wait_for_server() {
    for i in $(seq 1 36); do                     # 36 x 10 min = 6 hours
        if server_ok; then return 0; fi
        echo "$(date '+%F %T') server not answering, re-checking in 10 min ($i/36)" | tee -a "$LOG"
        sleep 600
    done
    return 1
}

run() {
    label=$1; shift
    if ! wait_for_server; then
        echo "$(date '+%F %T') SKIP  $label: server down for 6 hours" | tee -a "$LOG"; return
    fi
    echo "$(date '+%F %T') START $label: python main.py $*" | tee -a "$LOG"
    python main.py "$@" > "resources/output/night_${label}.out" 2>&1
    rc=$?
    folder=$(ls -d resources/output/run_* | sort | tail -1)   # folder names are timestamps
    echo "$(date '+%F %T') END   $label exit=$rc folder=$folder" | tee -a "$LOG"
    tail -6 "$folder/output.txt" | sed 's/^/      /' >> "$LOG"
    # RDF + structural evaluation (never stops the night if it fails)
    if [ -f "$folder/triples.json" ]; then
        python output_parsing/parser_ontopfas.py "$folder/triples.json" "$folder/output.ttl" >> "$LOG" 2>&1 &&
        python evaluate_pragmatic_quality.py --reference resources/reference/ontopfas_reference.ttl \
            --synthetic "$folder/output.ttl" --questions competency_questions/ontopfas/manifest_generation.json \
            --output-dir "$folder/evaluation" --no-progress > /dev/null 2>&1 &&
        echo "      evaluation written to $folder/evaluation" >> "$LOG" ||
        echo "      (parsing or evaluation failed, run it by hand)" >> "$LOG"
    fi
    sleep 30   # let the server breathe between runs
}

# (macOS ships bash 3.2: no associative arrays, so a case statement)
args_for() {
    case "$1" in
        sched_full_10k)     echo "--contract OntoPFAS_contract.yaml --conversation 1 --target 10000 --intent_selection schedule" ;;
        model_full_10k)     echo "--contract OntoPFAS_contract.yaml --conversation 1 --target 10000" ;;
        sched_weighted_10k) echo "--contract OntoPFAS_contract_weighted.yaml --conversation 1 --target 10000 --intent_selection schedule" ;;
        minimal_MtoM) echo "--contract OntoPFAS_minimal_contract.yaml --conversation 4 --target 1000" ;;
        full_1to1)    echo "--contract OntoPFAS_contract.yaml --conversation 1 --target 1000" ;;
        full_MtoM)    echo "--contract OntoPFAS_contract.yaml --conversation 4 --target 1000" ;;
        minimal_1to1) echo "--contract OntoPFAS_minimal_contract.yaml --conversation 1 --target 1000" ;;
    esac
}
RUNS="$*"
[ -z "$RUNS" ] && RUNS="sched_full_10k"

for r in $RUNS; do
    a=$(args_for "$r")
    [ -n "$a" ] || { echo "unknown run '$r' (use: sched_full_10k model_full_10k sched_weighted_10k minimal_MtoM full_1to1 full_MtoM minimal_1to1)" | tee -a "$LOG"; continue; }
    run "$r" $a
done

echo "$(date '+%F %T') all done" | tee -a "$LOG"
