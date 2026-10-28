import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JasnyJob } from "@/components/career/layouts/JasnyJob";
import type { CareerJobResponse } from "@/lib/career/api";

/** Odpowiedź `/api/public/career/r/pl-eu-amlr-package-kyc-delivery-lead-lyy3` (28.10.2026). */
const AMLR = {
  status: "open",
  recruiter: { first_name: "Urszula", slug: null },
  theme: "jasny",
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
} as unknown as CareerJobResponse;

function withJob(patch: Partial<CareerJobResponse["job"]>): CareerJobResponse {
  return { ...AMLR, job: { ...AMLR.job, ...patch } };
}

function renderJob(data: CareerJobResponse = AMLR) {
  return render(<JasnyJob data={data} base="/kariera" host="kariera.b2bnetwork.pl" />);
}

const MUST_SHOWN = ["KYC", "Transaction Monitoring", "Project/programme manager"];

describe("JasnyJob", () => {
  it("tytuł stoi w <h1>", () => {
    renderJob();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "PL_EU AMLR Package - KYC delivery lead",
    );
  });

  it("pokazuje trzy fakty jako <dl>: lokalizację, tryb pracy i umowę", () => {
    const { container } = renderJob();
    const dl = container.querySelector("dl");
    expect(dl).not.toBeNull();
    const pairs = Array.from(dl!.querySelectorAll("dt")).map((dt) => [
      dt.textContent,
      dt.nextElementSibling?.tagName === "DD" ? dt.nextElementSibling.textContent : null,
    ]);
    expect(pairs).toEqual([
      ["Lokalizacja", "Gdańsk, Gdynia, Warszawa, Łódź"],
      ["Tryb pracy", "Hybryda · 3 dni w biurze w tygodniu"],
      ["Umowa", "B2B"],
    ]);
  });

  it("sekcje mają wspólne nazwy: O projekcie, Wymagania, Proces rekrutacji, Aplikuj", () => {
    renderJob();
    expect(screen.getByRole("region", { name: "O projekcie" })).toBeInTheDocument();
    const req = within(screen.getByRole("region", { name: "Wymagania" }));
    expect(req.getByRole("heading", { name: "Wymagane" })).toBeInTheDocument();
    expect(req.getByRole("heading", { name: "Mile widziane" })).toBeInTheDocument();
    const steps = within(screen.getByRole("region", { name: "Proces rekrutacji" }));
    const items = within(steps.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("Rozmowa z Urszulą");
    const apply = screen.getByRole("region", { name: "Aplikuj" });
    expect(apply).toHaveAttribute("id", "aplikuj");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("każdy przycisk „Aplikuj” prowadzi do formularza #aplikuj", () => {
    const { container } = renderJob();
    const apply = screen.getAllByRole("link", { name: /^Aplikuj/ });
    expect(apply.length).toBeGreaterThanOrEqual(3);
    for (const link of apply) expect(link).toHaveAttribute("href", "#aplikuj");
    const target = container.querySelector("#aplikuj");
    expect(target).not.toBeNull();
    expect(target).toHaveAttribute("tabindex", "-1");
    expect(within(target as HTMLElement).getByRole("form", { name: "Formularz aplikacji" })).toBeInTheDocument();
  });

  it("każde wymaganie występuje na stronie dokładnie raz, „Mile widziane” osobno", () => {
    renderJob();
    for (const name of MUST_SHOWN) expect(screen.getAllByText(name)).toHaveLength(1);
    const must = within(screen.getByRole("list", { name: "Wymagane" }));
    expect(must.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Mile widziane" })).toBeInTheDocument();
    const nice = within(screen.getByRole("list", { name: "Mile widziane" }));
    expect(nice.getAllByRole("listitem")).toHaveLength(3);
    expect(must.queryByText("sole trader customer segment")).toBeNull();
  });

  it("kroki procesu stoją raz — karta „Prowadzi” ma tylko imię i zdanie", () => {
    renderJob();
    expect(screen.getAllByText("Rozmowa z Urszulą")).toHaveLength(1);
    const lead = within(screen.getByRole("complementary", { name: "Kto prowadzi rekrutację" }));
    expect(lead.getByText("Prowadzi: Urszula")).toBeInTheDocument();
    expect(lead.queryByRole("list")).toBeNull();
    expect(screen.getByText("Umowa B2B")).toBeInTheDocument();
  });

  it("show.must=false chowa wymagania, mile widziane zostają", () => {
    renderJob(withJob({ show: { must: false, nice: true, params: true, process: true } }));
    for (const name of MUST_SHOWN) expect(screen.queryByText(name)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Wymagane" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Mile widziane" })).toBeInTheDocument();
  });

  it("bez wymagań nie ma przycisku „Zobacz wymagania” ani pustej sekcji", () => {
    const { container } = renderJob(withJob({ must: [], nice: [] }));
    expect(screen.queryByRole("link", { name: "Zobacz wymagania" })).toBeNull();
    expect(container.querySelector("#wymagania")).toBeNull();
  });

  it("brak params nie zostawia pustych kafli faktów", () => {
    const { container } = renderJob(withJob({ params: null }));
    expect(container.querySelector("dl")).toBeNull();
    expect(screen.queryByText("Lokalizacja")).toBeNull();
    expect(screen.getByRole("form", { name: "Formularz aplikacji" })).toBeInTheDocument();
  });

  it("stopka ma dane prawne i link do klauzuli RODO", () => {
    renderJob();
    const footer = within(screen.getByRole("contentinfo"));
    expect(footer.getByText(/KRS: 0000387063/)).toBeInTheDocument();
    expect(footer.getByRole("link", { name: "Klauzula informacyjna RODO" })).toHaveAttribute(
      "href",
      "/kariera/rodo",
    );
  });

  it("ze stałym linkiem rekrutera formularz odsyła do jego strony", () => {
    renderJob({ ...AMLR, recruiter: { ...AMLR.recruiter, slug: "urszula-k" } });
    expect(screen.getByRole("link", { name: /Nie ten projekt\?/ })).toHaveAttribute(
      "href",
      expect.stringContaining("urszula-k"),
    );
  });
});
