import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CareerJobResponse } from "@/lib/career/api";

import { TerminalJob } from "../TerminalJob";

/** Publiczna odpowiedź `/api/public/career/r/<slug>` rekrutacji AMLR (28.10.2026). */
const AMLR: CareerJobResponse = {
  status: "open",
  recruiter: { first_name: "Urszula", slug: null },
  theme: "terminal",
  published_at: "2026-10-28",
  canonical_slug: "pl-eu-amlr-package-kyc-delivery-lead-lyy3",
  job: {
    slug: "pl-eu-amlr-package-kyc-delivery-lead-lyy3",
    title: "PL_EU AMLR Package - KYC delivery lead",
    subtitle:
      "Szukamy KYC Delivery Lead do poprowadzenia wdrożenia zmian w ramach unijnego pakietu regulacyjnego AML",
    about:
      "Projekt dotyczy wdrożenia nowego unijnego pakietu regulacyjnego AML. Celem jest zaplanowanie i realizacja zmian w obszarach KYC i/lub Transaction Monitoring oraz zapewnienie gotowości operacyjnej i zgodności z regulacją.\n\nCzym się zajmiesz: Prowadzenie kompleksowego planowania i realizacji strumieni prac KYC i/lub Transaction Monitoring; Definiowanie zakresu, dostaw i kryteriów zakończenia prac; Przygotowanie jednostek operacyjnych do wdrożenia zmian; Zarządzanie zależnościami, ryzykami i problemami w ramach projektu; Raportowanie postępów oraz eskalowanie kwestii do kadry zarządzającej; Angażowanie i zarządzanie interesariuszami na różnych szczeblach organizacji; Prowadzenie dużych, złożonych projektów obejmujących wiele geografii i obszarów biznesowych.",
    must: [
      { name: "KYC", note: null },
      { name: "Transaction Monitoring", note: null },
      { name: "project/programme manager", note: null },
    ],
    nice: [
      "risk-based event driven review framework",
      "sole trader customer segment",
      "end-to-end customer monitoring processes and solutions",
    ],
    params: {
      city: "Gdańsk, Gdynia, Warszawa, Łódź",
      remote_policy: "hybrid",
      onsite_days_per_week: 3,
      onsite_days_per_month: null,
      seniority: null,
      contract: "B2B",
      start: null,
      duration: null,
    },
    show: { must: true, nice: true, params: true, process: true },
  },
} as CareerJobResponse;

const MUST = AMLR.job.must.map((m) => m.name);
const NICE = AMLR.job.nice;

function renderJob(data: CareerJobResponse = AMLR) {
  return render(<TerminalJob data={data} base="/kariera" host="localhost:3000" />);
}

function withJob(patch: Partial<CareerJobResponse["job"]>): CareerJobResponse {
  return { ...AMLR, job: { ...AMLR.job, ...patch } };
}

describe("TerminalJob", () => {
  it("shows the title in h1 and three facts on the first screen", () => {
    renderJob();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(AMLR.job.title);
    expect(screen.getByText("Gdańsk, Gdynia, Warszawa, Łódź")).toBeTruthy();
    expect(screen.getByText("Hybryda · 3 dni w biurze w tygodniu")).toBeTruthy();
    expect(screen.getByText("B2B", { selector: "dd" })).toBeTruthy();
    expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual([
      "Lokalizacja",
      "Tryb pracy",
      "Umowa",
    ]);
  });

  it("points every Aplikuj link at the form container", () => {
    const { container } = renderJob();
    const apply = screen.getAllByRole("link", { name: /^Aplikuj/ });
    expect(apply.length).toBeGreaterThanOrEqual(2);
    for (const link of apply) expect(link.getAttribute("href")).toBe("#aplikuj");
    const target = container.querySelector("#aplikuj");
    expect(target?.getAttribute("tabindex")).toBe("-1");
    expect(within(target as HTMLElement).getByRole("form", { name: "Formularz aplikacji" })).toBeTruthy();
  });

  it("lists each requirement exactly once, with nice-to-haves in their own group", () => {
    renderJob();
    for (const name of [...MUST, ...NICE]) expect(screen.getAllByText(name)).toHaveLength(1);
    const niceGroup = screen.getByRole("heading", { name: "Mile widziane" }).parentElement as HTMLElement;
    for (const name of NICE) expect(within(niceGroup).getByText(name)).toBeTruthy();
    for (const name of MUST) expect(within(niceGroup).queryByText(name)).toBeNull();
  });

  it("asks to tick instead of showing 0 of N, and counts after the first tick", () => {
    renderJob();
    expect(screen.getByText("Zaznacz, co już znasz.")).toBeTruthy();
    expect(screen.queryByText(/z 6/)).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "KYC" }));
    expect(screen.getByRole("checkbox", { name: "KYC" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("z 6", { exact: false })).toBeTruthy();
  });

  it("collapses a long list to six items with a show-all button", () => {
    const must = Array.from({ length: 20 }, (_, i) => ({ name: `Skill ${i + 1}`, note: null }));
    const { container } = renderJob(withJob({ must, nice: ["Selenium", "Playwright", "AI", "GitHub Copilot"] }));
    const card = container.querySelector("#wymagania") as HTMLElement;
    expect(within(card).getAllByRole("checkbox")).toHaveLength(6);
    expect(within(card).queryByRole("heading", { name: "Mile widziane" })).toBeNull();
    // Schowane pozycje zostają w treści strony (jedno miejsce z wymaganiami).
    expect(screen.getAllByText("Skill 20")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie (24)" }));
    expect(within(card).getAllByRole("checkbox")).toHaveLength(24);
  });

  it("hides requirements when show.must is false", () => {
    renderJob(withJob({ show: { must: false, nice: true, params: true, process: true } }));
    for (const name of MUST) expect(screen.queryByText(name)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Wymagane" })).toBeNull();
    expect(screen.getByText(NICE[0])).toBeTruthy();
  });

  it("leaves no empty fact tiles without params", () => {
    const { container } = renderJob(withJob({ params: null }));
    expect(container.querySelector("dl")).toBeNull();
    expect(screen.queryByText("Lokalizacja")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
  });

  it("drops the requirement card and its shortcut when there is nothing to show", () => {
    const { container } = renderJob(withJob({ must: [], nice: [] }));
    expect(container.querySelector("#wymagania")).toBeNull();
    expect(screen.queryByRole("link", { name: /Zobacz wymagania/ })).toBeNull();
  });

  it("uses the shared section structure of the three layouts", () => {
    renderJob();
    for (const name of ["O projekcie", "Wymagania", "Proces rekrutacji", "Aplikuj"]) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
    expect(screen.getByRole("region", { name: "Aplikuj" }).id).toBe("aplikuj");
    const steps = within(screen.getByRole("region", { name: "Proces rekrutacji" })).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[0].textContent).toContain("Rozmowa z Urszulą");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("has the legal footer with the RODO clause", () => {
    renderJob();
    expect(screen.getByRole("link", { name: "Klauzula informacyjna RODO" }).getAttribute("href")).toBe(
      "/kariera/rodo",
    );
    expect(screen.getByText(/KRS: 0000387063/)).toBeTruthy();
  });
});
