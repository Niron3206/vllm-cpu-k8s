# cpu колесу vllm нужен glibc >= 2.39, в bookworm только 2.36, поэтому trixie
ARG BASE=python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704


FROM ${BASE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/uv
# баайткод компилируем при сборке, в поде корневая ФС только на чтение
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
RUN uv venv /opt/venv --python /usr/local/bin/python3.12
COPY docker/vllm/requirements.txt /tmp/requirements.txt
# --torch-backend cpu: пакеты torch с суффиксом +cpu берутся с индекса pytorch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv --require-hashes --no-deps --torch-backend cpu \
        -r /tmp/requirements.txt
COPY plugin /tmp/plugin
RUN uv pip install --python /opt/venv --no-deps --no-build-isolation /tmp/plugin \
    && uv pip check --python /opt/venv


FROM ${BASE} AS runtime
# g++ нужен в рантайме, т.к. triton-cpu и torch.compile собирают ядра на лету,
# без компилятора vllm падает на первом же запросе.
RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ libnuma1 libtcmalloc-minimal4t64 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 vllm \
    && useradd --uid 10001 --gid vllm --home-dir /home/vllm --create-home \
        --shell /usr/sbin/nologin vllm
COPY --from=build /opt/venv /opt/venv
COPY k8s/config/logging.json /etc/vllm/logging.json
# HF_HUB_OFFLINE: веса только с тома, в Hugging Face основной контейнер не ходит
ENV PATH=/opt/venv/bin:$PATH \
    LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4:/opt/venv/lib/libiomp5.so \
    VLLM_LOGGING_CONFIG_PATH=/etc/vllm/logging.json \
    HF_HUB_OFFLINE=1 \
    VLLM_NO_USAGE_STATS=1 \
    DO_NOT_TRACK=1 \
    HOME=/home/vllm \
    PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /home/vllm
EXPOSE 8000
ENTRYPOINT ["vllm", "serve"]


FROM runtime AS test
COPY plugin/tests /tests
RUN python -m unittest discover -s /tests -v
