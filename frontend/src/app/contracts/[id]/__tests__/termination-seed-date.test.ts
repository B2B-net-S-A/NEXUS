/**
 * Zgłoszenie: przy zmianie statusu na „Zakończony" datę zakończenia trzeba było
 * wpisać dwa razy — raz w formularzu edycji, raz w oknie „Zakończ współpracę".
 * Przyczyną był `defaultDate={contract.end_date}` w call site dialogu: data
 * sprzed edycji z serwera zamiast tej, którą operator właśnie wpisał.
 *
 * Test czyta ŹRÓDŁO strony, tak jak `edit-form-labels.test.ts` obok: karta
 * kontraktu siedzi za sesją i kilkunastoma zapytaniami, więc test renderujący
 * padałby z powodów niezwiązanych z tą regułą. Bez tego strażnika regresja
 * wróciłaby niezauważona — samo zachowanie pola pilnuje
 * `components/contracts/__tests__/ContractTerminationDialog.test.tsx`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = readFileSync(join(__dirname, "..", "page.tsx"), "utf8");

/** Znaczniki `<ContractTerminationDialog …>` ze zwiniętymi białymi znakami. */
function dialogCallSites(): string[] {
  return [...SRC.matchAll(/<ContractTerminationDialog\b[\s\S]*?\/>/g)].map((m) =>
    m[0].replace(/\s+/g, " "),
  );
}

describe("karta kontraktu — data podstawiana w „Zakończ współpracę”", () => {
  it("zapamiętuje datę z formularza przy przejściu na „Zakończony”", () => {
    const normalized = SRC.replace(/\s+/g, " ");
    expect(normalized).toContain(
      "terminationSeedDate(form.end_date, contract.end_date)",
    );
    expect(SRC).toContain("terminationSeedDate");
  });

  it("dialog dostaje datę z formularza, nie tę zapisaną na umowie", () => {
    const sites = dialogCallSites();
    expect(sites).toHaveLength(1);
    for (const site of sites) {
      expect(site).toMatch(/defaultDate=\{terminationDate\}/);
      // To była dokładnie ta regresja: prop karmiony stanem z serwera.
      // Dopasowanie do samego propu — w komentarzu obok `contract.end_date`
      // pada z nazwy i bare `toContain` przewracałby się na dokumentacji.
      expect(site).not.toMatch(/defaultDate=\{\s*contract\.end_date/);
    }
  });

  it("zapamiętana data jest czyszczona po zamknięciu i po zapisie", () => {
    const handlers = SRC.match(/setTerminationDate\(undefined\)/g) ?? [];
    expect(handlers.length).toBeGreaterThanOrEqual(2);
  });
});
