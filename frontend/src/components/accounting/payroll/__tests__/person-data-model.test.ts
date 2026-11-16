import { describe, expect, it } from "vitest";

import {
  nipChecksumOk,
  peselChecksumOk,
  personForm,
  personFormProblems,
  personUpdate,
} from "../person-data-model";
import { personData } from "./payroll-fixtures";

// Numery składane w teście z wymyślonej daty i serii (repo publiczne: bez
// PESEL-i wpisanych na stałe); NIP fikcyjny z poprawną sumą kontrolną.
const WEIGHTS = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3];
function syntheticPesel(body: string): string {
  const total = body.split("").reduce((sum, digit, i) => sum + Number(digit) * WEIGHTS[i], 0);
  return body + String((10 - (total % 10)) % 10);
}
const PESEL = syntheticPesel("9001011234");
const WRONG_PESEL = PESEL.slice(0, 10) + String((Number(PESEL[10]) + 1) % 10);
const NIP = "1234563218";

describe("formularz danych płacowych", () => {
  it("nie wypełnia PESEL-u, dokumentu ani rachunku — API ich nie zwraca", () => {
    const form = personForm(personData({ document_type: "passport", document_masked: "•••789", bank_account_last4: "4321" }));
    expect(form.pesel).toBe("");
    expect(form.document_number).toBe("");
    expect(form.bank_account).toBe("");
    expect(form.document_type).toBe("passport");
    expect(form.pit2).toBe("12");
    expect(form.address.country).toBe("PL");
    expect(form.nfz_code).toBe("07R");
    expect(form.work_time).toBe("1/1");
  });

  it("bez zmian nie wysyła niczego", () => {
    const data = personData();
    expect(personUpdate(data, personForm(data))).toBeNull();
  });

  it("wysyła tylko zmienione pola i wersję", () => {
    const data = personData();
    const form = { ...personForm(data), pesel: ` ${PESEL} `, pit2: "0" as const, reliefs: ["senior" as const] };
    expect(personUpdate(data, form)).toEqual({ expected_version: 3, pesel: PESEL, pit2: 0, reliefs: ["senior"] });
  });

  it("imię i nazwisko z podpowiedzi konta idą przy każdym zapisie — zapis je potwierdza", () => {
    const data = personData({ names_confirmed: false });
    expect(personUpdate(data, personForm(data))).toEqual({ expected_version: 3, first_name: "Jan", last_name: "Testowy" });
  });

  it("adres idzie w całości, gdy zmieniło się jedno pole; pusty adres czyści", () => {
    const data = personData();
    const form = personForm(data);
    const changed = personUpdate(data, { ...form, address: { ...form.address, flat_number: "5" } });
    expect(changed?.address).toMatchObject({ country: "PL", city: "Testowo", flat_number: "5", postal_code: "00-001" });
    const empty = Object.fromEntries(Object.keys(form.address).map((key) => [key, key === "country" ? "PL" : ""]));
    expect(personUpdate(data, { ...form, address: empty as typeof form.address })?.address).toBeNull();
    const none = personData({ address: null });
    expect(personUpdate(none, personForm(none))).toBeNull();
  });

  it("oddział NFZ: pusty wraca do województwa, wymiar etatu tylko dla osoby z zespołu", () => {
    const data = personData();
    const form = personForm(data);
    expect(personUpdate(data, { ...form, nfz_code: "" })).toEqual({ expected_version: 3, nfz_code: null });
    expect(personUpdate(data, { ...form, nfz_code: "06r" })).toEqual({ expected_version: 3, nfz_code: "06R" });
    expect(personUpdate(data, { ...form, work_time: "1/2" })).toEqual({ expected_version: 3, work_time: "1/2" });
    const contractor = personData({ user_id: null, candidate_id: 21, subject: "c21" });
    expect(personUpdate(contractor, { ...personForm(contractor), work_time: "1/2" })).toBeNull();
  });

  it("PPK: włączenie z wpłatami, wyłączenie samym znacznikiem", () => {
    const data = personData();
    const on = personUpdate(data, { ...personForm(data), ppk_participates: true, ppk_employee_rate: "1,5" });
    expect(on?.ppk).toEqual({ participates: true, employee_rate: "1.5", employee_extra: "0", employer_extra: "0" });
    const saved = personData({ ppk: { employee_rate: "2.00", employee_extra: "0.00", employer_extra: "0.50" } });
    expect(personUpdate(saved, personForm(saved))).toBeNull();
    expect(personUpdate(saved, { ...personForm(saved), ppk_participates: false })?.ppk).toEqual({ participates: false });
  });

  it("rachunek i „student do” tylko dla kontraktora; NIP bez PESEL-u", () => {
    const contractor = personData({ user_id: null, candidate_id: 21, subject: "c21", pesel_masked: null });
    const form = personForm(contractor);
    expect(
      personUpdate(contractor, { ...form, bank_account: "12 3456", student_exempt_until: "2027-06-30", nip: NIP }),
    ).toEqual({ expected_version: 3, bank_account: "123456", student_exempt_until: "2027-06-30", nip: NIP });
    const team = personData();
    expect(personUpdate(team, { ...personForm(team), bank_account: "123", student_exempt_until: "2027-06-30" })).toBeNull();
  });
});

describe("sprawdzenie przed zapisem", () => {
  it("liczy sumy kontrolne PESEL-u i NIP-u", () => {
    expect(peselChecksumOk(PESEL)).toBe(true);
    expect(peselChecksumOk(WRONG_PESEL)).toBe(false);
    expect(nipChecksumOk(NIP)).toBe(true);
    expect(nipChecksumOk("1234563219")).toBe(false);
  });

  it("zatrzymuje złe numery i kody z tymi samymi zdaniami co serwer", () => {
    const data = personData({ user_id: null, candidate_id: 21, subject: "c21" });
    const form = personForm(data);
    expect(
      personFormProblems(
        {
          ...form,
          pesel: "1234",
          zus_title_code: "0110",
          tax_office_code: "12",
          nfz_code: "17R",
          nip: "123",
          ppk_participates: true,
          ppk_employee_rate: "3",
          bank_account: "123",
          address: { ...form.address, postal_code: "00001" },
        },
        data,
      ),
    ).toEqual([
      "PESEL to 11 cyfr.",
      "NIP osoby: 10 cyfr z poprawną cyfrą kontrolną.",
      "Kod pocztowy: w formacie 00-000.",
      "Kod urzędu skarbowego: 4 cyfry.",
      "Kod tytułu ubezpieczenia: 6 cyfr, np. 011000.",
      "Oddział NFZ: od 01R do 16R.",
      "PPK — wpłata podstawowa osoby: od 0,5 do 2%.",
      "Rachunek: 26 cyfr numeru NRB.",
    ]);
  });

  it("wymiar etatu sprawdza tylko u osoby z zespołu; dokument wymaga rodzaju", () => {
    const team = personData({ pesel_masked: null });
    expect(personFormProblems({ ...personForm(team), work_time: "3/2" }, team)).toEqual([
      "Wymiar etatu: ułamek, np. 1/1 albo 1/2.",
    ]);
    expect(personFormProblems({ ...personForm(team), document_number: "ABC12345" }, team)).toEqual([
      "Podaj rodzaj dokumentu.",
    ]);
    expect(personFormProblems(personForm(team), team)).toEqual([]);
  });
});
