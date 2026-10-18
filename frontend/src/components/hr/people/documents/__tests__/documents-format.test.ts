/**
 * E-teczka — słowa tabeli „Dokumenty”: stan, „ważny do”, krąg widzących,
 * kolejność wierszy (żywe dokumenty, protokoły, na końcu ślad usuniętych).
 * Dane fikcyjne z harnessu.
 */
import { describe, expect, it } from "vitest";

import { CELINA_DOCUMENTS, CELINA_PROTOCOLS, hrView } from "@/app/preview/hr-documents/fixtures";
import { audienceLabel, profileSyncMessage } from "@/lib/api/hr-documents";

import {
  documentRows,
  documentStatus,
  fileSizeLabel,
  protocolRow,
  validUntilLabel,
} from "../documents-format";

describe("documents-format", () => {
  it("umowa bez daty jest bezterminowa, inny rodzaj bez daty — kreska", () => {
    expect(validUntilLabel({ kind: "contract", valid_until: null })).toBe("bezterminowo");
    expect(validUntilLabel({ kind: "annex", valid_until: null })).toBe("—");
    expect(validUntilLabel({ kind: "statement", valid_until: "2027-06-30" })).toBe("30.06.2027");
  });

  it("stan: z generatora podpisana/podpisany, wgrany — dostarczone, usunięty z powodem", () => {
    const [statement, annex, contract] = CELINA_DOCUMENTS;
    expect(documentStatus(contract).label).toBe("podpisana");
    expect(documentStatus(annex).label).toBe("podpisany");
    expect(documentStatus(statement)).toMatchObject({ label: "dostarczone", note: "02.10.2026" });
    const removed = hrView().documents.find((row) => row.deleted);
    expect(removed && documentStatus(removed)).toMatchObject({
      label: "usunięty",
      note: "03.10.2026 · pomyłka",
    });
  });

  it("krąg słowami: Kadry zawsze, reszta według znaczników", () => {
    expect(audienceLabel({ person: true, payroll: true, equipment: false })).toBe(
      "osoba, Kadry, Płace",
    );
    expect(audienceLabel({ person: false, payroll: false, equipment: true })).toBe(
      "Kadry, recepcja",
    );
  });

  it("protokół sprzętu to odnośnik: rodzaj „protokół”, krąg osoba, Kadry, recepcja", () => {
    const row = protocolRow(CELINA_PROTOCOLS[0]);
    expect(row.title).toBe("Protokół wydania sprzętu PZO/2026/10/004");
    expect(row.kindLabel).toBe("protokół");
    expect(row.audience).toBe("osoba, Kadry, recepcja");
    expect(row.document).toBeNull();
  });

  it("kolejność: dokumenty, protokoły, na końcu usunięte", () => {
    const rows = documentRows(hrView().documents, hrView().protocols);
    expect(rows.map((row) => row.key)).toEqual(["d7003", "d7002", "d7001", "p8801", "d7000"]);
    expect(rows.at(-1)?.muted).toBe(true);
  });

  it("rozmiar pliku po polsku", () => {
    expect(fileSizeLabel(184_320)).toBe("180 KB");
    expect(fileSizeLabel(2_516_582)).toBe("2,4 MB");
  });

  it("zasilenie kartoteki opisane zdaniem, brak zasilenia — brak zdania", () => {
    expect(profileSyncMessage(null)).toBeNull();
    expect(profileSyncMessage({ status: "updated", until: "2027-06-30" })).toMatch(/30 dni/);
    expect(profileSyncMessage({ status: "not_zlecenie", until: null })).toMatch(/zlecenie/);
    expect(profileSyncMessage({ status: "kept_earlier", until: "2027-01-01" })).toMatch(
      /wcześniejsza/,
    );
  });
});
