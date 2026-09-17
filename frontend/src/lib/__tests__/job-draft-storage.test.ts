import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearJobDraft,
  isJobFormEmpty,
  readJobDraft,
  writeJobDraft,
  type JobDraftFormState,
} from "@/lib/job-draft-storage";

const EMPTY: JobDraftFormState = {
  title: "",
  clientId: null,
  clientName: null,
  recruitmentType: "body_leasing",
  description: "",
  mustHaveInput: "",
  location: "",
  remotePolicy: "",
  onsiteDaysPerWeek: "",
  rateBudgetHourly: "",
  salaryMin: "",
  salaryMax: "",
};

const FILLED: JobDraftFormState = {
  ...EMPTY,
  title: "Senior Java Developer",
  clientId: 42,
  clientName: "Acme",
  description: "Szukamy...",
};

beforeEach(() => {
  window.localStorage.clear();
});

describe("isJobFormEmpty", () => {
  it("uznaje formularz bez żadnej treści za pusty", () => {
    expect(isJobFormEmpty(EMPTY)).toBe(true);
  });

  it("uznaje formularz z tytułem za niepusty", () => {
    expect(isJobFormEmpty({ ...EMPTY, title: "x" })).toBe(false);
  });

  it("uznaje formularz z wybranym klientem za niepusty", () => {
    expect(isJobFormEmpty({ ...EMPTY, clientId: 1 })).toBe(false);
  });
});

describe("writeJobDraft / readJobDraft", () => {
  it("odczytuje to, co zapisano", () => {
    writeJobDraft(7, FILLED);
    const restored = readJobDraft(7);
    expect(restored?.form).toEqual(FILLED);
    expect(typeof restored?.savedAt).toBe("string");
  });

  it("klucz jest PER UŻYTKOWNIK — szkic użytkownika 7 nie wycieka do 8", () => {
    writeJobDraft(7, FILLED);
    expect(readJobDraft(8)).toBeNull();
  });

  it("zapis pustego formularza kasuje istniejący szkic zamiast go nadpisać pustką", () => {
    writeJobDraft(7, FILLED);
    writeJobDraft(7, EMPTY);
    expect(readJobDraft(7)).toBeNull();
    expect(window.localStorage.getItem("nexus:jobDraft:v1:7")).toBeNull();
  });

  it("brak zapisu → null", () => {
    expect(readJobDraft(999)).toBeNull();
  });

  it("uszkodzony JSON → null, nie wyjątek", () => {
    window.localStorage.setItem("nexus:jobDraft:v1:7", "{not json");
    expect(readJobDraft(7)).toBeNull();
  });

  it("inna wersja kontraktu → null", () => {
    window.localStorage.setItem(
      "nexus:jobDraft:v1:7",
      JSON.stringify({ version: 2, savedAt: new Date().toISOString(), form: FILLED }),
    );
    expect(readJobDraft(7)).toBeNull();
  });

  it("zapisany formularz pusty (np. zegar zapisał przed wypełnieniem) → null", () => {
    window.localStorage.setItem(
      "nexus:jobDraft:v1:7",
      JSON.stringify({ version: 1, savedAt: new Date().toISOString(), form: EMPTY }),
    );
    expect(readJobDraft(7)).toBeNull();
  });
});

describe("clearJobDraft", () => {
  it("kasuje zapisany szkic", () => {
    writeJobDraft(7, FILLED);
    clearJobDraft(7);
    expect(readJobDraft(7)).toBeNull();
  });

  it("jest bezpieczne, gdy nic nie było zapisane", () => {
    expect(() => clearJobDraft(999)).not.toThrow();
  });
});

describe("storage wyłączony (np. tryb prywatny)", () => {
  it("writeJobDraft nie rzuca, gdy `setItem` rzuca", () => {
    const spy = vi
      .spyOn(window.localStorage.__proto__, "setItem")
      .mockImplementation(() => {
        throw new Error("QuotaExceededError");
      });
    expect(() => writeJobDraft(7, FILLED)).not.toThrow();
    spy.mockRestore();
  });

  it("readJobDraft zwraca null, gdy `getItem` rzuca", () => {
    const spy = vi
      .spyOn(window.localStorage.__proto__, "getItem")
      .mockImplementation(() => {
        throw new Error("SecurityError");
      });
    expect(readJobDraft(7)).toBeNull();
    spy.mockRestore();
  });
});
