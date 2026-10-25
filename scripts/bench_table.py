"""собирает markdown таблицу из строк RESULT в логе Job vllm-bench (читает stdin)"""

import json
import sys

COLUMNS = [
    ("Сценарий", lambda r: r["name"]),
    ("Вход / выход, ток.", lambda r: f'{r["input"]} / {r["output"]}'),
    ("Одновр.", lambda r: r["concurrency"]),
    ("TTFT p50 / p99, с", lambda r: f'{r["p50_ttft_ms"] / 1000:.2f} / {r["p99_ttft_ms"] / 1000:.2f}'),
    ("TPOT p50, мс", lambda r: f'{r["p50_tpot_ms"]:.0f}'),
    ("Latency p50 / p99, с", lambda r: f'{r["p50_e2el_ms"] / 1000:.1f} / {r["p99_e2el_ms"] / 1000:.1f}'),
    ("Запросов/с", lambda r: f'{r["request_throughput"]:.2f}'),
    ("Выход, ток/с", lambda r: f'{r["output_throughput"]:.1f}'),
    ("Всего, ток/с", lambda r: f'{r["total_token_throughput"]:.1f}'),
]

rows = [json.loads(line[len("RESULT "):]) for line in sys.stdin if line.startswith("RESULT ")]
print("| " + " | ".join(name for name, _ in COLUMNS) + " |")
print("|" + "---|" * len(COLUMNS))
for row in rows:
    print("| " + " | ".join(str(cell(row)) for _, cell in COLUMNS) + " |")
