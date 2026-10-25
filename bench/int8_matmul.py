"""время int8-матмула vllm (oneDNN) в зависимости от числа строк M

матрица как у mlp слоя Qwen2.5-1.5B (K=1536, N=8960), активации bf16 квантуются на лету, как в W8A8-модели. 
Запуск в демоне minikube:
  docker run --rm -i --cpus 8 -e OMP_NUM_THREADS=8 --entrypoint python vllm-cpu:0.32.0 - < bench/int8_matmul.py
"""

import time

import torch
from vllm import _custom_ops as ops
from vllm.platforms import current_platform

current_platform.import_kernels()
torch.manual_seed(0)

K, N = 1536, 8960
# как в vllm. Веса [K, N] - транспонированный вид тензора [N, K]
w = torch.randint(-127, 128, (N, K), dtype=torch.int8).t()
w_scale = torch.rand(N, 1) * 0.01


def bench(handler, m, symmetric, adj):
    x = torch.randn(m, K, dtype=torch.bfloat16)
    out = torch.empty(m, N, dtype=torch.bfloat16)

    def step():
        xq, xs, xzp = ops.onednn_scaled_int8_quant(x, None, None, symmetric)
        ops.onednn_scaled_mm(handler, xq, out, xs, xzp, adj, None)

    for _ in range(3):
        step()
    n = 20 if m <= 128 else 5
    start = time.perf_counter()
    for _ in range(n):
        step()
    return (time.perf_counter() - start) / n * 1000

for symmetric in (True, False):
    handler = ops.create_onednn_scaled_mm(w, w_scale, torch.bfloat16, True, not symmetric, 32)
    adj = None if symmetric else w.sum(dim=0, keepdim=True, dtype=torch.float32) * w_scale.squeeze()
    sizes = (1, 2, 4, 8, 16, 32, 128, 512, 2048, 8192) if symmetric else (1, 2, 4, 8, 16, 32, 128)
    print("symmetric (как у модели)" if symmetric else "asymmetric")
    for m in sizes:
        ms = bench(handler, m, symmetric, adj)
        print(f"  M={m:5d}: {ms:7.1f} ms, {ms / m * 1000:7.1f} us/row")
