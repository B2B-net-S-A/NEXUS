// Testy komunikatów porażki logowania wtyczki.
//
// DLACZEGO: na produkcji `PASSWORD_LOGIN_ENABLED=false`, więc `/api/auth/login`
// zwraca 503. Poprzednia wersja wklejała do UI surowy blob
// (`Login failed (HTTP 503): {"detail":"..."}`), a 503 bez rozróżnienia czyta
// się jak chwilowa awaria backendu — rekruter próbuje w kółko czegoś, co nigdy
// nie zadziała. Regresja tego rozróżnienia jest cicha: przycisk dalej jest,
// błąd dalej się pokazuje, tylko przestaje cokolwiek znaczyć.
//
// Uruchomienie: node --test extension/test/*.test.mjs
//
// `api-client.js` importuje `./storage.js` (dotyka globalnego `chrome`), a
// data: URL nie rozwiązuje ścieżek względnych — podmieniamy więc import na
// atrapy i asertujemy, że podmiana faktycznie zaszła.

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const raw = await readFile(
  new URL("../src/shared/api-client.js", import.meta.url),
  "utf8",
);
const IMPORT_BLOCK = `import {
  getAuth,
  setAuth,
  clearAuth,
  getBackendUrl,
} from "./storage.js";`;
assert.ok(
  raw.includes(IMPORT_BLOCK),
  "kształt importu ze storage.js się zmienił — zaktualizuj atrapę w teście",
);
const src = raw.replace(
  IMPORT_BLOCK,
  [
    "const getAuth = async () => null;",
    "const setAuth = async () => {};",
    "const clearAuth = async () => {};",
    "const getBackendUrl = async () => 'https://api.example.test';",
    "void getAuth; void setAuth; void clearAuth; void getBackendUrl;",
  ].join("\n"),
);
const { describeLoginFailure } = await import(
  "data:text/javascript;base64," + Buffer.from(src, "utf8").toString("base64")
);

test("503 przy wyłączonym logowaniu hasłem mówi, że hasło NIGDY nie zadziała", () => {
  const out = describeLoginFailure(503, "Logowanie hasłem jest wyłączone.", {
    password: false,
    microsoft: true,
    self_registration: false,
  });
  assert.equal(out.code, "password_login_disabled");
  assert.match(out.error, /Microsoft SSO/);
  // Nie wolno sugerować „spróbuj później” — to jest stan trwały.
  assert.doesNotMatch(out.error, /za kilka minut/);
  // Żadnego surowego JSON-a w tekście dla użytkownika.
  assert.doesNotMatch(out.error, /[{}"]/);
});

test("503 bez odpowiedzi z /api/auth/methods zostaje realną niedostępnością", () => {
  const out = describeLoginFailure(503, null, null);
  assert.equal(out.code, "backend_unavailable");
  assert.match(out.error, /za kilka minut/);
});

test("503 przy WŁĄCZONYM logowaniu hasłem to awaria, nie bramka", () => {
  const out = describeLoginFailure(503, null, { password: true, microsoft: true });
  assert.equal(out.code, "backend_unavailable");
});

test("401 nie udaje awarii serwera", () => {
  const out = describeLoginFailure(401, "Invalid credentials", null);
  assert.equal(out.code, "invalid_credentials");
  assert.match(out.error, /hasło/);
});

test("403 przepuszcza polski powód z backendu (konto wyłączone / e-mail)", () => {
  const out = describeLoginFailure(403, "Potwierdź adres e-mail.", null);
  assert.equal(out.code, "forbidden");
  assert.equal(out.error, "Potwierdź adres e-mail.");
});

test("429 tłumaczy limit prób, nie zostawia gołego numeru", () => {
  const out = describeLoginFailure(429, null, null);
  assert.equal(out.code, "rate_limited");
  assert.match(out.error, /Zbyt wiele prób/);
});

test("nieznany status niesie numer i szczegół, ale nie surowy JSON", () => {
  const out = describeLoginFailure(500, "Internal Server Error", null);
  assert.equal(out.code, "http_500");
  assert.match(out.error, /HTTP 500/);
  assert.match(out.error, /Internal Server Error/);
});
