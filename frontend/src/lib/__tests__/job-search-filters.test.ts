import { describe, expect, it } from "vitest";

import type { CriticalResolution } from "@/lib/critical-skills";
import {
  candidatesListFiltersForQuery,
  criticalSearchRows,
  jobListFilters,
  jobSearchPlan,
  mandatorySourceNote,
  splitByCritical,
  type ManualSearchJob,
} from "@/lib/job-search-filters";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

const critical = (patch: Partial<CriticalResolution>): CriticalResolution => ({
  stored: null,
  decided: true,
  effective: [],
  source: "dl",
  suggested: [],
  ...patch,
});

const job = (profile: unknown): ManualSearchJob => ({
  id: 7,
  title: "Java Developer",
  champion_profile: profile,
});

describe("wiersze obowiązkowe czytają krytyczną jak bramka AI", () => {
  it("krytyczna „Java 11+” trafia w wiersz Championa „Java 17” — bez osobnego dosłownego wiersza", () => {
    const split = splitByCritical(
      [["Java 17"], ["Spring"]],
      [],
      critical({ effective: ["Java 11+"], search_rows: [["Java"]] }),
    );
    expect(split.required).toEqual([["Java 17", "Java"]]);
    expect(split.preferred).toEqual([["Spring"]]);
  });

  it("`must` = niekrytyczne wiersze Championa; `preferred` bez zmian (must + „mile widziane”)", () => {
    const split = splitByCritical(
      [["Java 17"], ["Spring"], ["SQL", "PL/SQL"]],
      [["Scala"], ["spring"]],
      critical({ effective: ["Java"], search_rows: [["Java"]] }),
    );
    expect(split.required).toEqual([["Java 17", "Java"]]);
    expect(split.must).toEqual([["Spring"], ["SQL", "PL/SQL"]]);
    // „spring” z „mile widzianych” to ten sam wiersz co must — nie dubluje się.
    expect(split.preferred).toEqual([["Spring"], ["SQL", "PL/SQL"], ["Scala"]]);
    expect(split.preferred.slice(0, split.must.length)).toEqual(split.must);
    // Kopie, nie te same tablice: zmiana jednej listy nie rusza drugiej.
    expect(split.preferred[0]).not.toBe(split.must[0]);
  });

  it("bez krytycznych wszystkie wiersze Championa są `must`, a filtry listy się nie zmieniają", () => {
    const source = job({ search: { requirements: [["KYC"], ["AML"]] } });
    const resolution = critical({ effective: [], search_rows: [] });
    const plan = jobSearchPlan(source, resolution);
    expect(plan.split.must).toEqual([["KYC"], ["AML"]]);
    const filters = jobListFilters(source, null, resolution);
    expect(filters.qAny).toEqual([]);
    expect(filters.qPreferred).toEqual([["KYC"], ["AML"]]);
  });

  it("odpowiedź bez `search_rows`: opcje bez wersji, „/”, „lub” i przykłady w nawiasie", () => {
    expect(
      criticalSearchRows(
        critical({
          effective: [
            "Java 11+",
            "Docker/Kubernetes",
            "Bazy danych (Oracle, PostgreSQL)",
            "Kafka lub RabbitMQ",
          ],
        }),
      ),
    ).toEqual([["Java"], ["Docker", "Kubernetes"], ["Oracle", "PostgreSQL"], ["Kafka", "RabbitMQ"]]);
  });

  it("krytyczna jednoliterowa nie staje się słowem kluczowym — ekran mówi to zdaniem", () => {
    const split = splitByCritical(
      [],
      [],
      critical({
        effective: ["R", "Kubernetes"],
        search_rows: [["Kubernetes"]],
        search_rows_skipped: ["R"],
      }),
    );
    expect(split.required).toEqual([["Kubernetes"]]);
    expect(mandatorySourceNote(split)).toContain("„R”");
    expect(mandatorySourceNote(split)).toContain("Umiejętności");
  });
});

describe("jedna reguła „są wiersze do szukania” (okno ręczne, zakładka, kafel)", () => {
  it("profil bez wymagań do wyszukiwania, ale z krytyczną z serwera — szukamy", () => {
    const resolution = critical({ effective: ["Kafka"], search_rows: [["Kafka", "Apache Kafka"]] });
    const source = job({ stack: { must: [{ name: "Kafka" }] } });
    const plan = jobSearchPlan(source, resolution);
    expect(plan.hasRows).toBe(true);
    expect(jobListFilters(source, null, resolution).qAny).toEqual(plan.split.required);
  });

  it("bez wierszy, bez krytycznych i bez „mile widzianych” — nie ma czego szukać", () => {
    const plan = jobSearchPlan(job({}), critical({ effective: [], search_rows: [] }));
    expect(plan.hasRows).toBe(false);
  });

  it("same wiersze „mile widziane” ze stack.rows też są wierszami do szukania", () => {
    const plan = jobSearchPlan(
      job({ stack: { rows: [{ words: ["Scala"], level: "nice" }] } }),
      critical({ effective: [], search_rows: [] }),
    );
    expect(plan.hasRows).toBe(true);
    expect(plan.split.preferred).toEqual([["Scala"]]);
  });
});

describe("candidatesListFiltersForQuery — okno „Szukaj ręcznie”", () => {
  const restored = {
    ...DEFAULT_FILTERS,
    recruitmentIds: [99],
    recruitmentClientIds: [3],
    recruitmentMatch: "assigned" as const,
    recruitmentPresence: "not_in_process" as const,
  };

  it("wymusza „nie w tej rekrutacji”, zdejmuje cudzy zakres, zostawia tryb", () => {
    const query = candidatesListFiltersForQuery(restored, { jobId: 7 });
    expect(query.recruitmentIds).toEqual([7]);
    expect(query.recruitmentMatch).toBe("not_assigned");
    // Zakres klienta z pamięci okna filtrowałby niewidocznie za zablokowanym polem.
    expect(query.recruitmentClientIds).toEqual([]);
    expect(query.recruitmentPresence).toBe("not_in_process");
  });

  it("poza oknem rekrutacji nie zmienia filtrów", () => {
    expect(candidatesListFiltersForQuery(restored, null)).toBe(restored);
  });
});
