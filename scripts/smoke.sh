#!/usr/bin/env bash
# проверка развёрнутого сервиса.
# авторизация, ответ модели и что текст запроса
# и ответа не попал в логи, а сам факт запроса попал
set -euo pipefail

cd "$(dirname "$0")/.."

ns=llm
port=${PORT:-8000}
url=http://127.0.0.1:$port
token=$(grep '^VLLM_API_KEY=' k8s/secrets.env | cut -d= -f2-)
model=$(grep '^SERVED_MODEL_NAME=' k8s/config/vllm.env | cut -d= -f2-)

kubectl -n "$ns" port-forward svc/vllm "$port:8000" >/dev/null &
pf=$!
trap 'kill $pf' EXIT
for _ in $(seq 30); do
    curl -sf "$url/health" >/dev/null && break
    sleep 1
done

failed=0
ok() { echo "ok    $1"; }
fail() { echo "FAIL  $1"; failed=1; }
expect() {
    if [ "$2" = "$3" ]; then ok "$1"; else fail "$1: ждали $2, получили $3"; fi
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

expect "/health без токена" 200 "$(status "$url/health")"
expect "/v1/models без токена" 401 "$(status "$url/v1/models")"
expect "/v1/models с чужим токеном" 401 "$(status -H 'Authorization: Bearer wrong' "$url/v1/models")"
expect "/invocations без токена" 401 "$(status -X POST -H 'Content-Type: application/json' -d '{}' "$url/invocations")"
expect "/metrics без токена" 401 "$(status "$url/metrics")"

canary="canary-$RANDOM-$RANDOM"
body=$(printf '{"model": "%s", "max_tokens": 32, "temperature": 0, "messages": [{"role": "user", "content": "Repeat exactly: %s"}]}' "$model" "$canary")
response=$(curl -s -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d "$body" "$url/v1/chat/completions")
read -r id answer < <(python3 -c 'import json, sys; r = json.load(sys.stdin); print(r["id"], r["choices"][0]["message"]["content"])' <<<"$response") \
    || { fail "ответ chat/completions: $response"; exit 1; }
ok "chat/completions с токеном: $answer"

logs=$(kubectl -n "$ns" logs deploy/vllm --all-containers)
if grep -qF "$canary" <<<"$logs"; then fail "промпт попал в логи"; else ok "промпта нет в логах"; fi
if grep -qF "$answer" <<<"$logs"; then fail "ответ модели попал в логи"; else ok "ответа модели нет в логах"; fi
if grep -qF "request $id" <<<"$logs"; then ok "факт запроса $id есть в логах"; else fail "запроса $id нет в логах"; fi
if grep -qF "response $id" <<<"$logs"; then ok "строка об ответе есть в логах"; else fail "строки об ответе $id нет в логах"; fi

expect "uid процесса vLLM" 10001 "$(kubectl -n "$ns" exec deploy/vllm -c vllm -- id -u)"

exit $failed
