/**
 * Tablica otwartych rekrutacji (strona główna kariery, etap 6; od 29.10.2026
 * w barwach marki): pusty stan tylko przy udanym odczycie, awaria ≠ pusta
 * lista, filtry z licznikami, „pokaż kolejne”, karta na link prowadzącego
 * z wymaganiami, „Zostaw CV” stałym linkiem HoR i kontrast tekstu na kartach.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
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
  render(<CareerBoardView data={data} base="" host="kariera.b2bnetwork.pl" />);

const cards = () => screen.getAllByRole("link", { name: /Zobacz/ });

describe("CareerBoardView", () => {
  it("karty prowadzą na link prowadzącego, 12 na start, potem „Pokaż kolejne”", () => {
    view(DATA);
    expect(cards()).toHaveLength(12);
    expect(cards()[0]).toHaveAttribute("href", "/r/rekrutacja-1");
    expect(cards()[0]).toHaveTextContent("Rekruter: Marta");
    expect(cards()[1]).toHaveTextContent("Warszawa · Hybryda");
    expect(screen.getByText(/15 otwartych · Projekty B2B/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pokaż kolejne 3/ }));
    expect(cards()).toHaveLength(15);
    expect(screen.queryByRole("button", { name: /Pokaż kolejne/ })).toBeNull();
  });

  it("filtry: kategoria z licznikami, szukanie, tryb pracy, wyczyszczenie", () => {
    view(DATA);
    const cats = screen.getByRole("group", { name: "Kategoria" });
    expect(within(cats).getByRole("button", { name: "Wszystkie · 15" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Kategorie bez kart nie zajmują miejsca.
    expect(within(cats).queryByRole("button", { name: /Infra/ })).toBeNull();
    fireEvent.click(within(cats).getByRole("button", { name: "QA · 1" }));
    expect(cards()).toHaveLength(1);
    expect(screen.getByTestId("board-count")).toHaveTextContent("1 z 15");

    fireEvent.click(within(cats).getByRole("button", { name: "Wszystkie · 15" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w rekrutacjach" }), {
      target: { value: "tester" },
    });
    expect(cards()).toHaveLength(1);
    expect(within(cats).getByRole("button", { name: "QA · 1" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Stacjonarnie" }));
    expect(screen.getByText("Nic nie pasuje do filtrów.")).toBeInTheDocument();
    expect(screen.queryByText("Brak otwartych rekrutacji.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść filtry" }));
    expect(cards()).toHaveLength(12);
  });

  it("karta pokazuje kategorię i do 4 wymagań zamiast podglądu sceny", () => {
    view({
      ...DATA,
      jobs: [job(1, { title: "Data Engineer", category: "infra", must: ["Spark", "Airflow", "dbt", "SQL", "Kafka"] })],
    });
    const [card] = cards();
    expect(card).toHaveTextContent("Infra & data");
    expect(card).toHaveTextContent(/Spark.*Airflow.*dbt.*SQL/);
    expect(card).not.toHaveTextContent("Kafka");
    expect(document.querySelector(".kr-board-preview")).toBeNull();
  });

  it("szukanie po wymaganiach z karty", () => {
    view({ ...DATA, jobs: [job(1, { must: ["Kafka"] }), job(2)] });
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w rekrutacjach" }), {
      target: { value: "kafka" },
    });
    expect(cards()).toHaveLength(1);
    expect(screen.getByTestId("board-count")).toHaveTextContent("1 z 2");
  });

  it("pusta tablica po udanym odczycie: „Brak otwartych rekrutacji” i „Zostaw CV”", () => {
    view({ ...DATA, jobs: [] });
    expect(screen.getByText("Brak otwartych rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Kategoria" })).toBeNull();
    expect(screen.getByRole("button", { name: "Zostaw CV" })).toBeInTheDocument();
  });

  it("awaria API to komunikat o błędzie, nigdy pusta lista", () => {
    view(null);
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać otwartych rekrutacji");
    expect(screen.queryByText("Brak otwartych rekrutacji.")).toBeNull();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("kariera.b2bnetwork.pl");
  });

  it("„Zostaw CV” otwiera formularz bazy (bez rekrutacji) na stałym linku HoR", () => {
    view(DATA);
    expect(screen.queryByRole("button", { name: /dołącz do bazy/i })).toBeNull();
    expect(screen.getByRole("link", { name: "Zostaw CV" })).toHaveAttribute("href", "#zostaw-cv");
    fireEvent.click(screen.getByRole("button", { name: "Zostaw CV" }));
    const cv = screen.getByRole("region", { name: "Nie widzisz nic dla siebie?" });
    expect(within(cv).getByRole("button", { name: /dołącz do bazy/i })).toBeInTheDocument();
    // Link rekrutera ma tylko zgodę na przyszłe procesy.
    expect(cv.textContent).toMatch(/przyszłych procesów rekrutacyjnych/);
    expect(screen.queryByRole("button", { name: "Zostaw CV" })).toBeNull();
  });

  it("bez linku HoR nie ma „Zostaw CV”", () => {
    view({ ...DATA, cv: null });
    expect(screen.queryByRole("button", { name: /Zostaw CV/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Zostaw CV/ })).toBeNull();
  });

  it("bez śladów terminala", () => {
    const { container } = view(DATA);
    expect(container.textContent).not.toMatch(/\$ |ls ~|grep|zsh/);
  });
});

// ── kontrast ────────────────────────────────────────────────────────────────

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
  // Karty z `brand/brandPage.module.css`: #242424 na ciemnych szablonach, biel na Jasnym.
  const CARD = { dark: "#242424", light: "#FFFFFF" };

  it("tekst karty, filtrów i liczników ≥ 4,5:1 w każdym szablonie", () => {
    for (const id of CAREER_THEME_IDS) {
      const p = CAREER_THEMES[id];
      const card = p.light ? CARD.light : CARD.dark;
      for (const bg of [p.bg, card]) {
        for (const [name, fg] of Object.entries({ heading: p.heading, text: p.text, para: p.para, muted: p.muted, accent: p.accent })) {
          expect(contrast(fg, bg), `${id}: ${name} na ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      }
      expect(contrast(p.btnText, p.btn), `${id}: przycisk`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
