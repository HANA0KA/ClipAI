import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// El .env compartido con el servicio Python vive en la raíz del proyecto.
loadEnvConfig(path.resolve(process.cwd(), ".."));
const MEDIA_API_URL = (process.env.MEDIA_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Videos, miniaturas y descargas los sirve FastAPI; el navegador los pide
  // al mismo origen (/media/...) y Next los reenvía, con soporte de Range.
  async rewrites() {
    return [{ source: "/media/:path*", destination: `${MEDIA_API_URL}/:path*` }];
  },
  serverExternalPackages: ["better-sqlite3", "@prisma/adapter-better-sqlite3"],
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  poweredByHeader: false,
};

export default nextConfig;
