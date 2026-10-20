import { fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { constellationName, constellationPoints, STAR_POSITIONS } from "../ConstellationScene";
import { mockMatchMedia, renderScene } from "./sceneTestUtils";

afterEach(() => vi.unstubAllGlobals());

describe("scena Konstelacja", () => {
  it("linia idzie w kolejności klikania, nazwa rośnie z liczbą gwiazd", () => {
    expect(constellationPoints([2, 0])).toBe(`${STAR_POSITIONS[2].join(",")} ${STAR_POSITIONS[0].join(",")}`);
    expect(constellationName(0)).toBe("Twój gwiazdozbiór: jeszcze pusty");
    expect(constellationName(3)).toBe("Twój gwiazdozbiór: „Trójkąt Danych”");
    expect(constellationName(5)).toBe("Twój gwiazdozbiór: „Pełna Platforma”");
  });

  it("kliknięte gwiazdy łączą się, numer = kolejność, „zacznij od nowa” czyści wynik", () => {
    const s = renderScene("konstelacja");
    const full = s.full();
    fireEvent.click(full.getByRole("button", { name: /^PostgreSQL/ }));
    fireEvent.click(full.getByRole("button", { name: /^Java Spring Boot/ }));
    expect(full.getByRole("button", { name: /^PostgreSQL/ })).toHaveTextContent("1");
    expect(full.getByRole("button", { name: /^Java Spring Boot/ })).toHaveTextContent("2");
    expect(full.getByText("PostgreSQL → Java Spring Boot")).toBeInTheDocument();
    expect(s.container.querySelector("polyline")).toHaveAttribute(
      "points",
      `${STAR_POSITIONS[2].join(",")} ${STAR_POSITIONS[0].join(",")}`,
    );
    expect(s.score().getByText("2/5")).toBeInTheDocument();
    expect(s.compact().getByRole("button", { name: /^PostgreSQL/ })).toHaveTextContent("★ 1");
    fireEvent.click(full.getByRole("button", { name: "zacznij od nowa" }));
    expect(s.score().getByText("0/5")).toBeInTheDocument();
    expect(s.container.querySelector("polyline")).toBeNull();
  });

  it("ograniczenie ruchu: linia bez rysowania, gwiazdy dalej się łączą", () => {
    mockMatchMedia((q) => q.includes("reduce"));
    const s = renderScene("konstelacja");
    fireEvent.click(s.full().getByRole("button", { name: /^Kafka/ }));
    fireEvent.click(s.full().getByRole("button", { name: /^English/ }));
    expect(s.container.querySelector("polyline")).not.toHaveClass("kr-const-draw");
    expect(s.score().getByText("2/5")).toBeInTheDocument();
  });
});
