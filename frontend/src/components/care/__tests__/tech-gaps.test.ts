/** „Luki do dopytania” mapy technologii jako pytania (D16) i link „w bazie”. */
import { describe, expect, it } from "vitest";

import { candidatesHref, gapQuestion } from "@/components/care/tech-gaps";

describe("luki do dopytania", () => {
  it("dział bez źródła", () => {
    expect(
      gapQuestion({ kind: "area_no_source", area: { id: 1, name: "CI/CD i chmura" }, last_seen: null }),
    ).toEqual({
      key: "area-1",
      subject: "CI/CD i chmura",
      detail: "brak źródła od 18 miesięcy",
      question: "Jakich technologii używa teraz dział CI/CD i chmura?",
    });
  });

  it("menedżer bez „podlega pod” — z działem i bez", () => {
    const placed = gapQuestion({
      kind: "manager_unplaced",
      contact: { id: 7, name: "Michał Rogalski-Przykładowy" },
      position: null,
      area: { id: 3, name: "QA" },
      consultants: 1,
    });
    expect(placed.subject).toBe("QA");
    expect(placed.detail).toBe("nie wiemy, komu podlega Michał R.");
    expect(placed.question).toBe("Komu podlega Michał Rogalski-Przykładowy (QA)?");
    const loose = gapQuestion({
      kind: "manager_unplaced",
      contact: { id: 8, name: "Ola" },
      position: null,
      area: null,
      consultants: 2,
    });
    expect(loose.subject).toBe("Ola");
    expect(loose.question).toBe("Komu podlega Ola?");
  });

  it("technologia z jednego źródła: jedno odwołanie z datą, kilka z liczbą", () => {
    const one = gapQuestion({
      kind: "single_source",
      skill_id: 5,
      name: "Databricks",
      source: "jobs",
      refs: 1,
      last_seen: "2026-03-12",
      areas: ["Data"],
    });
    expect(one.detail).toBe("znane tylko z rekrutacji z 03.2026");
    expect(one.question).toBe("Czy Databricks jest naprawdę używany w dziale Data?");
    const many = gapQuestion({
      kind: "single_source",
      skill_id: 6,
      name: "Terraform",
      source: "notes",
      refs: 2,
      last_seen: null,
      areas: [],
    });
    expect(many.detail).toBe("znane tylko z notatek o stacku (2)");
    expect(many.question).toBe("Czy Terraform jest naprawdę używany?");
  });
});

describe("„w bazie” → lista kandydatów", () => {
  it("wszystkie umiejętności działu naraz, nazwy ze spacją w cudzysłowie", () => {
    const href = candidatesHref(["Java 17", "Kafka"]);
    expect(href).not.toBeNull();
    const url = new URL(href ?? "", "http://localhost");
    expect(url.pathname).toBe("/candidates");
    expect(url.searchParams.get("skills_q")).toBe('"Java 17" AND Kafka');
    expect(candidatesHref([])).toBeNull();
    expect(candidatesHref([" "])).toBeNull();
  });
});
