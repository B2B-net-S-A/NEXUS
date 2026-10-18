/**
 * Harnessy „Ludzi w NEXUSIE” (`/preview/hr-*`, 17.10.2026) — strażnik zestawu.
 *
 * Plan programu obiecywał harness dla każdej makiety raportu (14 ekranów),
 * a audyt 17.10 nie znalazł żadnego. Ten test pilnuje, żeby każdy harness HR
 * miał test, który montuje CAŁĄ stronę i sprawdza zero PRÓB żądania (spy na
 * `Axios.prototype.request` łapie też żądania odrzucone przez interceptor),
 * i żeby zasiewał dane wspólnym `useHrHarness` (blokada sieci + konto).
 * Statyczny strażnik kluczy (`harness-seeds.test.ts`) nie widzi kluczy
 * z parametrem, a te w ekranach „Ludzi” są prawie wszystkie (miesiąc, filtr, id).
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PREVIEW = join(process.cwd(), "src/app/preview");

const HARNESSES = readdirSync(PREVIEW).filter(
  (name) => name.startsWith("hr-") && existsSync(join(PREVIEW, name, "page.tsx")),
);

/** Makiety raportu i harness, który je pokazuje (stanem albo personą). */
const MOCKUPS: Record<string, string> = {
  "Pulpit i nieobecni": "hr-dashboard",
  "Wniosek urlopowy": "hr-my-time",
  "Kalendarz zespołu": "hr-calendar",
  "Mój miesiąc": "hr-my-time",
  Akceptacje: "hr-approvals",
  "Kartoteka osoby": "hr-person",
  "Płace i premie": "hr-payroll",
  Odejście: "hr-offboarding",
  "Opieka nad konsultantem": "hr-care",
  "Technologie klienta": "hr-client-tech",
  "Sprawy administracja@": "hr-cases",
  "Sprzęt: ewidencja": "hr-equipment",
  "Wydanie i protokół": "hr-equipment-issue",
  "Wejście nowej osoby": "hr-onboarding",
};

describe("harnessy „Ludzi” /preview/hr-*", () => {
  it("każda z 14 makiet raportu ma harness", () => {
    const missing = Object.entries(MOCKUPS)
      .filter(([, route]) => !HARNESSES.includes(route))
      .map(([mockup, route]) => `${mockup} → /preview/${route}`);
    expect(missing).toEqual([]);
  });

  it("każdy harness ma test strony z zerem prób żądania", () => {
    const missing = HARNESSES.filter((name) => {
      const path = join(PREVIEW, "__tests__", `${name}-harness.test.tsx`);
      if (!existsSync(path)) return true;
      const source = readFileSync(path, "utf8");
      return (
        !source.includes(`../${name}/page`) ||
        !source.includes('vi.spyOn(Axios.prototype, "request")') ||
        !source.includes("expect(attempted()).toEqual([])")
      );
    });
    expect(missing, "harness bez testu „zero prób żądania”").toEqual([]);
  });

  it("każdy harness odcina sieć wspólnym `useHrHarness`", () => {
    const missing = HARNESSES.filter((name) => {
      const source = readFileSync(join(PREVIEW, name, "page.tsx"), "utf8");
      return !source.includes("useHrHarness(") || !source.includes("harnessQueryClient()");
    });
    expect(missing).toEqual([]);
  });
});
