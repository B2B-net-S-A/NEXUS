import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { CONTRACT_STATUS_BADGE } from "@/components/v2/pages/ContractsListV2";

/**
 * Plakietka statusu w globalnym rejestrze kontraktów musi być lustrem enuma
 * `ContractStatus` z backendu.
 *
 * Regresja jest tu CICHA w obie strony i typy jej nie łapią (mapa to
 * `Record<string, …>`, a `status` z API to `string`):
 *  - klucz, którego backend nie emituje, po prostu nigdy się nie zapala —
 *    tak żyły `expiring` i `terminated`, a `ending` („< 30 dni do końca"),
 *    czyli jedyny status istniejący po to, żeby ostrzegać, zabierał neutralny
 *    fallback zamiast bursztynu i wyglądał jak kontrakt zakończony;
 *  - brakujący klucz nie wywala renderu, tylko drukuje surowy identyfikator —
 *    polskojęzyczny rejestr pokazywał „ready_for_signature".
 *
 * Dlatego kontrakt sprawdzamy wobec ŹRÓDŁA prawdy: definicji enuma w modelu.
 */

const REPO_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
  "..",
  "..",
);
const CONTRACT_MODEL = path.join(REPO_ROOT, "backend", "app", "models", "contract.py");
const ENUM_HEADER = "class ContractStatus(str, enum.Enum):";

function backendContractStatuses(): string[] {
  const source = fs.readFileSync(CONTRACT_MODEL, "utf8");
  const start = source.indexOf(ENUM_HEADER);
  if (start === -1) throw new Error(`Nie znaleziono ContractStatus w ${CONTRACT_MODEL}`);
  // Ciało enuma jest przeplecione komentarzami (`ready_for_signature` i `void`
  // mają po kilka linii wyjaśnienia), więc bierzemy blok do następnej klasy
  // i dopiero z niego wyciągamy przypisania.
  const rest = source.slice(start + ENUM_HEADER.length);
  const end = rest.indexOf("\nclass ");
  const block = end === -1 ? rest : rest.slice(0, end);
  return [...block.matchAll(/^\s+\w+ = "([^"]+)"/gm)].map((m) => m[1]);
}

describe("CONTRACT_STATUS_BADGE ↔ enum ContractStatus", () => {
  it("czyta model backendu (strażnik nie jest pusty)", () => {
    // Bez tej asercji zmiana kształtu modelu dałaby zielony test na zawsze.
    expect(backendContractStatuses().length).toBeGreaterThanOrEqual(6);
  });

  it("pokrywa dokładnie statusy, które backend potrafi zwrócić", () => {
    expect(Object.keys(CONTRACT_STATUS_BADGE).sort()).toEqual(
      backendContractStatuses().sort(),
    );
  });

  it("nie wypuszcza angielskiego identyfikatora jako etykiety", () => {
    for (const [value, badge] of Object.entries(CONTRACT_STATUS_BADGE)) {
      expect(badge.label.trim().length).toBeGreaterThan(0);
      expect(badge.label).not.toBe(value);
    }
  });

  it("trzyma ostrzegawczy wariant na statusie, który ostrzega", () => {
    // `ending` = mniej niż 30 dni do końca współpracy. To jedyny powód
    // istnienia tego statusu, więc kolor jest tu funkcją, nie ozdobą.
    expect(CONTRACT_STATUS_BADGE.ending.variant).toBe("warning");
    expect(CONTRACT_STATUS_BADGE.ended.variant).toBe("neutral");
  });
});
