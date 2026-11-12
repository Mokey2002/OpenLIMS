# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    clustalo \
    ncbi-blast+ \
    libglib2.0-0 \
    libgl1 \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt

COPY . /app

ARG OPENLIMS_VERSION=development
ARG OPENLIMS_REVISION=unknown
ARG OPENLIMS_SOURCE=https://github.com/Mokey2002/OpenLIMS
ENV OPENLIMS_VERSION=${OPENLIMS_VERSION}
LABEL org.opencontainers.image.version=${OPENLIMS_VERSION} \
      org.opencontainers.image.revision=${OPENLIMS_REVISION} \
      org.opencontainers.image.source=${OPENLIMS_SOURCE} \
      org.opencontainers.image.licenses=Apache-2.0
RUN printf '%s\n' "$OPENLIMS_VERSION" > /app/VERSION
