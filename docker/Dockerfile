FROM python:3.14

RUN apt-get update \
  && apt-get install --yes --no-install-recommends \
    tini \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

RUN useradd --create-home appuser

USER appuser

RUN mkdir /home/appuser/app && \
    mkdir --parents /home/appuser/.cache/uv

WORKDIR /home/appuser/app

ARG GIT_COMMIT
ENV GIT_COMMIT=$GIT_COMMIT \
    POTTO__BIND_HOST=0.0.0.0 \
    POTTO__BIND_PORT=3001 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_SYNC=true \
    UV_LOCKED=true \
    UV_PYTHON=3.14

RUN --mount=type=cache,uid=1000,gid=1000,target=/home/appuser/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY --chown=appuser:appuser . .

RUN --mount=type=cache,uid=1000,gid=1000,target=/home/appuser/.cache/uv \
    uv sync --locked

RUN echo $GIT_COMMIT > /home/appuser/git-commit.txt

EXPOSE 3001

ENTRYPOINT ["tini", "-g", "--", "uv", "run", "potto"]

CMD ["run-server"]
