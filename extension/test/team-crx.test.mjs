// Paczka dla polityki Chrome z Intune (`frontend/public/wtyczka/nexus-linkedin.crx`
// + `update.xml`): podpisana kluczem z pola `key`, z tymi samymi plikami co
// extension/ i z `update_url`, bo z niego Chrome bierze kolejne wersje.
// Nieaktualny .crx = laptopy z polityką zostają na starej wersji. Odśwież:
// sh extension/scripts/pack.sh na laptopie z kluczem (extension/README.md).
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readCrx3 } from "../scripts/crx3.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TEAM_DIR = resolve(ROOT, "../frontend/public/wtyczka");
const CRX = join(TEAM_DIR, "nexus-linkedin.crx");
const UPDATE_XML = join(TEAM_DIR, "update.xml");
const TEAM_ID = "pmnonjpommkjblgacmpaclgacjmipplm";
const BASE = "https://nexus.b2bnetwork.pl/wtyczka";
const manifest = JSON.parse(readFileSync(join(ROOT, "manifest.json"), "utf8"));
const skip = process.env.SKIP_TEAM_ZIP_CHECK === "1";

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (name === ".DS_Store") return [];
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

test("CRX zespołu: podpis kluczem z pola key, stałe id", { skip }, () => {
  assert.ok(existsSync(CRX), "brak frontend/public/wtyczka/nexus-linkedin.crx — uruchom sh extension/scripts/pack.sh z kluczem");
  const crx = readCrx3(readFileSync(CRX));
  assert.equal(crx.id, TEAM_ID);
  assert.equal(crx.publicKey, manifest.key, "CRX podpisany innym kluczem niż pole key manifestu");
});

test("CRX zespołu = pliki z repo, manifest z update_url", { skip }, () => {
  const { zip } = readCrx3(readFileSync(CRX));
  const tmp = mkdtempSync(join(tmpdir(), "nexus-crx-"));
  try {
    const zipPath = join(tmp, "crx.zip");
    writeFileSync(zipPath, zip);
    const listed = execFileSync("unzip", ["-Z1", zipPath], { encoding: "utf8" }).split("\n").filter((l) => l && !l.endsWith("/"));
    const expected = ["manifest.json", ...[...walk(join(ROOT, "icons")), ...walk(join(ROOT, "src"))].map((p) => relative(ROOT, p))].sort();
    assert.deepEqual([...listed].sort(), expected);
    for (const file of expected.filter((f) => f !== "manifest.json")) {
      const zipped = execFileSync("unzip", ["-p", zipPath, file], { maxBuffer: 16 * 1024 * 1024 });
      assert.ok(zipped.equals(readFileSync(join(ROOT, file))), `${file}: CRX jest nieaktualny — uruchom sh extension/scripts/pack.sh z kluczem`);
    }
    const packed = JSON.parse(execFileSync("unzip", ["-p", zipPath, "manifest.json"], { encoding: "utf8" }));
    assert.deepEqual(packed, { ...manifest, update_url: `${BASE}/update.xml` }, "manifest w CRX różni się od extension/manifest.json — uruchom pack.sh");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("update.xml: id, wersja z manifestu i adres .crx", { skip }, () => {
  assert.ok(existsSync(UPDATE_XML), "brak frontend/public/wtyczka/update.xml — uruchom sh extension/scripts/pack.sh z kluczem");
  const xml = readFileSync(UPDATE_XML, "utf8");
  assert.match(xml, new RegExp(`<app appid='${TEAM_ID}'>`));
  assert.match(xml, new RegExp(`codebase='${BASE}/nexus-linkedin.crx'`));
  assert.match(xml, new RegExp(`version='${manifest.version.replaceAll(".", "\\.")}'`), "update.xml ma inną wersję niż manifest");
  assert.match(xml, new RegExp(`prodversionmin='${manifest.minimum_chrome_version}'`));
});
