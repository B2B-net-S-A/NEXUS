import { describe, expect, it } from "vitest";

import {
  jobRowTitle,
  jobWorkModeFull,
  jobWorkModeShort,
} from "@/lib/job-row-summary";

describe("jobRowTitle — sama nazwa stanowiska w wierszu listy", () => {
  it("z tytułu roboczego automatu bierze pierwszy człon (rolę)", () => {
    expect(
      jobRowTitle({
        title: "Programista Python (ZOB-2947)",
        working_title: "Programista Python · Python, Microservices · 6+ lat",
        working_title_auto: true,
        must_skills: ["Python", "Microservices"],
      }),
    ).toBe("Programista Python");
  });

  it("brak flagi automatu liczy się jak automat (starszy backend)", () => {
    expect(
      jobRowTitle({
        title: "DevSecOps (ZOB-3030)",
        working_title: "DevSecOps · Linux · 3+ lata",
      }),
    ).toBe("DevSecOps");
  });

  it("tytuł wpisany ręcznie zostaje w całości", () => {
    expect(
      jobRowTitle({
        title: "Java Dev",
        working_title: "Java · zespół płatności · pilne",
        working_title_auto: false,
      }),
    ).toBe("Java · zespół płatności · pilne");
  });

  it("automat bez roli zaczyna od must-have — wtedy nazwa od klienta", () => {
    expect(
      jobRowTitle({
        title: "Specjalista ds. integracji",
        working_title: "Java, Kafka · 5+ lat",
        working_title_auto: true,
        must_skills: [{ name: "Java" }, { name: "Kafka" }, { name: "SQL" }],
      }),
    ).toBe("Specjalista ds. integracji");
  });

  it("bez tytułu roboczego pokazuje nazwę od klienta, a bez niej numer rekrutacji", () => {
    expect(jobRowTitle({ title: "Tester automatyzujący" })).toBe(
      "Tester automatyzujący",
    );
    expect(jobRowTitle({ id: 7 })).toBe("Rekrutacja #7");
  });
});

describe("jobWorkModeShort — tryb pracy w wierszu", () => {
  it("zdalnie nie pokazuje miasta", () => {
    expect(
      jobWorkModeShort({ remote_policy: "remote", location: "Warszawa" }),
    ).toBe("Zdalnie");
  });

  it("hybrydowo z jednym miastem i z kilkoma", () => {
    expect(
      jobWorkModeShort({ remote_policy: "hybrid", location: "Warszawa" }),
    ).toBe("Hybrydowo · Warszawa");
    expect(
      jobWorkModeShort({
        remote_policy: "hybrid",
        location: "Warszawa, Gdańsk, Gdynia",
      }),
    ).toBe("Hybrydowo · Warszawa +2");
  });

  it("samo miasto bez trybu i sam tryb bez miasta", () => {
    expect(jobWorkModeShort({ location: "Kraków" })).toBe("Kraków");
    expect(jobWorkModeShort({ remote_policy: "onsite" })).toBe("Stacjonarnie");
  });

  it("kraj to nie miasto; brak danych = null", () => {
    expect(jobWorkModeShort({ location: "Polska" })).toBeNull();
    expect(jobWorkModeShort({})).toBeNull();
    expect(jobWorkModeShort({ remote_policy: "nieznany" })).toBeNull();
  });
});

describe("jobWorkModeFull — pełny zapis w Podglądzie", () => {
  it("tryb, dni w biurze i wszystkie miasta", () => {
    expect(
      jobWorkModeFull({
        remote_policy: "hybrid",
        onsite_days_per_week: 2,
        location: "Warszawa, Gdańsk",
      }),
    ).toBe("Hybrydowo · 2 dni w tygodniu · Warszawa, Gdańsk");
  });

  it("wpis miesięczny wygrywa z tygodniowym", () => {
    expect(
      jobWorkModeFull({
        remote_policy: "hybrid",
        onsite_days_per_week: 1,
        onsite_days_per_month: 2,
      }),
    ).toBe("Hybrydowo · 2 dni w miesiącu");
  });

  it("zdalnie pomija dni w biurze; lokalizacja bez miasta zostaje dosłownie", () => {
    expect(
      jobWorkModeFull({ remote_policy: "remote", onsite_days_per_week: 0 }),
    ).toBe("Zdalnie");
    expect(jobWorkModeFull({ location: "Polska" })).toBe("Polska");
    expect(jobWorkModeFull({})).toBeNull();
  });

  it("lokalizacja, która powtarza tryb pracy, nie stoi drugi raz", () => {
    expect(jobWorkModeFull({ remote_policy: "remote", location: "Zdalnie" })).toBe(
      "Zdalnie",
    );
    expect(jobWorkModeFull({ remote_policy: "remote", location: "Remote (PL)" })).toBe(
      "Zdalnie",
    );
    expect(jobWorkModeFull({ remote_policy: "remote", location: "Polska" })).toBe(
      "Zdalnie · Polska",
    );
  });
});
