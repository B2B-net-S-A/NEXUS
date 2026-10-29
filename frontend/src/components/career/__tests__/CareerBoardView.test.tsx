/**
 * Tablica otwartych rekrutacji (strona główna kariery, etap 6): pusty stan tylko
 * przy udanym odczycie, awaria ≠ pusta lista, filtry z licznikami, „pokaż
 * kolejne”, karta na link prowadzącego, „Zostaw CV” stałym linkiem HoR
 * i kontrast tekstu na kartach (≥ 4,5:1).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CareerBoardView } from "@/components/career/CareerBoardView";
import { CAREER_THEME_IDS, CAREER_THEMES } from "@/components/career/themes";
import type { CareerBoardJob, CareerBoardResponse } from "@/lib/career/api";

const job = (i: number, over: Partial<CareerBoardJob> = {}): CareerBoardJob => ({
  slug: `rekrutacja-${i}`,
  title: `Java Developer ${i}`,
  subtitle: null,
  city: "Warszawa",
  remote_policy: "hybrid",
  category: "development",
  theme: CAREER_THEME_IDS[i % CAREER_THEME_IDS.length],
  recruiter_first_name: "Marta",
  ...over,
});

const DATA: CareerBoardResponse = {
  cv: { slug: "olga-r", first_name: "Olga" },
  jobs: [
    job(1, { title: "Tester automatyzujący", category: "qa", remote_policy: "remote", city: null }),
    ...Array.from({ length: 14 }, (_, i) => job(i + 2)),
  ],
};

const view = (data: CareerBoardResponse | null) =>
  render(<CareerBoardView data={data} base="" footer={<footer>stopka</footer>} />);

describe("CareerBoardView", () => {
  it("karty prowadzą na link prowadzącego, 12 na start, potem „pokaż kolejne”", () => {
    view(DATA);
    const cards = () => screen.getAllByRole("link", { name: /Zobacz/ });
    expect(cards()).toHaveLength(12);
    expect(cards()[0]).toHaveAttribute("href", "/r/rekrutacja-1");
    expect(cards()[0]).toHaveTextContent("rekruter: Marta");
    expect(screen.getByText(/\[15 otwartych · projekty B2B/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /pokaż kolejne 3/ }));
    expect(cards()).toHaveLength(15);
    expect(screen.queryByRole("button", { name: /pokaż kolejne/ })).toBeNull();
  });

  it("filtry: kategoria z licznikami, szukanie, tryb pracy, wyczyszczenie", () => {
    view(DATA);
    const cats = screen.getByRole("group", { name: "Kategoria" });
    expect(within(cats).getByRole("button", { name: "wszystkie · 15" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Kategorie bez kart nie zajmują miejsca.
    expect(within(cats).queryByRole("button", { name: /infra/ })).toBeNull();
    fireEvent.click(within(cats).getByRole("button", { name: "qa · 1" }));
    expect(screen.getAllByRole("link", { name: /Zobacz/ })).toHaveLength(1);
    expect(document.querySelector(".kr-board-out")).toHaveTextContent("1 z 15");

    fireEvent.click(within(cats).getByRole("button", { name: "wszystkie · 15" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w rekrutacjach" }), {
      target: { value: "tester" },
    });
    expect(screen.getAllByRole("link", { name: /Zobacz/ })).toHaveLength(1);
    expect(within(cats).getByRole("button", { name: "qa · 1" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "stacjonarnie" }));
    expect(screen.getByText("Nic nie pasuje do filtrów.")).toBeInTheDocument();
    expect(screen.queryByText("Brak otwartych rekrutacji.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "$ wyczyść filtry" }));
    expect(screen.getAllByRole("link", { name: /Zobacz/ })).toHaveLength(12);
  });

  it("podgląd: scena wiersza pod myszą, z wymaganiami; ukryty przed czytnikiem i Tabem", () => {
    view({
      ...DATA,
      jobs: [
        job(1, { title: "Data Engineer", theme: "grafit", must: ["Spark", "Airflow"], nice: ["dbt"] }),
        job(2, { title: "DevOps Engineer", theme: "terminal", must: ["Kubernetes"] }),
      ],
    });
    const preview = document.querySelector(".kr-board-preview") as HTMLElement;
    expect(preview).toHaveAttribute("aria-hidden", "true");
    expect(preview).toHaveAttribute("tabindex", "-1");
    expect(preview).toHaveTextContent("Data Engineer");
    expect(preview).toHaveTextContent("Spark");
    expect(preview).toHaveTextContent(/dbt\s*mile widziane/);

    const rows = screen.getAllByRole("link", { name: /Zobacz/ });
    fireEvent.mouseEnter(rows[1]);
    expect(preview).toHaveTextContent("DevOps Engineer");
    expect(preview).toHaveAttribute("href", "/r/rekrutacja-2");
    expect(rows[1]).toHaveAttribute("data-active");
    fireEvent.focus(rows[0]);
    expect(preview).toHaveTextContent("Data Engineer");
  });

  it("szukanie po wymaganiach z karty", () => {
    view({ ...DATA, jobs: [job(1, { must: ["Kafka"] }), job(2)] });
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w rekrutacjach" }), {
      target: { value: "kafka" },
    });
    expect(screen.getAllByRole("link", { name: /Zobacz/ })).toHaveLength(1);
    expect(document.querySelector(".kr-board-out")).toHaveTextContent("1 z 2");
  });

  it("pusta tablica po udanym odczycie: „Brak otwartych rekrutacji” i „Zostaw CV”", () => {
    view({ ...DATA, jobs: [] });
    expect(screen.getByText("Brak otwartych rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Kategoria" })).toBeNull();
    expect(screen.getAllByRole("button", { name: /Zostaw CV/ }).length).toBeGreaterThan(0);
  });

  it("awaria API to komunikat o błędzie, nigdy pusta lista", () => {
    view(null);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać otwartych rekrutacji");
    expect(screen.queryByText("Brak otwartych rekrutacji.")).toBeNull();
    expect(screen.getByText("stopka")).toBeInTheDocument();
  });

  it("„Zostaw CV” otwiera formularz bazy (bez rekrutacji) na stałym linku HoR", () => {
    view(DATA);
    expect(screen.queryByRole("button", { name: /dołącz do bazy/ })).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: /^Zostaw CV/ })[0]);
    const cv = screen.getByRole("region", { name: "Nie widzisz nic dla siebie?" });
    expect(within(cv).getByRole("button", { name: /dołącz do bazy/ })).toBeInTheDocument();
    // Link rekrutera ma tylko zgodę na przyszłe procesy.
    expect(cv.textContent).toMatch(/przyszłych procesów rekrutacyjnych/);
    expect(screen.queryByRole("button", { name: "Zostaw CV — odezwiemy się" })).toBeNull();
  });

  it("bez linku HoR nie ma „Zostaw CV”", () => {
    view({ ...DATA, cv: null });
    expect(screen.queryByRole("button", { name: /Zostaw CV/ })).toBeNull();
  });
});

// ── kontrast ────────────────────────────────────────────────────────────────

const css = readFileSync(join(__dirname, "..", "career.css"), "utf8");
const token = (name: string) =>
  new RegExp(`--kr-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`).exec(css)?.[1] ?? "";

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("kontrast tablicy", () => {
  it("tekst karty, filtrów i liczników ≥ 4,5:1 (motyw Terminal strony głównej)", () => {
    for (const bg of ["form-bg", "input-bg", "bg", "tint-strong"]) {
      for (const fg of ["white", "text", "para", "gray", "red"]) {
        expect(contrast(token(fg), token(bg)), `${fg} na ${bg}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("nazwa sceny i kategoria na pasku sceny ≥ 4,5:1 w każdym szablonie", () => {
    for (const id of CAREER_THEME_IDS) {
      const p = CAREER_THEMES[id];
      expect(contrast(p.muted, p.bg), `${id}: scena`).toBeGreaterThanOrEqual(4.5);
      expect(contrast(p.text, p.bg), `${id}: kategoria`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
