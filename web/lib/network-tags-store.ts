import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { DATA_DIR } from "@/lib/paths";
import { cleanTags, EMPTY_NETWORK_TAGS, type NetworkTags } from "@/lib/network-tags";

const FILE = path.join(DATA_DIR, "network-hashtags.json");

let queue: Promise<unknown> = Promise.resolve();

export async function readNetworkTags(): Promise<NetworkTags> {
  try {
    const j = JSON.parse(await fs.readFile(FILE, "utf8")) as Partial<Record<keyof NetworkTags, unknown>>;
    return { youtube: cleanTags(j.youtube), instagram: cleanTags(j.instagram) };
  } catch {
    return structuredClone(EMPTY_NETWORK_TAGS);
  }
}

/** Guarda las fijas de una red de forma atómica (tmp + rename); devuelve las dos listas. */
export function writeNetworkTags(patch: Partial<Record<keyof NetworkTags, unknown>>): Promise<NetworkTags> {
  const run = queue.catch(() => undefined).then(async () => {
    const cur = await readNetworkTags();
    const next: NetworkTags = {
      youtube: patch.youtube !== undefined ? cleanTags(patch.youtube) : cur.youtube,
      instagram: patch.instagram !== undefined ? cleanTags(patch.instagram) : cur.instagram,
    };
    await fs.mkdir(path.dirname(FILE), { recursive: true });
    const tmp = `${FILE}.${process.pid}.${Date.now()}.tmp`;
    await fs.writeFile(tmp, JSON.stringify({ version: 1, ...next }, null, 1), { mode: 0o600 });
    await fs.rename(tmp, FILE);
    return next;
  });
  queue = run;
  return run;
}
