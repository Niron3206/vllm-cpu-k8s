#!/usr/bin/env bash
# прогоняет сценарии из scenarios.txt через vllm bench serve
# после каждого сценария печатает строку "RESULT {json}", её разбирает scripts/bench_table.py
set -euo pipefail

grep -v '^#' /bench/scenarios.txt | while read -r name input output concurrency prompts; do
    [ -n "$name" ] || continue
    echo "=== $name: input=$input output=$output concurrency=$concurrency prompts=$prompts"
    # промпты случайные, длина ответа фиксирована (--ignore-eos)
    # прогрев с той же конкурентностью. triton-cpu компилирует ядра под каждую новую форму батча,
    # без прогрева компиляция попала бы в замер
    vllm bench serve \
        --backend vllm --base-url http://vllm:8000 \
        --model "$MODEL_DIR" --served-model-name "$SERVED_MODEL_NAME" \
        --dataset-name random --random-input-len "$input" --random-output-len "$output" \
        --ignore-eos --num-warmups "$concurrency" --seed 0 --ready-check-timeout-sec 600 \
        --max-concurrency "$concurrency" --num-prompts "$prompts" --request-rate inf \
        --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,99 \
        --disable-tqdm --save-result --result-dir /tmp/results --result-filename "$name.json" \
        </dev/null
    python - "$name" "$input" "$output" "$concurrency" "/tmp/results/$name.json" <<'PY'
import json, sys

name, inp, out, conc, path = sys.argv[1:]
r = json.load(open(path))
keys = [
    "completed", "duration", "request_throughput", "output_throughput", "total_token_throughput",
    "p50_ttft_ms", "p99_ttft_ms", "p50_tpot_ms", "p99_tpot_ms", "p50_e2el_ms", "p99_e2el_ms",
]
row = {"name": name, "input": int(inp), "output": int(out), "concurrency": int(conc)}
row.update({k: r.get(k) for k in keys})
print("RESULT " + json.dumps(row))
PY
done
