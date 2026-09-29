/**
 * Słowniczek „Po ludzku”: jedna siatka dla nagłówka i każdego wiersza
 * (wyrównanie w pionie), tekst bez ucinania, stan opisu zamiast pustki.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GLOSSARY_GRID, PlainGlossaryTable } from "@/components/champion/plain/PlainGlossaryTable";
import type { GlossaryTerm } from "@/lib/api/plainKnowledge";

function term(patch: Partial<GlossaryTerm>): GlossaryTerm {
  return {
    term_key: "kafka",
    display_name: "Kafka",
    level: "must",
    level_label: "wymagane",
    status: "ready",
    summary: "Taśmociąg wiadomości między systemami.",
    does: null,
    cv_hints: ["Apache Kafka", "Confluent"],
    confused_with: null,
    in_this_project: null,
    sources: [],
    origin: "seed",
    ...patch,
  };
}

describe("PlainGlossaryTable", () => {
  it("nagłówek i każdy wiersz mają ten sam szablon kolumn", () => {
    render(
      <PlainGlossaryTable
        terms={[
          term({}),
          term({ term_key: "java", display_name: "Java", in_this_project: "Cały system." }),
        ]}
      />,
    );
    const header = screen.getByTestId("glossary-header");
    expect(within(header).getByText("Technologia")).toBeInTheDocument();
    expect(within(header).getByText("Po ludzku")).toBeInTheDocument();
    expect(within(header).getByText("W CV szukaj")).toBeInTheDocument();
    const grid = GLOSSARY_GRID.split(" ");
    const rowGrids = screen.getAllByTestId("glossary-row").map((row) =>
      row.tagName === "DETAILS" ? (row.querySelector("summary") as HTMLElement) : row,
    );
    expect(rowGrids).toHaveLength(2);
    for (const el of [header, ...rowGrids]) {
      for (const cls of grid) expect(el.className).toContain(cls);
    }
  });

  it("tekst się zawija, nigdy nie jest ucinany", () => {
    const { container } = render(<PlainGlossaryTable terms={[term({})]} />);
    expect(container.innerHTML).not.toMatch(/\btruncate\b|text-ellipsis|line-clamp/);
    expect(screen.getByText("Apache Kafka, Confluent")).toBeInTheDocument();
  });

  it("brak opisu i trwające szukanie mówią to wprost", () => {
    render(
      <PlainGlossaryTable
        terms={[
          term({ term_key: "a", display_name: "PSD2", status: "missing", summary: null }),
          term({ term_key: "b", display_name: "Kubernetes", status: "researching", summary: null }),
        ]}
      />,
    );
    const statuses = screen.getAllByTestId("glossary-status").map((el) => el.textContent);
    expect(statuses).toEqual(["Brak opisu", "Szukam opisu…"]);
  });

  it("rozwinięcie pokazuje „W tym projekcie”, „Nie myl z” i tylko bezpieczne źródła", () => {
    render(
      <PlainGlossaryTable
        terms={[
          term({
            in_this_project: "Po niej płyną transakcje.",
            confused_with: "RabbitMQ robi podobną rzecz.",
            sources: [
              { url: "https://kafka.apache.org/intro", title: "Kafka — wprowadzenie" },
              { url: "javascript:alert(1)", title: "zły link" },
            ],
          }),
        ]}
      />,
    );
    expect(screen.getByText("W tym projekcie")).toBeInTheDocument();
    expect(screen.getByText("Nie myl z")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kafka — wprowadzenie" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.queryByText("zły link")).not.toBeInTheDocument();
  });

  it("poziom „wymagane” ma kolor główny, „mile widziane” wyciszony", () => {
    render(
      <PlainGlossaryTable
        terms={[term({}), term({ term_key: "k8s", display_name: "K8s", level: "nice", level_label: "mile widziane" })]}
      />,
    );
    expect(screen.getByText("wymagane").className).toContain("text-primary");
    expect(screen.getByText("mile widziane").className).toContain("text-muted-foreground");
  });
});
