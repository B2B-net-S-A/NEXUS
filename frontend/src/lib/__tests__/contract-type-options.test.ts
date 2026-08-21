import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { CONTRACT_TYPE_OPTIONS } from "@/lib/filter-options";

/**
 * Filtr „Typ" na /contracts musi być lustrem enuma PG `contracttype`.
 *
 * `contracts.contract_type` to natywny enum Postgresa, a handler przyjmuje
 * `list[str]` — więc wartość spoza słownika NIE jest odrzucana przez FastAPI
 * czytelnym 422, tylko przez sterownik: `invalid input value for enum
 * contracttype` → 500. To API przy 500 gubi nagłówki CORS, więc w przeglądarce
 * widać „Network Error", a rejestr i eksport XLSX/CSV renderują stan błędu.
 *
 * Do 2026-08 były tu wartości przepisane z `RecruitmentType`
 * (body_leasing/fixed_price/t_and_m), który żyje na `Job`, NIE na `Contract` —
 * czyli KAŻDA z trzech opcji filtra padała. Regresja jest cicha po stronie
 * typów (union stringów zgodzi się z czymkolwiek), więc kontrakt sprawdzamy
 * wobec ŹRÓDŁA prawdy: definicji enuma w modelu backendu.
 */

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
);
const CONTRACT_MODEL = path.join(REPO_ROOT, "backend", "app", "models", "contract.py");

function backendContractTypes(): string[] {
  const source = fs.readFileSync(CONTRACT_MODEL, "utf8");
  const block = /class ContractType\(str, enum\.Enum\):\n((?:\s+\w+ = "[^"]+".*\n)+)/.exec(
    source,
  );
  if (!block) throw new Error(`Nie znaleziono ContractType w ${CONTRACT_MODEL}`);
  return [...block[1].matchAll(/^\s+\w+ = "([^"]+)"/gm)].map((m) => m[1]);
}

describe("CONTRACT_TYPE_OPTIONS ↔ enum ContractType", () => {
  it("czyta model backendu (strażnik nie jest pusty)", () => {
    // Bez tej asercji zmiana kształtu modelu dałaby zielony test na zawsze.
    expect(backendContractTypes().length).toBeGreaterThanOrEqual(3);
  });

  it("oferuje dokładnie wartości akceptowane przez kolumnę", () => {
    expect([...CONTRACT_TYPE_OPTIONS].map((o) => o.value).sort()).toEqual(
      backendContractTypes().sort(),
    );
  });

  it("każda opcja ma etykietę po polsku", () => {
    for (const option of CONTRACT_TYPE_OPTIONS) {
      expect(option.label.trim().length).toBeGreaterThan(0);
    }
  });
});
