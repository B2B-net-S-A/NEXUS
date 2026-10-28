// Strażnicy paczki: manifest, pliki, importy i zasady produktu
// (nic nie doklejamy do LinkedIna, zero voyagera, zero zewnętrznych skryptów).
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(ROOT, "manifest.json"), "utf8"));

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const SRC = walk(join(ROOT, "src"));
const JS = SRC.filter((p) => p.endsWith(".js"));

test("manifest: MV3, nazwa, wersja, panel boczny i service worker istnieją", () => {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.name, "NEXUS — LinkedIn");
  assert.equal(manifest.version, "1.0.0");
  assert.ok(existsSync(join(ROOT, manifest.side_panel.default_path)));
  assert.ok(existsSync(join(ROOT, manifest.background.service_worker)));
  assert.equal(manifest.background.type, "module");
  for (const icon of [...Object.values(manifest.icons), ...Object.values(manifest.action.default_icon)]) assert.ok(existsSync(join(ROOT, icon)), icon);
  assert.equal(manifest.default_locale, undefined);
});

test("manifest: tylko potrzebne uprawnienia i hosty", () => {
  assert.deepEqual([...manifest.permissions].sort(), ["scripting", "sidePanel", "storage"]);
  assert.deepEqual(manifest.host_permissions, ["https://www.linkedin.com/*", "https://nexus.b2bnetwork.pl/*", "https://api.nexus.b2bnetwork.pl/*", "https://api.nexus.dynaminds.pl/*", "http://localhost:8100/*"]);
  assert.deepEqual(manifest.externally_connectable.matches, ["https://nexus.b2bnetwork.pl/*", "http://localhost:3100/*", "http://localhost:3101/*"]);
  assert.equal(manifest.content_scripts, undefined, "nic nie doklejamy do stron LinkedIna");
  assert.equal(manifest.web_accessible_resources, undefined);
});

test("lista originów w config.js = externally_connectable", async () => {
  const { ALLOWED_FRONT_ORIGINS } = await import("../src/config.js");
  assert.deepEqual(
    ALLOWED_FRONT_ORIGINS,
    manifest.externally_connectable.matches.map((m) => m.replace(/\/\*$/, "")),
  );
});

test("każdy względny import w src wskazuje istniejący plik", () => {
  for (const file of JS) {
    const code = readFileSync(file, "utf8");
    for (const m of code.matchAll(/(?:import|export)\s[^"']*?from\s+["'](\.[^"']+)["']/g)) {
      assert.ok(existsSync(resolve(dirname(file), m[1])), `${file}: ${m[1]}`);
    }
  }
});

test("HTML panelu: brak skryptów z sieci i skryptów inline (CSP MV3)", () => {
  for (const file of SRC.filter((p) => p.endsWith(".html"))) {
    const html = readFileSync(file, "utf8");
    assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/, `${file}: skrypt inline`);
    assert.doesNotMatch(html, /\b(src|href)=["']https?:/, `${file}: zasób z sieci`);
  }
  for (const file of SRC.filter((p) => p.endsWith(".css"))) {
    assert.doesNotMatch(readFileSync(file, "utf8"), /@import|url\(\s*["']?https?:/, `${file}: zasób z sieci`);
  }
});

test("zasady produktu w kodzie: zero voyagera, zero innerHTML, zero wysyłania wiadomości na LinkedInie", () => {
  for (const file of JS) {
    const code = readFileSync(file, "utf8");
    assert.doesNotMatch(code, /voyager/i, `${file}: wewnętrzne API LinkedIna`);
    assert.doesNotMatch(code, /\.innerHTML\s*=|insertAdjacentHTML/, `${file}: innerHTML`);
    assert.doesNotMatch(code, /linkedin\.com\/[^"'`]*(messaging|invitation)/i, `${file}: wysyłka na LinkedInie`);
  }
});

test("tylko page.js wstrzykuje kod do karty, tylko background.js słucha stron NEXUSA", () => {
  for (const file of JS) {
    const code = readFileSync(file, "utf8");
    if (!file.endsWith("page.js")) assert.doesNotMatch(code, /executeScript/, file);
    if (!file.endsWith("background.js")) assert.doesNotMatch(code, /onMessageExternal\.addListener/, file);
  }
});
