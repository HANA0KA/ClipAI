# Interfaz de ClipAI (Next.js + Prisma). Contexto de construcción: la raíz del repo.
FROM node:24-bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# La URL del servicio de procesamiento queda fija en la compilación (reenvío /media/*).
ARG MEDIA_API_URL=http://media:8000
ENV MEDIA_API_URL=$MEDIA_API_URL NEXT_TELEMETRY_DISABLED=1 DATABASE_URL=file:/tmp/build.db
RUN npx prisma generate && npm run build

FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 curl tini \
    && rm -rf /var/lib/apt/lists/*
# Misma disposición que en el repo: /app/web (cwd) y /app/data (DATA_DIR) para que
# las rutas relativas (`../data`, `.env` compartido) resuelvan igual.
WORKDIR /app/web
COPY --from=build --chown=1000:1000 /app/web ./
# La web lee las plantillas de subtítulos de media/templates.
COPY --chown=1000:1000 media/templates /app/media/templates
COPY --chown=1000:1000 docker/web-entrypoint.sh /usr/local/bin/web-entrypoint
RUN chmod +x /usr/local/bin/web-entrypoint && mkdir -p /app/data /app/db && chown 1000:1000 /app/data /app/db
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 CHECKPOINT_DISABLE=1 HOME=/tmp
USER 1000:1000
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--", "web-entrypoint"]
