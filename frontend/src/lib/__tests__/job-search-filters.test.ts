import { describe, expect, it } from "vitest";

import type { CriticalResolution } from "@/lib/critical-skills";
import {
  criticalSearchRows,
  jobListFilters,
  jobSearchPlan,
  mandatorySourceNote,
  splitByCritical,
  type ManualSearchJob,
} from "@/lib/job-search-filters";

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
