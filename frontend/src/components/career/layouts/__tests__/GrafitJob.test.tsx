import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GrafitJob } from "@/components/career/layouts/GrafitJob";
import type { CareerJobResponse } from "@/lib/career/api";

/** Publiczna odpowiedź `/api/public/career/r/<slug>` rekrutacji AMLR (28.10.2026). */
const AMLR: CareerJobResponse = {
  status: "open",
  recruiter: { first_name: "Marta", slug: null },
  theme: "grafit",
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

function renderJob(data: CareerJobResponse = AMLR) {
  return render(<GrafitJob data={data} base="/kariera" host="kariera.b2bnetwork.pl" />);
}

function withJob(patch: Partial<CareerJobResponse["job"]>): CareerJobResponse {
  return { ...AMLR, job: { ...AMLR.job, ...patch } };
}

describe("GrafitJob", () => {
  it("tytuł rekrutacji jest w h1", () => {
    renderJob();
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("PL_EU AMLR Package – KYC delivery lead");
  });

  it("pierwszy ekran ma trzy fakty: lokalizacja, tryb, umowa", () => {
    const { container } = renderJob();
    const terms = Array.from(container.querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(terms).toEqual(["Lokalizacja", "Tryb pracy", "Umowa"]);
    expect(screen.getByText("Gdańsk, Gdynia, Warszawa, Łódź")).toBeInTheDocument();
    expect(screen.getByText("Hybryda")).toBeInTheDocument();
    expect(screen.getByText("3 dni w biurze w tygodniu")).toBeInTheDocument();
    expect(screen.getByText("B2B")).toBeInTheDocument();
    const values = Array.from(container.querySelectorAll("dd")).map((dd) => dd.textContent);
    expect(values).toEqual(["Gdańsk, Gdynia, Warszawa, Łódź", "Hybryda · 3 dni w biurze w tygodniu", "B2B"]);
  });

  it("„Poziom” i „Start” są w tej samej liście faktów", () => {
    const { container } = renderJob(
      withJob({ params: { ...AMLR.job.params!, seniority: "senior", start: "od zaraz" } }),
    );
    expect(container.querySelectorAll("dl")).toHaveLength(1);
    const terms = Array.from(container.querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(terms).toEqual(["Lokalizacja", "Tryb pracy", "Umowa", "Poziom", "Start"]);
    expect(screen.getByText("Senior")).toBeInTheDocument();
    expect(screen.getByText("Od zaraz")).toBeInTheDocument();
  });

  it("sekcje mają nazwy: O projekcie, Wymagania, Proces rekrutacji, Aplikuj", () => {
    renderJob();
    expect(screen.getByRole("region", { name: "O projekcie" })).toBeInTheDocument();
    const req = screen.getByRole("region", { name: "Wymagania" });
    expect(within(req).getByRole("heading", { name: "Wymagane" })).toBeInTheDocument();
    expect(within(req).getByRole("heading", { name: "Mile widziane" })).toBeInTheDocument();
    const process = screen.getByRole("region", { name: "Proces rekrutacji" });
    const steps = within(process).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[0]).toHaveTextContent("Rozmowa z Martą");
    const apply = screen.getByRole("region", { name: "Aplikuj" });
    expect(apply).toHaveAttribute("id", "aplikuj");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("każde „Aplikuj” prowadzi do formularza #aplikuj", () => {
    const { container } = renderJob();
    const links = screen.getAllByRole("link", { name: /^Aplikuj/ });
    expect(links.length).toBeGreaterThanOrEqual(2);
    for (const link of links) expect(link).toHaveAttribute("href", "#aplikuj");
    const target = container.querySelector("#aplikuj");
    expect(target).not.toBeNull();
    expect(target).toHaveAttribute("tabindex", "-1");
    expect(within(target as HTMLElement).getByRole("form", { name: "Formularz aplikacji" })).toBeInTheDocument();
  });

  it("każde wymaganie występuje na stronie dokładnie raz, mile widziane osobno", () => {
    renderJob();
    for (const m of AMLR.job.must) expect(screen.getAllByText(m.name)).toHaveLength(1);
    const must = screen.getByRole("heading", { name: "Wymagane" }).closest("article") as HTMLElement;
    const nice = screen.getByRole("heading", { name: "Mile widziane" }).closest("article") as HTMLElement;
    expect(must).not.toBe(nice);
    expect(within(must).getAllByRole("listitem")).toHaveLength(3);
    for (const n of AMLR.job.nice) {
      expect(within(nice).getByText(n)).toBeInTheDocument();
      expect(within(must).queryByText(n)).toBeNull();
    }
  });

  it("„Czym się zajmiesz” to punkty, a kroki procesu stoją przy formularzu", () => {
    renderJob();
    const tile = screen.getByRole("heading", { name: "Czym się zajmiesz" }).closest("article") as HTMLElement;
    expect(within(tile).getAllByRole("listitem")).toHaveLength(7);
    expect(screen.getByText("Rozmowa z Martą")).toBeInTheDocument();
    expect(screen.getByText("Umowa B2B")).toBeInTheDocument();
  });

  it("show.must=false chowa wymagania", () => {
    renderJob(withJob({ show: { must: false, nice: true, params: true, process: true } }));
    expect(screen.queryByRole("heading", { name: "Wymagane" })).toBeNull();
    expect(screen.queryByText("Transaction Monitoring")).toBeNull();
    expect(screen.getByRole("heading", { name: "Mile widziane" })).toBeInTheDocument();
  });

  it("brak params nie zostawia pustych kafli faktów", () => {
    const { container } = renderJob(withJob({ params: null }));
    expect(container.querySelector("dl")).toBeNull();
    expect(screen.queryByText("Lokalizacja")).toBeNull();
    expect(screen.getAllByRole("link", { name: /^Aplikuj/ })[0]).toHaveAttribute("href", "#aplikuj");
  });

  it("bez opisu i wymagań nie rysuje pustych kafli treści", () => {
    const { container } = renderJob(withJob({ about: "", must: [], nice: [] }));
    expect(container.querySelectorAll("article")).toHaveLength(0);
    expect(screen.getByRole("form", { name: "Formularz aplikacji" })).toBeInTheDocument();
  });

  it("stopka ma dane prawne i klauzulę RODO, bez nazwiska rekrutera", () => {
    renderJob();
    expect(screen.getByRole("link", { name: "Klauzula informacyjna RODO" })).toHaveAttribute(
      "href",
      "/kariera/rodo",
    );
    expect(screen.getByText(/KRS: 0000387063/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Wszystkie rekrutacje" })).toHaveAttribute("href", "/kariera");
  });

  it("stały link rekrutera daje odesłanie „Nie ten projekt?”", () => {
    renderJob({ ...AMLR, recruiter: { first_name: "Marta", slug: "marta-k" } });
    expect(screen.getByRole("link", { name: /Nie ten projekt\?/ })).toHaveAttribute(
      "href",
      "/kariera/p/marta-k",
    );
  });
});
