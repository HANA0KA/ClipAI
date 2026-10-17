-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_Clip" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "projectId" TEXT NOT NULL,
    "rank" INTEGER NOT NULL DEFAULT 0,
    "startSec" REAL NOT NULL,
    "endSec" REAL NOT NULL,
    "score" INTEGER NOT NULL,
    "reason" TEXT NOT NULL,
    "hook" TEXT NOT NULL,
    "hookType" TEXT,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "hashtags" TEXT NOT NULL,
    "templateId" TEXT NOT NULL DEFAULT 'bold-yellow',
    "captionsPath" TEXT,
    "cropPath" TEXT,
    "renderStatus" TEXT NOT NULL DEFAULT 'NONE',
    "renderError" TEXT,
    "renderProgress" INTEGER NOT NULL DEFAULT 0,
    "renderedRevision" INTEGER NOT NULL DEFAULT 0,
    "outputPath" TEXT,
    "thumbPath" TEXT,
    "tiktokDraft" BOOLEAN NOT NULL DEFAULT false,
    "postedAt" DATETIME,
    "topic" INTEGER NOT NULL DEFAULT 0,
    "bestLine" TEXT,
    "bestLineStart" REAL,
    "bestLineEnd" REAL,
    "prependBestLine" BOOLEAN NOT NULL DEFAULT false,
    "layoutMode" TEXT NOT NULL DEFAULT 'auto',
    "smartCut" BOOLEAN NOT NULL DEFAULT false,
    "broll" BOOLEAN NOT NULL DEFAULT false,
    "edit" TEXT,
    "editRevision" INTEGER NOT NULL DEFAULT 0,
    "signals" TEXT,
    "qaWarnings" TEXT,
    "publishStatus" TEXT,
    "publishInfo" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Clip_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
INSERT INTO "new_Clip" ("bestLine", "bestLineEnd", "bestLineStart", "captionsPath", "createdAt", "cropPath", "description", "endSec", "hashtags", "hook", "id", "layoutMode", "outputPath", "postedAt", "prependBestLine", "projectId", "publishInfo", "publishStatus", "qaWarnings", "rank", "reason", "renderError", "renderStatus", "score", "signals", "smartCut", "startSec", "templateId", "thumbPath", "tiktokDraft", "title", "topic", "updatedAt") SELECT "bestLine", "bestLineEnd", "bestLineStart", "captionsPath", "createdAt", "cropPath", "description", "endSec", "hashtags", "hook", "id", "layoutMode", "outputPath", "postedAt", "prependBestLine", "projectId", "publishInfo", "publishStatus", "qaWarnings", "rank", "reason", "renderError", "renderStatus", "score", "signals", "smartCut", "startSec", "templateId", "thumbPath", "tiktokDraft", "title", "topic", "updatedAt" FROM "Clip";
DROP TABLE "Clip";
ALTER TABLE "new_Clip" RENAME TO "Clip";
CREATE INDEX "Clip_projectId_idx" ON "Clip"("projectId");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
