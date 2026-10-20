import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { pingMs } from "../TopologyScene";
import { mockMatchMedia, renderScene } from "./sceneTestUtils";
import { afterEach, vi } from "vitest";

afterEach(() => vi.unstubAllGlobals());

describe("scena Topologia sieci", () => {
  it("kliknięty węzeł zestawia łącze z TY i puszcza pakiet", () => {
    const s = renderScene("topologia");
    const node = s.full().getByRole("button", { name: /^Kafka/ });
    expect(s.container.querySelectorAll(".kr-topo-pk")).toHaveLength(0);
    fireEvent.click(node);
    expect(node).toHaveAttribute("aria-pressed", "true");
    expect(s.container.querySelectorAll(".kr-topo-link[data-on]")).toHaveLength(1);
    expect(s.container.querySelectorAll(".kr-topo-pk")).toHaveLength(1);
    expect(s.score().getByText("Łącza zestawione")).toBeInTheDocument();
    expect(s.full().getByText(/ping do zespołu: 98 ms/)).toBeInTheDocument();
  });

  it("fokus klawiaturą pokazuje notatkę jak najechanie", () => {
    const s = renderScene("topologia");
    const node = s.full().getByRole("button", { name: /^PostgreSQL/ });
    fireEvent.focus(node);
    expect(s.full().getByText("schemat i zapytania")).toBeInTheDocument();
    expect(s.full().getByText("kliknij, jeśli to znasz")).toBeInTheDocument();
    fireEvent.blur(node);
    expect(s.full().queryByText("kliknij, jeśli to znasz")).toBeNull();
  });

  it("ping maleje z łączami i ma dolną granicę", () => {
    expect(pingMs(0)).toBe(120);
    expect(pingMs(5)).toBe(12);
  });

  it("ograniczenie ruchu: scena z data-kr-still, łącza działają", () => {
    mockMatchMedia((q) => q.includes("reduce"));
    const s = renderScene("topologia");
    expect(s.getByTestId("scene-full")).toHaveAttribute("data-kr-still");
    fireEvent.click(s.compact().getByRole("button", { name: /^English/ }));
    expect(s.container.querySelectorAll(".kr-topo-link[data-on]")).toHaveLength(1);
  });
});

describe("dymek topologii", () => {
  it("dolne węzły mają dymek nad sobą, górne pod sobą", async () => {
    const { tipPosition } = await import("../TopologyScene");
    expect(tipPosition([300, 72])).toEqual({ left: 200, top: 108 });
    expect(tipPosition([288, 428])).toEqual({ left: 188, bottom: 132 });
    expect(tipPosition([40, 100]).left).toBe(8);
  });
});
