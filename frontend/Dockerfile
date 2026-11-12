# syntax=docker/dockerfile:1
ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --strict-ssl=true
COPY . .
ARG OPENLIMS_VERSION=development
RUN if [ "$OPENLIMS_VERSION" = development ]; then npm run build; else VITE_OPENLIMS_VERSION="${OPENLIMS_VERSION#v}" npm run build; fi

FROM ${NGINX_IMAGE}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -Y off -q -O /dev/null http://127.0.0.1/ || exit 1

ARG OPENLIMS_VERSION=development
ARG OPENLIMS_REVISION=unknown
ARG OPENLIMS_SOURCE=https://github.com/Mokey2002/OpenLIMS
LABEL org.opencontainers.image.version=${OPENLIMS_VERSION} \
      org.opencontainers.image.revision=${OPENLIMS_REVISION} \
      org.opencontainers.image.source=${OPENLIMS_SOURCE} \
      org.opencontainers.image.licenses=Apache-2.0
