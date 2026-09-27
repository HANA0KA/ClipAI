import path from "node:path";
import { config } from "dotenv";
import { defineConfig } from "prisma/config";

// El .env vive en la raíz del proyecto (compartido con el servicio Python).
const root = path.resolve(process.cwd(), "..");
config({ path: path.join(root, ".env"), quiet: true });

function databaseUrl(): string {
  const raw = process.env.DATABASE_URL;
  if (raw && raw.startsWith("file:")) {
    const file = raw.slice("file:".length);
    return `file:${path.isAbsolute(file) ? file : path.resolve(root, file)}`;
  }
  const dataDir = path.resolve(root, process.env.DATA_DIR || "./data");
  return `file:${path.join(dataDir, "app.db")}`;
}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: { url: databaseUrl() },
});
