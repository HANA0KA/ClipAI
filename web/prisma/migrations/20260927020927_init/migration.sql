-- CreateTable
CREATE TABLE "Project" (
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
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "Clip" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "projectId" TEXT NOT NULL,
    "rank" INTEGER NOT NULL DEFAULT 0,
    "startSec" REAL NOT NULL,
    "endSec" REAL NOT NULL,
    "score" INTEGER NOT NULL,
    "reason" TEXT NOT NULL,
    "hook" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "hashtags" TEXT NOT NULL,
    "templateId" TEXT NOT NULL DEFAULT 'bold-yellow',
    "captionsPath" TEXT,
    "cropPath" TEXT,
    "renderStatus" TEXT NOT NULL DEFAULT 'NONE',
    "renderError" TEXT,
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
    "signals" TEXT,
    "qaWarnings" TEXT,
    "publishStatus" TEXT,
    "publishInfo" TEXT,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Clip_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Job" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "type" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'QUEUED',
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "error" TEXT,
    "payload" TEXT,
    "runAfter" DATETIME,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateIndex
CREATE INDEX "Clip_projectId_idx" ON "Clip"("projectId");

-- CreateIndex
CREATE INDEX "Job_status_idx" ON "Job"("status");

-- CreateIndex
CREATE INDEX "Job_targetId_idx" ON "Job"("targetId");
