-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_Project" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "sourceType" TEXT NOT NULL,
    "sourceUrl" TEXT,
    "title" TEXT,
    "durationSec" INTEGER,
    "language" TEXT,
    "folder" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'QUEUED',
    "progress" INTEGER NOT NULL DEFAULT 0,
    "stage" TEXT,
    "error" TEXT,
    "query" TEXT,
    "transcriptSource" TEXT,
    "llmProvider" TEXT,
    "thumbPath" TEXT,
    "sourceDeleted" BOOLEAN NOT NULL DEFAULT false,
    "aiCostUsd" REAL NOT NULL DEFAULT 0,
    "aiTokens" INTEGER NOT NULL DEFAULT 0,
    "aiCostEstimated" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO "new_Project" ("createdAt", "durationSec", "error", "folder", "id", "language", "llmProvider", "progress", "query", "sourceDeleted", "sourceType", "sourceUrl", "stage", "status", "thumbPath", "title", "transcriptSource", "updatedAt") SELECT "createdAt", "durationSec", "error", "folder", "id", "language", "llmProvider", "progress", "query", "sourceDeleted", "sourceType", "sourceUrl", "stage", "status", "thumbPath", "title", "transcriptSource", "updatedAt" FROM "Project";
DROP TABLE "Project";
ALTER TABLE "new_Project" RENAME TO "Project";
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
