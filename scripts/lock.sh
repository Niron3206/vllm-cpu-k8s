#!/usr/bin/env bash
# пересобираем requirements.txt для обоих образов
# uv крутится в контейнере
# уже записанные версии uv сохраняет; обновить всё разом: ./scripts/lock.sh --upgrade
set -euo pipefail

UV_IMAGE=ghcr.io/astral-sh/uv:0.12.24-python3.12-trixie-slim@sha256:c45e18882c3b26a1631ac8b64537a2213e301b752edaa2471d32226090ccaafe
cache="${XDG_CACHE_HOME:-$HOME/.cache}/uv"

cd "$(dirname "$0")/.."
mkdir -p "$cache"

uv() {
    docker run --rm -u "$(id -u):$(id -g)" \
        -v "$PWD:/src" -w /src \
        -v "$cache:/uv-cache" -e UV_CACHE_DIR=/uv-cache \
        "$UV_IMAGE" uv "$@"
}

uv pip compile docker/vllm/requirements.in \
    --python-version 3.12 --python-platform x86_64-manylinux_2_39 \
    --torch-backend cpu --generate-hashes --quiet "$@" \
    -o docker/vllm/requirements.txt

# загрузчик собирается на alpine, отсюда musl.
uv pip compile docker/downloader/requirements.in \
    --python-version 3.12 --python-platform x86_64-unknown-linux-musl \
    --generate-hashes --quiet "$@" \
    -o docker/downloader/requirements.txt
