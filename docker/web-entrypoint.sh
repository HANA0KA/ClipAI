#!/bin/sh
# Prepara la base de datos (volumen /app/db) y arranca la interfaz en :3000.
set -eu
DB=/app/db/app.db
LEGACY=/app/data/app.db

# Primera vez: si venías de ./start.sh, importa tu base de datos (copia consistente;
# el original no se toca). SQLite en WAL compartido entre contenedores no es fiable
# sobre bind mounts de macOS/Windows, por eso la BD vive en un volumen propio.
if [ ! -f "$DB" ] && [ -f "$LEGACY" ]; then
  echo "▸ Importando la base de datos de ./data/app.db"
  sqlite3 "$LEGACY" ".backup '$DB'"
fi

# Copia de seguridad antes de migrar (solo si hay migraciones pendientes).
if [ -f "$DB" ] && ! npx prisma migrate status >/dev/null 2>&1; then
  mkdir -p /app/data/backups
  cp "$DB" "/app/data/backups/app-antes-de-migrar-$(date +%Y%m%d-%H%M%S).db"
  echo "▸ Copia de seguridad en data/backups/"
fi

echo "▸ Aplicando migraciones de la base de datos"
npx prisma migrate deploy
exec npx next start -H 0.0.0.0 -p 3000
