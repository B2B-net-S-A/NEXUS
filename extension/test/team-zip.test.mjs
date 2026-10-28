// ZIP zespołu (`frontend/public/wtyczka/nexus-linkedin.zip`, pobierany z NEXUSA
// na stronie /wtyczka) musi mieć dokładnie te pliki co extension/ — inaczej
// ludzie instalują starszą wersję niż ta w repo. Odśwież: sh extension/scripts/pack.sh.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ZIP = resolve(ROOT, "../frontend/public/wtyczka/nexus-linkedin.zip");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (name === ".DS_Store") return [];
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

test("ZIP zespołu = manifest, ikony i src z repo", { skip: process.env.SKIP_TEAM_ZIP_CHECK === "1" }, () => {
  assert.ok(existsSync(ZIP), "brak frontend/public/wtyczka/nexus-linkedin.zip — uruchom sh extension/scripts/pack.sh");
  const listed = execFileSync("unzip", ["-Z1", ZIP], { encoding: "utf8" }).split("\n").filter((l) => l && !l.endsWith("/"));
  const expected = ["manifest.json", ...walk(join(ROOT, "icons")), ...walk(join(ROOT, "src"))].map((p) => (p === "manifest.json" ? p : relative(ROOT, p))).sort();
  assert.deepEqual([...listed].sort(), expected);
  for (const file of expected) {
    const zipped = execFileSync("unzip", ["-p", ZIP, file], { maxBuffer: 16 * 1024 * 1024 });
    assert.ok(zipped.equals(readFileSync(join(ROOT, file))), `${file}: ZIP zespołu jest nieaktualny — uruchom sh extension/scripts/pack.sh`);
  }
  const manifest = JSON.parse(execFileSync("unzip", ["-p", ZIP, "manifest.json"], { encoding: "utf8" }));
  assert.ok(manifest.key, "ZIP zespołu musi mieć pole key (stałe id)");
});
