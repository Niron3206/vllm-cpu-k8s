#!/usr/bin/env bash
# нагрузочный тест в кластере
# лог и таблицу в bench/results/<время>.{log,md}
set -euo pipefail

cd "$(dirname "$0")/.."

ns=llm
out=bench/results/$(date +%Y%m%d-%H%M%S)
mkdir -p bench/results

kubectl -n "$ns" delete job vllm-bench --ignore-not-found
kubectl apply -k bench
kubectl -n "$ns" rollout status deploy/vllm --timeout=10m


while true; do
    state=$(kubectl -n "$ns" get job vllm-bench \
        -o jsonpath='{.status.conditions[?(@.status=="True")].type}')
    case "$state" in
        *Complete*) break ;;
        *Failed*) echo "Job vllm-bench упал, лог: $out.log" >&2; break ;;
    esac
    sleep 15
done

kubectl -n "$ns" logs job/vllm-bench > "$out.log"
python3 scripts/bench_table.py < "$out.log" | tee "$out.md"