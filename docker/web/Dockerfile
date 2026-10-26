ARG BASE=python:3.12-alpine@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d

FROM ${BASE} AS build
COPY docker/web/requirements.txt /tmp/requirements.txt
RUN python -m venv --without-pip /opt/venv \
    && pip --python /opt/venv/bin/python install --no-cache-dir --root-user-action=ignore \
        --disable-pip-version-check --require-hashes --no-deps -r /tmp/requirements.txt


FROM ${BASE} AS runtime
RUN addgroup -g 10001 chat \
    && adduser -D -H -u 10001 -G chat -s /sbin/nologin chat
COPY --from=build /opt/venv /opt/venv
COPY web/app /app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
WORKDIR /app
EXPOSE 8080
ENTRYPOINT ["uvicorn", "chat:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]


FROM runtime AS test
COPY web/tests /tests
RUN python -m unittest discover -s /tests -v
