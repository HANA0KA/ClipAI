import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import { PrismaClient } from "@/lib/generated/prisma/client";
import { databaseFile } from "@/lib/paths";

// Un solo cliente por proceso (el hot reload de `next dev` re-evalúa módulos).
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

function createClient(): PrismaClient {
  // ISO 8601 es el formato por defecto del adaptador; media/services/db.py
  // escribe las fechas con el mismo formato.
  const adapter = new PrismaBetterSqlite3({ url: `file:${databaseFile()}`, timeout: 5000 });
  return new PrismaClient({ adapter });
}

export const prisma = globalForPrisma.prisma ?? createClient();
if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
