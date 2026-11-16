// Strażnik zestawu Poligonu: repo jest publiczne, a zestaw powstaje z nagrania
// na kopii produkcji. Każdy tekst musi być kodem, datą względną, osobą
// ćwiczebną albo stać pod kluczem z `safe-keys.json` (etykiety interfejsu,
// pytania screeningu). Do tego żadnych e-maili, telefonów i adresów WWW.

import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import meta from "../meta.json";
import safeKeys from "../safe-keys.json";

const ENUM = /^[a-z0-9_\-:.]{1,60}$/;
const SAFE = new Set<string>(safeKeys);
/** Klucze, pod którymi skrypt wstawia wymyśloną treść (CV ćwiczebne, osoby, rekrutacja). */
const FICTION_KEYS = new Set([
  "name", "lastname", "first_name", "last_name", "full_name", "title", "working_title", "job_title", "role_name",
  "job_working_title", "cv_position", "client_name", "company", "client", "reference_number", "client_reference",
  "role", "current_role", "current_position", "description", "desc", "companies", "company_norm", "achievements",
  "evidence", "issuer", "certifications", "degree", "school", "field", "profile", "professional_profile",
  "ai_summary", "career_summary", "matching_facts", "bullets", "notes", "content", "content_rendered",
  "notice_period", "available_from", "rate_flexibility", "added_via", "technologies", "skill", "job_reference",
  // Przegląd Delivery Leada: wymagania i kategoria są wymyślone (`dl_context` w skrypcie).
  "candidate_value", "category_name",
]);
const PERSON_KEY = /(^|_)(name|person|who)$/;
/** Stałe teksty zastępcze skryptu (`REQUIRED_TEXT`) pod kluczami spoza słownika — tylko ta wartość, nie cały klucz. */
const FIXED_TEXT = new Map([["raw", "z rozmowy telefonicznej"]]);

function strings(value: unknown, key = "", out: Array<[string, string]> = []): Array<[string, string]> {
  if (typeof value === "string") out.push([key, value]);
  else if (Array.isArray(value)) value.forEach((v) => strings(v, key, out));
  else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => strings(v, k, out));
  return out;
}

describe("zestaw Poligonu", () => {
  const all = strings(dataset);

  it("nie ma e-maili, telefonów ani adresów WWW", () => {
    const bad = all.filter(([, v]) => /[\w.+-]+@[\w-]+\.\w+|\+48[\d ]{9,}|https?:\/\//.test(v));
    expect(bad).toEqual([]);
  });

  it("nie ma tokenów, odcisków ani innych ciągów o wysokiej entropii", () => {
    const secretKey = /(token|hash|fingerprint|sha\d*|signature|secret|password)/i;
    expect(all.filter(([k, v]) => secretKey.test(k) && v !== "poligon")).toEqual([]);
    // Długi ciąg liter i cyfr bez spacji (np. hash) — kody interfejsu mają podkreślenia albo słowa.
    expect(all.filter(([, v]) => /^[A-Za-z0-9+/=]{24,}$/.test(v) && /\d/.test(v) && /[A-Za-z]/.test(v))).toEqual([]);
  });

  it("każdy tekst jest kodem, datą, osobą ćwiczebną albo stoi pod dozwolonym kluczem", () => {
    const people = new Set(meta.people.flatMap((p) => [p.name, p.lastname, `${p.name} ${p.lastname}`]));
    Object.values(meta.trainers).forEach((t) => people.add(t.name));
    const bad = all.filter(([k, v]) => {
      if (!v || ENUM.test(v) || /^@reld?:-?[\d.]+$/.test(v) || /^@relt:\d+T\d{2}:\d{2}$/.test(v) || /^\d+$/.test(v)) return false;
      if (people.has(v)) return false;
      if (SAFE.has(k) || FICTION_KEYS.has(k) || FIXED_TEXT.get(k) === v) return false;
      if (PERSON_KEY.test(k) && people.has(v)) return false;
      return true;
    });
    expect(bad).toEqual([]);
  });

  it("osoby pod kluczami osób to wyłącznie osoby ćwiczebne", () => {
    const people = new Set(meta.people.map((p) => `${p.name} ${p.lastname}`));
    Object.values(meta.trainers).forEach((t) => people.add(t.name));
    [meta.job_title, meta.client_name].forEach((v) => people.add(v));
    const fullNames = all.filter(([k, v]) => PERSON_KEY.test(k) && k !== "name" && !SAFE.has(k) && /^\p{Lu}\p{Ll}+ \p{Lu}\p{Ll}+/u.test(v));
    expect(fullNames.filter(([, v]) => !people.has(v) && v !== "Ty")).toEqual([]);
  });

  it("identyfikatory rekrutacji i osób są z zakresu poligonu", () => {
    expect(meta.job_id).toBeGreaterThanOrEqual(990_000);
    meta.people.forEach((p) => {
      expect(p.candidate_id).toBeGreaterThanOrEqual(990_000);
      expect(p.entry_id).toBeGreaterThanOrEqual(990_000);
    });
    const ids = Object.keys((dataset as { responses: Record<string, unknown> }).responses).flatMap((k) => k.match(/\b\d{5,}\b/g) ?? []);
    expect(ids.filter((id) => Number(id) < 990_000)).toEqual([]);
  });
});
