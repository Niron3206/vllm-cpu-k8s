ARG BASE=python:3.12-alpine@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d

FROM ${BASE} AS build
COPY docker/downloader/requirements.txt /tmp/requirements.txt
RUN python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install --no-cache-dir --root-user-action=ignore \
        --disable-pip-version-check --require-hashes --no-deps -r /tmp/requirements.txt

FROM ${BASE}
RUN addgroup -g 10001 downloader \
    && adduser -D -H -u 10001 -G downloader -s /sbin/nologin downloader
COPY --from=build /opt/venv /opt/venv
COPY docker/downloader/download_model.py /app/download_model.py
ENV PATH=/opt/venv/bin:$PATH \
    HF_HOME=/tmp/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "/app/download_model.py"]
