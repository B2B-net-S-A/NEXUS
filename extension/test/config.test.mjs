import { test } from "node:test";
import assert from "node:assert/strict";

import { connectUrl, isAllowedApiBase, normalizeApiBase, validateKeyMessage } from "../src/config.js";

const KEY = `nxe_v1_${"a1".repeat(12)}_${"Zz9-_".repeat(8)}`;
const msg = (over = {}) => ({ type: "nexus-extension-key", key: KEY, apiBase: "https://api.nexus.b2bnetwork.pl", frontUrl: "https://nexus.b2bnetwork.pl", ...over });
const PROD = { origin: "https://nexus.b2bnetwork.pl", tab: { id: 5 } };

test("wiadomość połączenia ze strony NEXUSA zostaje przyjęta", () => {
  const r = validateKeyMessage(msg(), PROD);
  assert.equal(r.ok, true);
  assert.deepEqual(r.connection, { key: KEY, apiBase: "https://api.nexus.b2bnetwork.pl", frontUrl: "https://nexus.b2bnetwork.pl" });
});

test("staging z laptopa (3100, 3101) i API produkcji pod starą domeną", () => {
  assert.equal(validateKeyMessage(msg({ apiBase: "http://localhost:8100", frontUrl: "http://localhost:3100" }), { origin: "http://localhost:3100" }).ok, true);
  assert.equal(validateKeyMessage(msg({ apiBase: "http://localhost:8100", frontUrl: undefined }), { url: "http://localhost:3101/extension/connect?ext=x" }).connection.frontUrl, "http://localhost:3101");
  assert.equal(validateKeyMessage(msg({ apiBase: "https://api.nexus.dynaminds.pl/" }), PROD).connection.apiBase, "https://api.nexus.dynaminds.pl");
});

test("odrzuca obcego nadawcę, zły klucz i apiBase spoza listy hostów", () => {
  assert.equal(validateKeyMessage(msg(), { origin: "https://evil.example" }).reason, "sender_not_allowed");
  assert.equal(validateKeyMessage(msg(), {}).reason, "sender_not_allowed");
  assert.equal(validateKeyMessage(msg({ key: "nxe_v1_short_x" }), PROD).reason, "bad_key");
  assert.equal(validateKeyMessage(msg({ key: KEY.toUpperCase() }), PROD).reason, "bad_key");
  assert.equal(validateKeyMessage(msg({ apiBase: "https://attacker.example" }), PROD).reason, "bad_api_base");
  assert.equal(validateKeyMessage(msg({ apiBase: "http://api.nexus.b2bnetwork.pl" }), PROD).reason, "bad_api_base");
  assert.equal(validateKeyMessage(msg({ apiBase: "https://b2bnetwork.pl.evil.example" }), PROD).reason, "bad_api_base");
  assert.equal(validateKeyMessage(msg({ apiBase: "http://localhost:9999" }), PROD).reason, "bad_api_base");
  assert.equal(validateKeyMessage({ ...msg(), type: "other" }, PROD).reason, "wrong_type");
  assert.equal(validateKeyMessage(null, PROD).reason, "wrong_type");
});

test("frontUrl spoza listy → origin nadawcy", () => {
  assert.equal(validateKeyMessage(msg({ frontUrl: "https://evil.example" }), PROD).connection.frontUrl, "https://nexus.b2bnetwork.pl");
});

test("adres strony połączenia i normalizacja apiBase", () => {
  assert.equal(connectUrl("https://nexus.b2bnetwork.pl/", "abcdef", "1.0.0"), "https://nexus.b2bnetwork.pl/extension/connect?ext=abcdef&v=1.0.0");
  assert.equal(normalizeApiBase("https://api.nexus.b2bnetwork.pl/api/"), "https://api.nexus.b2bnetwork.pl");
  assert.equal(isAllowedApiBase("https://user:pass@api.nexus.b2bnetwork.pl"), false);
});
