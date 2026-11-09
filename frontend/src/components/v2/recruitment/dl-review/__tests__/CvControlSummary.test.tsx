import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CvControlSummary } from "@/components/v2/recruitment/dl-review/CvControlSummary";
import type { QcCheck } from "@/lib/api/cvQc";
import { cvControlSummary } from "@/lib/cv-qc";

const pass = (key: string, label: string): QcCheck => ({
  key,
  label,
  severity: "warning",
  status: "pass",
  summary: "OK",
  items: [],
});

const CHECKS: QcCheck[] = [
  pass("dates", "Każda rola ma daty"),
  pass("spelling", "Pisownia technologii"),
  { ...pass("must_bolded", "Must-have są pogrubione"), status: "skip" },
  {
    key: "critical_skills",
    label: "Umiejętności krytyczne są w CV i opisane w rolach",
    severity: "blocking",
    status: "manual",
    summary: "Odczyt CV nie ma opisów ról — sprawdź role ręcznie",
    items: [],
    roles: [
      { requirement: "Oracle DB", role: "CCC group", state: "described", manual: { by: "Zofia C.", at: "2026-11-07" } },
      { requirement: "Oracle DB", role: "Mebway", state: "not_in_original", manual: { by: "Zofia C.", at: "2026-11-07" } },
      { requirement: "ETL", role: "CCC group", state: "unverified" },
    ],
  },
];

describe("„Kontrola CV” w przeglądzie DL (R5, 07.11.2026)", () => {
  it("liczy, co sprawdził automat, co rekruter ręcznie i czego nie sprawdził nikt", () => {
    expect(cvControlSummary(CHECKS)).toEqual({
      autoOk: 2,
      manual: [{ requirement: "Oracle DB", roles: ["CCC group"], by: "Zofia C." }],
      unverified: ["ETL"],
      blocking: 0,
      gaps: [],
      dismissed: [],
      consentManual: false,
    });
  });

  it("QC-2: pominięta blokada nie liczy się jako zaliczona i ma swoją linię", () => {
    const checks: QcCheck[] = [
      pass("dates", "Każda rola ma daty"),
      {
        ...pass("no_unsupported", "CV nie twierdzi niczego spoza oryginału"),
        severity: "blocking",
        dismissed_items: [
          {
            requirement: "Kafka",
            dismissal: { id: 1, reason: "in_cv", reason_label: "Jest w CV", note: "jest w CV w roli A", by_name: "Anna Kowalska", at: "2026-11-07" },
          },
        ],
      },
    ];
    render(<CvControlSummary checks={checks} override={null} onOpenQc={() => undefined} />);
    expect(screen.getByText(/1 sprawdzenie automatu w porządku/)).toBeInTheDocument();
    expect(screen.getByText(/Pominięte jako nieprawdziwe: Kafka — Anna K\.: jest w CV w roli A/)).toBeInTheDocument();
    expect(screen.queryByText("Nic nie przepuszczono mimo uwag")).toBeNull();
  });

  it("S1: nagłówek łączy stan z serwera i jedno „Otwórz QC”", async () => {
    const onOpenQc = vi.fn();
    render(
      <CvControlSummary
        checks={[pass("dates", "Każda rola ma daty")]}
        state={{ kind: "checked", n: 0, items: [], text: "QC: sprawdzone", tone: "ok", who: null, hint: null }}
        override={null}
        onOpenQc={onOpenQc}
      />,
    );
    const box = screen.getByRole("region", { name: "Kontrola CV" });
    expect(within(box).getByRole("heading")).toHaveTextContent("Kontrola CV · sprawdzone");
    await userEvent.click(within(box).getByRole("button", { name: "Otwórz QC" }));
    expect(onOpenQc).toHaveBeenCalledTimes(1);
  });

  it("QC-3: zgoda RODO z pliku kandydata jest widoczna w „Kontroli CV”", () => {
    const checks: QcCheck[] = [
      { ...pass("client_rules", "Reguły klienta"), severity: "blocking", status: "manual" },
    ];
    render(<CvControlSummary checks={checks} override={null} onOpenQc={() => undefined} />);
    expect(screen.getByText("Zgoda RODO z pliku kandydata — obejrzyj ręcznie")).toBeInTheDocument();
  });

  it("pokazuje trzy linie i „Otwórz QC” przy niesprawdzonym", async () => {
    const onOpenQc = vi.fn();
    render(<CvControlSummary checks={CHECKS} override={null} onOpenQc={onOpenQc} />);
    const box = screen.getByRole("region", { name: "Kontrola CV" });
    expect(box).toHaveTextContent("2 sprawdzenia automatu w porządku");
    expect(box).toHaveTextContent("Oracle DB opisane w: CCC group — wskazał(a) Zofia C.");
    expect(box).toHaveTextContent("ETL — nikt nie sprawdził opisu w rolach");
    expect(box).toHaveTextContent("Nic nie przepuszczono mimo uwag");
    await userEvent.click(within(box).getByRole("button", { name: "Otwórz QC" }));
    expect(onOpenQc).toHaveBeenCalled();
  });

  it("przepuszczone mimo uwag mówi kto i dlaczego", () => {
    render(
      <CvControlSummary
        checks={[pass("dates", "Każda rola ma daty")]}
        override={{ by_name: "Julia S.", reason: "Klient zna go z projektu", at: "2026-11-05T10:00:00Z" }}
        onOpenQc={() => undefined}
      />,
    );
    expect(screen.getByRole("region", { name: "Kontrola CV" })).toHaveTextContent(
      "Przepuszczone mimo uwag — Julia S.: Klient zna go z projektu",
    );
  });

  it("luka kandydata (R2) stoi jako decyzja Delivery Leada", () => {
    const checks: QcCheck[] = [
      {
        key: "critical_skills",
        label: "Umiejętności krytyczne są w CV i opisane w rolach",
        severity: "blocking",
        status: "pass",
        summary: "Luka kandydata: FastAPI",
        items: [],
        info: [{ requirement: "FastAPI", fix: "ask_candidate", candidate_gap: true }],
      },
    ];
    expect(cvControlSummary(checks).gaps).toEqual(["FastAPI"]);
    render(<CvControlSummary checks={checks} override={null} onOpenQc={() => undefined} />);
    expect(screen.getByRole("region", { name: "Kontrola CV" })).toHaveTextContent(
      "FastAPI — kandydat tego nie ma, decyzja o wysyłce należy do Ciebie",
    );
  });

  it("bez wyniku QC mówi, że jeszcze liczy", () => {
    render(<CvControlSummary checks={undefined} override={null} onOpenQc={() => undefined} />);
    expect(screen.getByRole("region", { name: "Kontrola CV" })).toHaveTextContent("Sprawdzam QC…");
  });
});
