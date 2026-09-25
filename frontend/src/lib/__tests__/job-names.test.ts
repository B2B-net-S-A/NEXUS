import { describe, expect, it } from "vitest";

import fixture from "@/lib/__fixtures__/job-working-title-cases.json";
import {
  composeWorkingTitle,
  jobClientLine,
  jobClientTitle,
  jobDisplayTitle,
  jobNamesDraft,
  jobNamesPatch,
} from "@/lib/job-names";

type Case = {
  name: string;
  input: {
    role: string | null;
    must: (string | { name: string })[];
    min_years: number | null;
    domain: string | null;
  };
  expected: string | null;
};

describe("composeWorkingTitle — lustro backendu (job_working_title.py)", () => {
  it.each((fixture.cases as Case[]).map((c) => [c.name, c] as const))("%s", (_, c) => {
    expect(
      composeWorkingTitle(c.input.role, c.input.must, c.input.min_years, c.input.domain),
    ).toBe(c.expected);
  });
});

describe("tytuł na ekranach wewnętrznych", () => {
  const job = {
    id: 5,
    title: "Programista Java (ZOB 48213)",
    working_title: "Java Developer · Java, Kafka · 5+ lat",
    client_reference: "ZOB 48213",
    client_name: "PKO BP",
  };

  it("pokazuje tytuł dla rekrutera, a pod nim klienta, nazwę i numer od klienta", () => {
    expect(jobDisplayTitle(job)).toBe("Java Developer · Java, Kafka · 5+ lat");
    expect(jobClientLine(job)).toBe("PKO BP · „Programista Java (ZOB 48213)” · ZOB 48213");
  });

  it("bez tytułu dla rekrutera nie powtarza nazwy od klienta w drugiej linii", () => {
    const bare = { ...job, working_title: null };
    expect(jobDisplayTitle(bare)).toBe("Programista Java (ZOB 48213)");
    expect(jobClientTitle(bare)).toBeNull();
    expect(jobClientLine(bare)).toBe("PKO BP · ZOB 48213");
    expect(jobDisplayTitle({ id: 9, title: " " })).toBe("Rekrutacja #9");
  });
});

describe("jobNamesPatch — PATCH niesie wyłącznie zmienione nazwy", () => {
  const auto = { title: "A", working_title: "Auto", working_title_auto: true, client_reference: null };

  it("brak zmian = pusty patch (zapis treści nie rusza nazw)", () => {
    expect(jobNamesPatch(auto, jobNamesDraft(auto))).toEqual({});
  });

  it("ręczny tytuł wyłącza automat, numer u klienta zapisuje się przycięty", () => {
    expect(
      jobNamesPatch(auto, {
        clientReference: " ZOB 1 ",
        workingTitle: "Mój tytuł",
        workingTitleManual: true,
      }),
    ).toEqual({ client_reference: "ZOB 1", working_title: "Mój tytuł" });
  });

  it("„Przywróć automatyczny” wysyła pusty tytuł, wyczyszczony numer = null", () => {
    const manual = { ...auto, working_title: "Ręczny", working_title_auto: false, client_reference: "ZOB 1" };
    expect(
      jobNamesPatch(manual, { clientReference: "", workingTitle: "", workingTitleManual: false }),
    ).toEqual({ client_reference: null, working_title: "" });
  });
});
