import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError, createApi, errorFromResponse, ERROR_KINDS, validateLookup } from "../src/api.js";

const CONN = { key: ["nxe", "v1", "a".repeat(24), "s".repeat(43)].join("_"), apiBase: "https://api.nexus.example.test" };

function fakeFetch(status, body, calls = []) {
  return async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => (body === undefined ? "" : typeof body === "string" ? body : JSON.stringify(body)),
    };
  };
}

function api(status, body, calls, extra = {}) {
  return createApi({ getConnection: async () => CONN, fetchImpl: fakeFetch(status, body, calls), ...extra });
}

test("401 extension_key_invalid → key_invalid i wywołanie onKeyInvalid", async () => {
  let called = 0;
  const client = api(401, { detail: "extension_key_invalid" }, [], { onKeyInvalid: () => (called += 1) });
  await assert.rejects(client.me(), (err) => err instanceof ApiError && err.kind === ERROR_KINDS.KEY_INVALID);
  assert.equal(called, 1);
});

test("mapowanie kodów błędów na stany panelu", () => {
  const cases = [
    [401, { detail: "extension_key_invalid" }, ERROR_KINDS.KEY_INVALID],
    [403, { detail: "Nie masz dostępu do kandydatów." }, ERROR_KINDS.FORBIDDEN],
    [409, { detail: { code: "off_limits_confirmation_required", message: "Firma jest off-limits.", candidates: [] } }, ERROR_KINDS.OFF_LIMITS],
    [409, { detail: "Duplikat" }, ERROR_KINDS.CONFLICT],
    [429, { detail: "extension_daily_limit" }, ERROR_KINDS.DAILY_LIMIT],
    [429, { detail: "Rate limit exceeded" }, ERROR_KINDS.RATE_LIMITED],
    [422, { detail: [{ loc: ["body"], msg: "x" }] }, ERROR_KINDS.BAD_REQUEST],
    [500, null, ERROR_KINDS.SERVER],
    [503, { detail: "x" }, ERROR_KINDS.SERVER],
  ];
  for (const [status, body, kind] of cases) assert.equal(errorFromResponse(status, body).kind, kind, `${status}`);
});

test("komunikaty: 403 pokazuje zdanie z detail, 429 limit dzienny po polsku, kod maszynowy nie trafia do człowieka", () => {
  assert.equal(errorFromResponse(403, { detail: "Nie masz dostępu do kandydatów." }).message, "Nie masz dostępu do kandydatów.");
  assert.equal(errorFromResponse(429, { detail: "extension_daily_limit" }).message, "Dzisiejszy limit odczytów wyczerpany, wróć jutro.");
  assert.doesNotMatch(errorFromResponse(403, { detail: "forbidden_scope" }).message, /forbidden_scope/);
  const off = errorFromResponse(409, { detail: { code: "off_limits_confirmation_required", message: "Zdanie z NEXUSA" } });
  assert.equal(off.detail.message, "Zdanie z NEXUSA");
});

test("błąd sieci → network z polskim komunikatem", async () => {
  const client = createApi({
    getConnection: async () => CONN,
    fetchImpl: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  await assert.rejects(client.me(), (err) => err.kind === ERROR_KINDS.NETWORK && /Nie udało się połączyć z NEXUSEM/.test(err.message));
});

test("brak połączenia → not_connected bez wywołania sieci", async () => {
  const calls = [];
  const client = createApi({ getConnection: async () => null, fetchImpl: fakeFetch(200, {}, calls) });
  await assert.rejects(client.me(), (err) => err.kind === ERROR_KINDS.NOT_CONNECTED);
  assert.equal(calls.length, 0);
});

test("nagłówek X-Extension-Key, bez Authorization; adresy tras z API.md", async () => {
  const calls = [];
  const client = api(200, { items: [] }, calls);
  await client.jobs("java");
  await client.lookupBatch([{ full_name: "A B", public_url: null, headline: null, current_company: null }]);
  await client.addToJobs(7, [1], "linkedin_inbound");
  assert.equal(calls[0].url, "https://api.nexus.example.test/api/extension/jobs?q=java");
  assert.equal(calls[0].init.headers["X-Extension-Key"], CONN.key);
  assert.equal(calls[0].init.headers.Authorization, undefined);
  assert.equal(calls[1].url, "https://api.nexus.example.test/api/extension/lookup-batch");
  assert.deepEqual(JSON.parse(calls[1].init.body), { people: [{ full_name: "A B", public_url: null, headline: null, current_company: null }] });
  assert.equal(calls[2].url, "https://api.nexus.example.test/api/extension/candidates/7/jobs");
  assert.deepEqual(JSON.parse(calls[2].init.body), { job_ids: [1], off_limits_how: "linkedin_inbound" });
});

test("ciała zapytań: candidates, contacts, notes, draft-message", async () => {
  const calls = [];
  const client = api(200, { ok: true }, calls);
  const profile = { page_kind: "profile", full_name: "Zofia Testowa" };
  await client.addCandidate(profile, [5], null);
  await client.addContact(3, { channel: "inmail", jobId: 5, note: "x", remindInDays: 3 });
  await client.addNote(3, "notatka");
  await client.draftMessage(5, "invitation", profile);
  await client.refresh(3, profile);
  assert.deepEqual(JSON.parse(calls[0].init.body), { profile, job_ids: [5], off_limits_how: null });
  assert.deepEqual(JSON.parse(calls[1].init.body), { channel: "inmail", job_id: 5, note: "x", remind_in_days: 3 });
  assert.deepEqual(JSON.parse(calls[2].init.body), { text: "notatka" });
  assert.deepEqual(JSON.parse(calls[3].init.body), { job_id: 5, kind: "invitation", profile });
  assert.equal(calls[4].url, "https://api.nexus.example.test/api/extension/candidates/3/refresh");
  assert.deepEqual(JSON.parse(calls[4].init.body), { profile });
});

test("lookup bez znanego statusu to awaria, a nie „Nie ma w NEXUSIE”", async () => {
  await assert.rejects(api(200, { status: "weird" }).lookup({}), (err) => err.kind === ERROR_KINDS.BAD_RESPONSE);
  await assert.rejects(api(200, "<html>proxy</html>").lookup({}), (err) => err.kind === ERROR_KINDS.BAD_RESPONSE);
  await assert.rejects(api(200, { status: "found", candidate: null }).lookup({}), (err) => err.kind === ERROR_KINDS.BAD_RESPONSE);
});

test("validateLookup uzupełnia brakujące listy pustymi", () => {
  const v = validateLookup({ status: "not_found", processes: null });
  assert.deepEqual([v.processes, v.contacts, v.matches, v.ambiguous], [[], [], [], []]);
});
