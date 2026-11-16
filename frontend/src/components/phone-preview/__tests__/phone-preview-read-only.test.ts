import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// Strażnik decyzji Artura z 05.11.2026: na telefonie tylko podgląd, praca na
// laptopie. Zapis, który tu trafi, zrobi z podglądu drugie miejsce pracy.
const ROOTS = ["src/app/podglad", "src/components/phone-preview"];
const WRITES = [
  /\bapi\s*\.\s*(post|put|patch|delete)\b/,
  /\buseMutation\b/,
  /method\s*:\s*["'`](POST|PUT|PATCH|DELETE)/i,
  /\bfetch\s*\(/,
];
// Na telefonie nie ma pracy z osobą ani plików.
const OFF_LIMITS = [/candidate_phone/, /candidate_email/, /\/download\b/];
// Decyzja Artura z 14.11.2026: numer i mail kandydata wolno pokazać na karcie
// kontaktu, ale linki do dzwonienia i poczty żyją w jednym pliku, a karta czyta
// `quick-view` z `via=phone`, żeby otwarcie zostało w historii kandydata.
const CONTACT_LINKS = [/\btel:/, /\bsms:/, /\bmailto:/];
const CONTACT_FILE = path.join("components", "phone-preview", "contact.tsx");
const CARD_FILE = path.join("app", "podglad", "kandydat", "[id]", "page.tsx");

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "__tests__" ? [] : sources(full);
    return /\.tsx?$/.test(e.name) ? [full] : [];
  });
}

describe("podgląd na telefonie", () => {
  const files = ROOTS.flatMap((r) => sources(path.resolve(process.cwd(), r)));

  it("ma co sprawdzać", () => {
    expect(files.length).toBeGreaterThan(8);
  });

  it.each(files)("%s niczego nie zapisuje, linki kontaktu tylko w contact.tsx", (file) => {
    const text = fs.readFileSync(file, "utf8");
    for (const rule of [...WRITES, ...OFF_LIMITS]) expect(text).not.toMatch(rule);
    if (!file.endsWith(CONTACT_FILE)) for (const rule of CONTACT_LINKS) expect(text).not.toMatch(rule);
  });

  it("karta kontaktu zapisuje otwarcie (quick-view z via=phone)", () => {
    const card = files.find((f) => f.endsWith(CARD_FILE));
    expect(card).toBeDefined();
    expect(fs.readFileSync(card!, "utf8")).toMatch(/quick-view`, \{ params: \{ via: "phone" \} \}/);
  });
});
