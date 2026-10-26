#!/usr/bin/env bash
# проверка развёрнутого веб-чата (kubectl apply -k web)
# пароль, защита от чужих сайтов, что токен vllm не уходит в браузер,
# стриминг, отмена генерации при обрыве и что текстов нет в логах
set -euo pipefail

cd "$(dirname "$0")/.."

ns=llm
port=${PORT:-8080}
url=http://127.0.0.1:$port
password=$(grep '^CHAT_PASSWORD=' web/secrets.env | cut -d= -f2-)
token=$(grep '^VLLM_API_KEY=' k8s/secrets.env | cut -d= -f2-)

kubectl -n "$ns" port-forward svc/chat "$port:8080" >/dev/null &
pf=$!
trap 'kill $pf' EXIT
for _ in $(seq 30); do
    curl -sf "$url/healthz" >/dev/null && break
    sleep 1
done

failed=0
ok() { echo "ok    $1"; }
fail() { echo "FAIL  $1"; failed=1; }
expect() {
    if [ "$2" = "$3" ]; then ok "$1"; else fail "$1: ждали $2, получили $3"; fi
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
chat() { curl -sN -u "user:$password" -H 'Content-Type: application/json' "$@" "$url/api/chat"; }

expect "/healthz без пароля" 200 "$(status "$url/healthz")"
expect "/ без пароля" 401 "$(status "$url/")"
expect "/ с чужим паролем" 401 "$(status -u user:wrong "$url/")"
expect "/ с паролем" 200 "$(status -u "user:$password" "$url/")"
expect "/api/chat без пароля" 401 "$(status -H 'Content-Type: application/json' -d '{}' "$url/api/chat")"

# браузер подставит Basic-пароль и в форму с чужого сайта
expect "/api/chat как форма (text/plain)" 415 "$(status -u "user:$password" -H 'Content-Type: text/plain' -d '{}' "$url/api/chat")"
expect "/api/chat с чужого сайта" 403 "$(status -u "user:$password" -H 'Content-Type: application/json' -H 'Sec-Fetch-Site: cross-site' -d '{}' "$url/api/chat")"

# наружу только /api/chat, остальной API vllm через чат недоступен
expect "/v1/models через чат" 404 "$(status -u "user:$password" "$url/v1/models")"
expect "/v1/chat/completions через чат" 405 "$(status -u "user:$password" -H 'Content-Type: application/json' -d '{}' "$url/v1/chat/completions")"
expect "/invocations через чат" 405 "$(status -u "user:$password" -H 'Content-Type: application/json' -d '{}' "$url/invocations")"

seen=$(for path in / /chat.js /chat.css; do curl -si -u "user:$password" "$url$path"; done
    curl -si -u "user:$password" -H 'Content-Type: application/json' -d '{"messages": []}' "$url/api/chat")
if grep -qF "$token" <<<"$seen"; then fail "токен vllm ушёл в браузер"; else ok "токена vllm нет в ответах браузеру"; fi

# ексли прокси копит ответ, все чанки придут разом
summary='
import json, sys, time
first = last = None
chunks, finished, parts, rid = 0, 0, [], "-"
for line in sys.stdin:
    if not line.startswith("data: "):
        continue
    last = time.monotonic()
    first = first or last
    data = line[6:].strip()
    if data == "[DONE]":
        finished = 1
        break
    chunk = json.loads(data)
    rid = chunk["id"]
    chunks += 1
    if chunk["choices"]:
        parts.append(chunk["choices"][0]["delta"].get("content") or "")
span = last - first if first else 0
print(rid, chunks, f"{span:.1f}", finished, "".join(parts).replace("\n", " "))
'
canary="canary-$RANDOM-$RANDOM"
body=$(printf '{"max_tokens": 32, "temperature": 0, "messages": [{"role": "user", "content": "Repeat exactly: %s"}]}' "$canary")
read -r id chunks span finished answer < <(chat -d "$body" | python3 -c "$summary") \
    || { fail "стрим не разобрался"; exit 1; }
expect "стрим закончился [DONE]" 1 "$finished"
if [ "$chunks" -ge 3 ]; then ok "стрим: $chunks чанков за $span с: $answer"; else fail "стрим: всего $chunks чанков"; fi
if python3 -c "import sys; sys.exit(float(sys.argv[1]) < 1)" "$span"; then
    ok "чанки приходят по мере генерации"
else
    fail "все чанки пришли разом, прокси буферизует ответ"
fi

# читаем первый чанк и закрываем соединение, как кнопка "Стоп"
first_chunk='
import json, sys
for line in sys.stdin:
    if line.startswith("data: {"):
        print(json.loads(line[6:])["id"])
        break
'
body='{"max_tokens": 300, "messages": [{"role": "user", "content": "Write a long story about a lighthouse."}]}'
abort_id=$(chat -d "$body" | python3 -c "$first_chunk" || true)
aborted=0
for _ in $(seq 15); do
    if kubectl -n "$ns" logs deploy/vllm -c vllm --since=5m | grep -qF "Request $abort_id aborted"; then
        aborted=1
        break
    fi
    sleep 1
done
expect "обрыв клиента снимает запрос в vllm ($abort_id)" 1 "$aborted"

no_text_in_logs() {
    if grep -qF "$canary" <<<"$2"; then fail "промпт попал в логи $1"; else ok "промпта нет в логах $1"; fi
    if [ -n "$answer" ] && grep -qF "$answer" <<<"$2"; then
        fail "ответ модели попал в логи $1"
    else
        ok "ответа модели нет в логах $1"
    fi
}
vllm_logs=$(kubectl -n "$ns" logs deploy/vllm --all-containers)
no_text_in_logs chat "$(kubectl -n "$ns" logs deploy/chat)"
no_text_in_logs vllm "$vllm_logs"
if grep -qF "request $id" <<<"$vllm_logs"; then ok "vllm записал запрос $id от чата"; else fail "запроса $id нет в логах vllm"; fi

expect "uid процесса чата" 10001 "$(kubectl -n "$ns" exec deploy/chat -c chat -- id -u)"

exit $failed
