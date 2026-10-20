import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderScene } from "./sceneTestUtils";

describe("scena Architektura C4", () => {
  it("C2: cztery kontenery i granica systemu; krawędź świeci, gdy oba końce zaprojektowane", () => {
    const s = renderScene("c4");
    const full = s.full();
    expect(full.getByRole("button", { name: "C2 · kontenery" })).toHaveAttribute("aria-pressed", "true");
    const edge = () => s.container.querySelector('path.kr-c4-edge[d^="M224 74L100"]');
    fireEvent.click(full.getByRole("button", { name: /^Java Spring Boot/ }));
    expect(edge()).not.toHaveAttribute("data-on");
    fireEvent.click(full.getByRole("button", { name: /^Kafka/ }));
    expect(edge()).toHaveAttribute("data-on");
    const boundary = full.getByRole("button", { name: "Kubernetes (mile widziane)" });
    expect(boundary).toHaveTextContent("[granica] Kubernetes — kliknij");
    fireEvent.click(boundary);
    expect(boundary).toHaveTextContent("— zaprojektowana");
    expect(s.score().getByText("Zaprojektowane")).toBeInTheDocument();
    expect(s.score().getByText("3/5")).toBeInTheDocument();
  });

  it("C1 to kontekst bez punktów; powrót do C2 zachowuje zaznaczenia", () => {
    const s = renderScene("c4");
    fireEvent.click(s.full().getByRole("button", { name: /^PostgreSQL/ }));
    fireEvent.click(s.full().getByRole("button", { name: "C1 · kontekst" }));
    expect(s.full().queryByRole("button", { name: /^PostgreSQL/ })).toBeNull();
    expect(s.full().getByText(/Marta · rekrutacja/)).toBeInTheDocument();
    fireEvent.click(s.full().getByRole("button", { name: /przełącz na C2/ }));
    expect(s.full().getByRole("button", { name: /^PostgreSQL/ })).toHaveAttribute("aria-pressed", "true");
    expect(s.compact().getByRole("button", { name: /^PostgreSQL/ })).toHaveTextContent("[kontener] ✓");
    expect(s.compact().getByRole("button", { name: "English" })).toHaveTextContent("[baza]");
  });

  it("trzy wymagania — bez granicy i bez krawędzi do brakującego klocka", () => {
    const s = renderScene("c4", {
      must: [
        { name: "A", note: null },
        { name: "B", note: null },
        { name: "C", note: null },
      ],
      nice: [],
    });
    expect(s.full().getAllByRole("button", { pressed: false })).toHaveLength(4); // C1 + 3 klocki
    expect(s.container.querySelectorAll("path.kr-c4-edge")).toHaveLength(2);
    expect(s.score().getByText("0/3")).toBeInTheDocument();
  });
});
