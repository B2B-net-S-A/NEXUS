import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CareerBoard } from "@/components/career/site/CareerBoard";
import { OfferPage } from "@/components/career/site/OfferPage";
import { atName } from "@/components/career/site/SentGate";
import type { CareerBoardJob, CareerBoardResponse, CareerJobResponse } from "@/lib/career/api";

const card = (slug: string, over: Partial<CareerBoardJob> = {}): CareerBoardJob => ({
  slug,
  title: `Rola ${slug}`,
  subtitle: null,
  city: "Warszawa",
  remote_policy: "hybrid",
  category: "development",
  theme: "grafit",
  recruiter_first_name: "Marta",
  must: [],
  nice: [],
  ...over,
});

const OPEN: CareerJobResponse = {
  status: "open",
  recruiter: { first_name: "Paulina", slug: null },
  canonical_slug: "kierownik-ab12",
  job: {
    slug: "kierownik-ab12",
    title: "Kierownik Projektów IT",
    subtitle: "Prowadzenie wdrożeń w banku",
    about:
      "Projekty obejmują wdrażanie nowych rozwiązań.\n\nCzym się zajmiesz: koordynacja projektu; raportowanie statusu; dokumentacja projektowa",
    must: [
      { name: "Doświadczenie w stosowaniu metodyki PRINCE2 lub Agile", note: null },
      { name: "Doświadczenie w zarządzaniu zespołem IT", note: null },
    ],
    nice: ["Doświadczenie w sektorze finansowym"],
    params: {
      city: "Warszawa, Łódź",
      remote_policy: "hybrid",
      onsite_days_per_week: 1,
      seniority: null,
      contract: "B2B",
      start: "2026-12-01",
      duration: null,
    },
    show: { must: true, nice: true, params: true, process: true },
  },
};

const BOARD: CareerBoardJob[] = [
  card("kierownik-ab12", { category: "management", must: ["metodyki PRINCE2 lub Agile", "PRINCE2", "zarządzaniu zespołem IT"] }),
  card("pm-2", { category: "management", title: "Project Manager" }),
  card("java-3", { title: "Java Developer", must: ["Java", "Kafka"], city: "Kraków", remote_policy: "onsite" }),
  card("qa-4", { category: "qa", title: "Tester", remote_policy: "remote", city: null }),
];

describe("strona oferty — jeden szablon dla każdej roli (OfertaA, OfertaManager)", () => {
  it("jedyny h1 to tytuł; fakty, sekcje z etykietami i cztery kroki procesu", () => {
    const { container } = render(<OfferPage data={OPEN} board={BOARD} base="" />);
    const h1 = container.querySelectorAll("h1");
    expect(h1).toHaveLength(1);
    expect(h1[0].textContent).toBe("Kierownik Projektów IT");
    for (const [label, value] of [
      ["Lokalizacja", "Warszawa, Łódź"],
      ["Tryb pracy", "Hybryda · 1 dzień w biurze w tygodniu"],
      ["Umowa", "B2B"],
    ]) {
      const dt = screen.getByText(label, { selector: "dt" });
      expect(dt.nextElementSibling?.textContent).toBe(value);
    }
    expect(screen.getByRole("complementary", { name: "Wymagania" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "O projekcie" })).toBeTruthy();
    const process = screen.getByRole("region", { name: "Proces rekrutacji" });
    expect(within(process).getAllByRole("listitem")).toHaveLength(4);
    expect(within(process).getByText("Rozmowa z Pauliną")).toBeTruthy();
    expect(within(process).getByText("Umowa B2B")).toBeTruthy();
    expect(container.querySelector("section#aplikuj[aria-label='Aplikuj']")).toBeTruthy();
    expect(screen.getByRole("form", { name: "Szybka aplikacja: samo CV" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Pełny formularz/ }).getAttribute("href")).toBe("#aplikuj");
  });

  it("technologie nad tytułem i pogrubienie tylko z krótkich umiejętności tablicy", () => {
    render(<OfferPage data={OPEN} board={BOARD} base="" />);
    // „metodyki PRINCE2 lub Agile” ma 26 znaków — za długie na pierwszą plakietkę, więc „PRINCE2”.
    const tags = within(screen.getByRole("list", { name: "Technologie" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(tags).toEqual(["PRINCE2", "zarządzaniu zespołem IT"]);
    expect(screen.getByRole("link", { name: "← Wszystkie oferty (4)" }).getAttribute("href")).toBe("/");
    // Pogrubienie bierze najdłuższą pasującą nazwę.
    expect(screen.getByText("metodyki PRINCE2 lub Agile", { selector: "b" })).toBeTruthy();
    expect(screen.getByText("zarządzaniu zespołem IT", { selector: "b" })).toBeTruthy();
    expect(screen.getByText("Czym się zajmiesz")).toBeTruthy();
    expect(screen.getByText("raportowanie statusu".replace(/^./, "R"))).toBeTruthy();
  });

  it("wymagania w prawej kolumnie jako zwykła lista, bez pól do zaznaczania", () => {
    render(<OfferPage data={OPEN} board={BOARD} base="" />);
    const list = screen.getByRole("complementary", { name: "Wymagania" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(within(list).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(list).getByText("Mile widziane")).toBeTruthy();
    expect(within(list).getByText("Nie musisz mieć wszystkiego.")).toBeTruthy();
    expect(screen.queryByText("Co już masz?")).toBeNull();
  });

  it("bez tablicy (awaria API) strona działa: bez technologii, liczby ofert i podobnych ofert", () => {
    const { container } = render(<OfferPage data={OPEN} board={null} base="" />);
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    expect(screen.queryByRole("list", { name: "Technologie" })).toBeNull();
    expect(screen.getByRole("link", { name: "← Wszystkie oferty" })).toBeTruthy();
    // Mapa nadal pokazuje miasto oferty, tylko bez kolumn tablicy.
    expect(screen.getByRole("img", { name: /zaznaczonym miejscem pracy: Warszawa, Łódź, biuro 1 dzień w tygodniu/ })).toBeTruthy();
    expect(container.querySelector("aside ul b")).toBeNull();
  });

  it("zamknięta rekrutacja: tytuł z plakietką, podobne z tej samej kategorii i prośba o CV", () => {
    render(<OfferPage data={{ ...OPEN, status: "closed" }} board={BOARD} base="/kariera" />);
    expect(screen.getByRole("heading", { level: 1, name: "Kierownik Projektów IT" })).toBeTruthy();
    expect(screen.getByText("Rekrutacja zamknięta")).toBeTruthy();
    expect(screen.getByText(/Ta rekrutacja już nie przyjmuje zgłoszeń\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Wszystkie oferty (4)" }).getAttribute("href")).toBe("/kariera");
    const links = screen.getAllByRole("link", { name: /^Zobacz: / }).map((a) => a.getAttribute("href"));
    expect(links[0]).toBe("/kariera/r/pm-2");
    expect(links).not.toContain("/kariera/r/kierownik-ab12");
    expect(screen.getByRole("link", { name: "Zostaw CV na następny projekt" }).getAttribute("href")).toBe("/kariera#zostaw-cv");
    expect(screen.queryByRole("button", { name: "Wyślij zgłoszenie" })).toBeNull();
  });
});

const DATA: CareerBoardResponse = { jobs: BOARD, cv: { slug: "olga-r", first_name: "Olga" } };

describe("lista rekrutacji (KarieraA)", () => {
  it("pierwszy ekran: hasło, liczba otwartych w leadzie, mapa miast z danych", () => {
    render(<CareerBoard data={DATA} base="" />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Dołącz do projektów, które muszą działać.");
    expect(screen.getByText("4 otwarte rekrutacje IT")).toBeTruthy();
    expect(screen.getByText(/w dwóch miastach\./)).toBeTruthy();
    // Mapa na desktop i telefon (CSS pokazuje jedną) — liczby z tablicy, nie z makiety.
    expect(screen.getAllByRole("img", { name: /^Szklana mapa Polski/ })).toHaveLength(1);
    const maps = [...document.querySelectorAll("svg[role='img']")];
    expect(maps).toHaveLength(2);
    expect(maps[0].getAttribute("aria-label")).toBe("Szklana mapa Polski. Otwarte rekrutacje według miast: Warszawa 2, Kraków 1.");
    expect(screen.getByRole("button", { name: "Pokaż 4 oferty" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "4 oferty" })).toBeTruthy();
  });

  it("bez kategorii: chipy miast z liczbami filtrują listę; liczby liczą się po szukaniu", () => {
    render(<CareerBoard data={DATA} base="" />);
    expect(screen.queryByText("Development")).toBeNull();
    const waw = screen.getByRole("button", { name: /Warszawa\s*2/ });
    fireEvent.click(waw);
    expect(waw.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByRole("article")).toHaveLength(2);
    fireEvent.click(waw);
    fireEvent.change(screen.getByPlaceholderText("Java, Kafka, Gdańsk…"), { target: { value: "java" } });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Warszawa\s*0/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Kraków\s*1/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pokaż 1 ofertę" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Wszystkie" }));
    expect(screen.getByRole("button", { name: "Wszystkie" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("tryb pracy zawęża listę", () => {
    render(<CareerBoard data={DATA} base="" />);
    fireEvent.click(screen.getByRole("button", { name: "Zdalnie" }));
    expect(screen.getAllByRole("article").map((a) => a.querySelector("h3")?.textContent)).toEqual(["Tester"]);
  });

  it("hasło bez trafień: pusta kolumna na mapie, zdanie z hasłem, czyszczenie filtrów i podpowiedź słowa", () => {
    render(<CareerBoard data={DATA} base="" />);
    fireEvent.change(screen.getByPlaceholderText("Java, Kafka, Gdańsk…"), { target: { value: "COBOL Kraków" } });
    expect(screen.getByRole("button", { name: "Pokaż 0 ofert" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Mapa Polski z pustym miejscem na kolumnę: dziś nie ma projektu z COBOL Kraków." })).toBeTruthy();
    expect(screen.getByText("Nie mamy teraz projektu dla „COBOL Kraków”.")).toBeTruthy();
    expect(screen.getByText(/Dla „Kraków” jest teraz 1 rekrutacja/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść filtry" }));
    expect(screen.getAllByRole("article")).toHaveLength(4);
  });

  it("„Pokaż kolejne” dokłada paczkę 12", () => {
    const many = Array.from({ length: 30 }, (_, i) => card(`job-${i}`));
    render(<CareerBoard data={{ jobs: many, cv: null }} base="" />);
    expect(screen.getAllByRole("article")).toHaveLength(12);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż kolejne 12 z 18" }));
    expect(screen.getAllByRole("article")).toHaveLength(24);
    expect(screen.getByRole("button", { name: "Pokaż kolejne 6 z 6" })).toBeTruthy();
  });

  it("awaria API to komunikat, nigdy pusta lista", () => {
    render(<CareerBoard data={null} base="" />);
    expect(screen.getByRole("alert").textContent).toContain("Nie udało się wczytać otwartych rekrutacji");
    expect(screen.queryByText("Brak otwartych rekrutacji")).toBeNull();
  });

  it("„Zostaw CV” otwiera formularz z jedną, obowiązkową zgodą na przyszłe procesy", () => {
    const { container } = render(<CareerBoard data={DATA} base="" />);
    const section = container.querySelector<HTMLElement>("#zostaw-cv")!;
    expect(section.hidden).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Zostaw CV" }));
    expect(screen.getByRole("link", { name: "Nic dla Ciebie? Zostaw CV" }).getAttribute("href")).toBe("#zostaw-cv");
    expect(section.hidden).toBe(false);
    expect(section.querySelector('input[name="consent"]')).toBeTruthy();
    expect(section.querySelector('input[name="consent_future"]')).toBeNull();
    expect(section.textContent).toContain("przyszłych procesów rekrutacyjnych");
  });
});

describe("„CV jest u …” — dopełniacz imienia albo nic", () => {
  it.each([
    ["Marek", "Marka"], ["Paweł", "Pawła"], ["Michał", "Michała"], ["Tomasz", "Tomasza"], ["Dominik", "Dominika"],
    ["Marta", "Marty"], ["Paulina", "Pauliny"], ["Olga", "Olgi"], ["Agnieszka", "Agnieszki"], ["Ola", "Oli"],
    ["Kasia", "Kasi"], ["Ania", "Ani"], ["Gosia", "Gosi"], ["Basia", "Basi"], ["Maria", "Marii"], ["Julia", "Julii"],
    ["Zofia", "Zofii"], ["Maja", "Mai"], ["Malwina", "Malwiny"],
  ])("%s → %s", (name, gen) => {
    expect(atName(name)).toBe(gen);
  });

  it("imienia, którego nie umie odmienić, nie zgaduje", () => {
    expect(atName("Zoe")).toBeNull();
    expect(atName("")).toBeNull();
    expect(atName("Anna Maria")).toBeNull();
  });
});

/* Kontrast tokenów nowej strony (WCAG AA 4,5:1 dla zwykłego tekstu). */
function hex(css: string, token: string): string {
  const m = new RegExp(`--${token}:\\s*(#[0-9a-f]{6})`, "i").exec(css);
  if (!m) throw new Error(`brak tokenu ${token}`);
  return m[1];
}
function lum(h: string): number {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a: string, b: string): number {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe("kontrast kolorów strony kariery", () => {
  const css = readFileSync(join(__dirname, "..", "site.module.css"), "utf8");
  const pairs: [string, string][] = [
    ["white", "red-text"], // przyciski i drobny tekst na czerwieni
    ["red-text", "white"], // „Zobacz”, komunikaty błędów
    ["ink", "snow"],
    ["ink-mid", "white"], // linia miejsca na karcie
    ["ink-soft", "white"],
    ["ink", "lime"], // karta Management & delivery
    ["on-ink-soft", "ink"],
    ["warm-soft", "ink"], // stopka
    ["red-text", "red-wash"], // baner błędu
    ["placeholder", "white"],
    ["on-red-soft", "red"], // tekst drugiego planu na pierwszym ekranie (język A)
  ];
  it.each(pairs)("%s na %s ma co najmniej 4,5:1", (fg, bg) => {
    expect(ratio(hex(css, fg), hex(css, bg))).toBeGreaterThanOrEqual(4.5);
  });
});
