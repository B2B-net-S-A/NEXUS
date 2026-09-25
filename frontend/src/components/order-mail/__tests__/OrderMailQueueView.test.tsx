/**
 * Kolejka zamówień z maila — warstwa prezentacyjna.
 *
 * Trzy reguły pod testem: awaria renderuje się jako awaria (nie pustka),
 * powody z bramki są treścią ekranu, a „Zastosuj" jest wyłączone dla roli bez
 * prawa zapisu (`can_apply=false`) — przycisk widoczny, nie klikalny, z tytułem
 * wyjaśniającym dlaczego.
 */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const openAuthenticatedFile = vi.hoisted(() => vi.fn());
vi.mock("@/lib/authenticated-files", () => ({ openAuthenticatedFile }));

import { OrderMailQueueView, selectOrderMailDocument } from "@/components/order-mail/OrderMailQueue";
import type { OrderMailDocument, OrderMailRecheckRun, OrderMailSyncStatus } from "@/lib/api/orderMail";

function doc(over: Partial<OrderMailDocument> = {}): OrderMailDocument {
  return {
    id: 1, received_at: "2031-03-03T08:00:00Z", sender_email: "x@bank.example", subject: "Zamówienie",
    attachment_name: "z.pdf", outcome: "needs_review", client_id: 1, client_name: "Bank A",
    identification_method: "registry_id", identification_reason: null, client_policy: "PKO BP",
    gate_verdict: "review", gate_reasons: ["„Jan Kowalski”: Dopasowanie z literówką — potwierdź osobę"],
    document_meta: null,
    extraction: { title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Jan Kowalski", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, uncertain: false, uncertain_reason: null }] },
    proposal: { client_id: 1, order_number: "7/2031", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Jan Kowalski", action: "new", candidate_id: 1, contract_id: 2, target_order_id: null, title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30", rate_client: null, rate_unit: "day", md_total: null, reasons: [] }] },
    applied_order_id: null, applied_at: null, reviewed_at: null, error: null, can_apply: true, has_file: true,
    ...over,
  };
}

function syncStatus(over: Partial<OrderMailSyncStatus> = {}): OrderMailSyncStatus {
  return {
    enabled: true, interval_minutes: 60, autoapply_enabled: false, running: false, started_at: "2031-03-03T08:00:00Z",
    interrupted: false, can_trigger: true,
    last_completed: {
      reason: "manual", started_at: "2031-03-03T08:00:00Z", finished_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      status: "ok", error: null, messages: 3, new_messages: 2, attachments: 2, auto_applied: 1, needs_review: 1,
      unrecognized: 0, duplicates: 0, skipped_existing: 1, ignored_no_pdf: 0, ignored_sender: 0, failed: 0,
      rechecked: 0, recheck_applied: 0, recheck_held: 0, recheck_alerts: 0, errors: [],
    },
    ...over,
  };
}

const mailbox = { status: syncStatus(), statusError: false, checking: false, checkError: null, onCheckNow: vi.fn() };

const noRecheck = { runs: [], state: "ready" as const, scoped: false, onRetry: vi.fn() };

function recheckRun(over: Partial<OrderMailRecheckRun> = {}): OrderMailRecheckRun {
  return {
    id: 5, started_at: "2031-03-03T08:02:00Z", finished_at: "2031-03-03T08:02:30Z",
    trigger: "scheduled", checked: 2, applied: 1, held: 1,
    entries: [
      { document_id: 11, client_id: 1, client_name: "Bank A", order_number: "7/2031", people: ["Jan Kowalski"],
        outcome: "applied", category: null, reasons: [] },
      { document_id: 12, client_id: 1, client_name: "Bank A", order_number: "8/2031", people: ["Anna Nowa"],
        outcome: "held", category: "awaiting_contract", reasons: ["jest już w bazie, ale bez trwającej współpracy"] },
    ],
    ...over,
  };
}

const base = {
  mailbox,
  outcome: "needs_review" as const, onOutcomeChange: vi.fn(), total: 1, selectedId: 1,
  onSelect: vi.fn(), onApply: vi.fn(), onDismiss: vi.fn(), onRetry: vi.fn(), busy: false, applyError: null,
  recheck: noRecheck,
};

describe("OrderMailQueueView", () => {
  it("refreshes the existing plan only with write rights and a saved PDF", () => {
    const onRefreshPlan = vi.fn();
    const { rerender } = render(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} state="ready" items={[doc({ can_apply: true, has_file: true })]} />);
    fireEvent.click(screen.getByRole("button", { name: "Przelicz plan" }));
    expect(onRefreshPlan).toHaveBeenCalledWith(1);
    rerender(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} busy state="ready" items={[doc({ can_apply: true, has_file: true })]} />);
    expect(screen.getByRole("button", { name: "Przelicz plan" })).toBeDisabled();
    rerender(<OrderMailQueueView {...base} onRefreshPlan={onRefreshPlan} state="ready" items={[doc({ can_apply: false, has_file: true })]} />);
    expect(screen.queryByRole("button", { name: "Przelicz plan" })).toBeNull();
  });

  it("renders gate reasons and redacted money as dashes", () => {
    render(<OrderMailQueueView {...base} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("gate-reasons")).toHaveTextContent("Dopasowanie z literówką");
    expect(screen.getByTestId("order-mail-detail")).toHaveTextContent("—");
    expect(screen.getByText("Nowe zamówienie")).toBeInTheDocument();
  });

  it("pokazuje daty DD.MM.RRRR i powód bez reprezentacji wyjątku (UAT A-B06, M07-B06)", () => {
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[
          doc({
            gate_reasons: ["Nie udało się zapisać zamówienia: ValueError('W bazie jest już osoba — zastosuj ręcznie')"],
            error: "ValueError(\"Kilka osób o tym imieniu\")",
          }),
        ]}
      />,
    );
    const detail = screen.getByTestId("order-mail-detail");
    expect(detail).toHaveTextContent("01.04.2031 – 30.06.2031");
    expect(detail).not.toHaveTextContent("2031-04-01");
    expect(screen.getByTestId("gate-reasons")).toHaveTextContent(
      "Nie udało się zapisać zamówienia: W bazie jest już osoba — zastosuj ręcznie",
    );
    expect(detail).toHaveTextContent("Błąd: Kilka osób o tym imieniu");
    expect(detail).not.toHaveTextContent("ValueError");
    expect(screen.getByTestId("order-mail-list")).toHaveTextContent("03.03.2031");
  });

  it("proposes the person already in the base instead of a new contractor", () => {
    // Zgłoszenie PKO BP: dokument trafił na zdublowany rekord klienta, więc
    // osoba wyszła jako „nowy kontraktor". Kolejka ma najpierw powiedzieć,
    // KOGO znaleziono — etykieta akcji schodzi pod podpowiedź.
    const reason =
      "„Piotr Michałowski” (#11) ma kontrakt #456 u klienta „Powszechna Kasa Oszczędności Bank Polski S.A”.";
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[
          doc({
            proposal: {
              client_id: 1,
              order_number: "1893/2031",
              is_group_client: false,
              blocking: [],
              rows: [
                {
                  row_index: 0, row_name: "Piotr Michałowski", action: "new_draft",
                  candidate_id: null, contract_id: null, target_order_id: null,
                  title: "1893/2031", start_date: "2031-10-01", end_date: "2031-12-31",
                  rate_client: null, rate_unit: "day", md_total: null,
                  reasons: [reason], existing_person_ids: [11],
                },
              ],
            },
          }),
        ]}
      />,
    );
    const hint = screen.getByTestId("person-already-in-base");
    expect(hint).toHaveTextContent("Osoba jest już w bazie — potwierdź tożsamość");
    expect(hint).toHaveTextContent("kontrakt #456");
    expect(hint).toHaveTextContent("Po potwierdzeniu: Nowy kontraktor — utworzy draft");
  });

  it("keeps the plain action label for a genuinely new person", () => {
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[
          doc({
            proposal: {
              client_id: 1, order_number: "7/2031", is_group_client: false, blocking: [],
              rows: [
                {
                  row_index: 0, row_name: "Zenon Nowy", action: "new_draft",
                  candidate_id: null, contract_id: null, target_order_id: null,
                  title: "7/2031", start_date: "2031-04-01", end_date: "2031-06-30",
                  rate_client: null, rate_unit: "day", md_total: null,
                  reasons: [], existing_person_ids: [],
                },
              ],
            },
          }),
        ]}
      />,
    );
    expect(screen.queryByTestId("person-already-in-base")).toBeNull();
    expect(screen.getByText("Nowy kontraktor — utworzy draft")).toBeInTheDocument();
  });

  it("apply is disabled without rights and calls back with rights", () => {
    const onApply = vi.fn();
    const { rerender } = render(<OrderMailQueueView {...base} onApply={onApply} state="ready" items={[doc({ can_apply: false })]} />);
    const btn = screen.getByRole("button", { name: /Zastosuj/ });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringContaining("Delivery Leada"));
    rerender(<OrderMailQueueView {...base} onApply={onApply} state="ready" items={[doc({ can_apply: true })]} />);
    fireEvent.click(screen.getByRole("button", { name: /Zastosuj/ }));
    expect(onApply).toHaveBeenCalledWith(1);
  });

  it("person to decide: the window link replaces a silent apply", () => {
    const decide = doc({
      proposal: {
        client_id: 7, order_number: "SAP 4500000777", is_group_client: true, blocking: [],
        rows: [{ row_index: 0, row_name: "Marian Odchodzący", action: "decide_person", candidate_id: 5, contract_id: 9, target_order_id: null, title: "SAP 4500000777", start_date: "2031-04-01", end_date: null, rate_client: null, rate_unit: "day", md_total: null, order_type: "cost",
          reasons: ["„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia"] }],
      },
      client_id: 7,
      id: 42,
    });
    render(<OrderMailQueueView {...base} selectedId={42} state="ready" items={[decide]} />);
    expect(screen.getByTestId("order-mail-detail")).toHaveTextContent("nie ma już aktywnej współpracy");
    expect(screen.getByTestId("person-decision")).toHaveTextContent("zostawić ją jako zapis historyczny");
    expect(screen.getByRole("link", { name: /Rozstrzygnij w oknie zamówienia/ })).toHaveAttribute(
      "href",
      "/clients/7?tab=zamowienia&orderMailDoc=42",
    );
    const apply = screen.getByRole("button", { name: /Zastosuj/ });
    expect(apply).toBeDisabled();
    expect(apply).toHaveAttribute("title", expect.stringContaining("w oknie zamówienia"));
  });

  it("mailbox panel shows the last check and the button asks for a new one", () => {
    const onCheckNow = vi.fn();
    render(<OrderMailQueueView {...base} mailbox={{ ...mailbox, onCheckNow }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("co 60 min");
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("5 min temu (ręcznie)");
    // UAT B75: liczby opisują OSTATNIE sprawdzenie, nie bieżące zaległości.
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent("W ostatnim sprawdzeniu:");
    expect(screen.getByTestId("mailbox-check-result")).not.toHaveTextContent("całej skrzynki");
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent(
      "2 nowe wiadomości · 1 zapisane automatycznie · 1 do weryfikacji",
    );
    fireEvent.click(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ }));
    expect(onCheckNow).toHaveBeenCalledTimes(1);
  });

  it("button is absent without rights and busy while the mailbox is being checked", () => {
    const { rerender } = render(
      <OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ can_trigger: false }) }} state="ready" items={[doc()]} />,
    );
    expect(screen.queryByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeNull();
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, checking: true }} state="ready" items={[doc()]} />);
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("Sprawdzam skrzynkę");
    // Bieg planowy trwający po stronie serwera blokuje przycisk tak samo jak własny klik.
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ running: true }) }} state="ready" items={[doc()]} />);
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
  });

  it("interrupted previous run, failed run and disabled ingest are said out loud", () => {
    const { rerender } = render(
      <OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ interrupted: true }) }} state="ready" items={[doc()]} />,
    );
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent("przerwane");
    rerender(
      <OrderMailQueueView
        {...base}
        mailbox={{ ...mailbox, status: syncStatus({ last_completed: { ...syncStatus().last_completed!, status: "error", error: "Graph 401" } }) }}
        state="ready"
        items={[doc()]}
      />,
    );
    expect(screen.getByTestId("mailbox-check-result")).toHaveTextContent("nie powiodło się: Graph 401");
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: syncStatus({ enabled: false }) }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("wyłączone");
    expect(screen.getByRole("button", { name: /Pobierz zamówienia z maila/ })).toBeDisabled();
    rerender(<OrderMailQueueView {...base} mailbox={{ ...mailbox, status: null, statusError: true }} state="ready" items={[doc()]} />);
    expect(screen.getByTestId("mailbox-check")).toHaveTextContent("Nie udało się pobrać stanu skrzynki");
  });

  it("error is an error, empty is empty, loading is loading", () => {
    const { rerender } = render(<OrderMailQueueView {...base} state="error" items={[]} total={0} />);
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    rerender(<OrderMailQueueView {...base} state="ready" items={[]} total={0} />);
    expect(screen.getByText("Nic do pokazania")).toBeInTheDocument();
    rerender(<OrderMailQueueView {...base} state="loading" items={[]} total={0} />);
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
  });

  it("403 is a lack of access, not a server failure with retry (UAT A-B04)", () => {
    render(<OrderMailQueueView {...base} state="forbidden" items={[]} total={0} />);
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Nie udało się pobrać danych")).toBeNull();
    expect(screen.queryByRole("button", { name: /Spróbuj ponownie/ })).toBeNull();
    expect(screen.queryByTestId("mailbox-check")).toBeNull();
  });

  it("PDF opens through the authenticated fetch, not a raw link to the frontend host (UAT M07-B03)", async () => {
    openAuthenticatedFile.mockReset();
    openAuthenticatedFile.mockRejectedValueOnce(new Error("HTTP 404"));
    render(<OrderMailQueueView {...base} state="ready" items={[doc({ id: 47, has_file: true })]} selectedId={47} />);
    expect(screen.queryByRole("link", { name: /PDF/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /PDF/ }));
    expect(openAuthenticatedFile).toHaveBeenCalledWith("/api/order-mail/queue/47/file", "application/pdf", "z.pdf");
    expect(await screen.findByText("Nie udało się otworzyć pliku PDF.")).toBeInTheDocument();
  });
});


describe("Historia automatycznej weryfikacji", () => {
  it("rozwija bieg do konkretnych dokumentów z powodem i linkiem", () => {
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ ...noRecheck, runs: [recheckRun()] }}
      />,
    );
    const history = screen.getByTestId("recheck-history");
    expect(history).toHaveTextContent("Sprawdzonych");
    expect(screen.queryByTestId("recheck-entries")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż (2)" }));
    const entries = screen.getByTestId("recheck-entries");
    expect(entries).toHaveTextContent("Zaakceptowane");
    expect(entries).toHaveTextContent("Wstrzymane");
    expect(entries).toHaveTextContent("Czeka na podpis umowy");
    expect(entries).toHaveTextContent("bez trwającej współpracy");
    expect(screen.getByRole("link", { name: "8/2031" })).toHaveAttribute("href", "/contracts?view=order-mail&doc=12");
  });

  it("awaria historii renderuje się jako awaria, nie jako brak biegów", () => {
    const onRetry = vi.fn();
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ runs: [], state: "error", scoped: false, onRetry }}
      />,
    );
    expect(screen.getByTestId("recheck-history")).not.toHaveTextContent("Brak zmian do pokazania");
    fireEvent.click(screen.getByRole("button", { name: /ponów|spróbuj/i }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("przeżywa awarię kolejki — ma własne zapytanie", () => {
    render(
      <OrderMailQueueView
        {...base}
        state="error"
        items={[]}
        recheck={{ ...noRecheck, runs: [recheckRun()] }}
      />,
    );
    // To właśnie historia mówi, czy system w ogóle próbuje dokończyć te wpisy —
    // schowanie jej razem z padniętą listą zabierałoby jedyny sygnał.
    expect(screen.getByTestId("recheck-history")).toHaveTextContent("Sprawdzonych");
  });

  it("pusty stan pojawia się dopiero po udanym odczycie", () => {
    const { rerender } = render(
      <OrderMailQueueView {...base} state="ready" items={[doc()]} recheck={{ ...noRecheck, state: "loading" }} />,
    );
    expect(screen.getByTestId("recheck-history")).not.toHaveTextContent("Brak zmian do pokazania");
    rerender(<OrderMailQueueView {...base} state="ready" items={[doc()]} recheck={noRecheck} />);
    expect(screen.getByTestId("recheck-history")).toHaveTextContent("Brak zmian do pokazania");
  });

  it("pusta historia ze znacznikiem znaczy „nic nie wymagało zmiany”, nie awarię", () => {
    // Wiersz powstaje tylko przy zmianie, więc bez tego zdania pusta tabela
    // czytałaby się jak zepsuty mechanizm.
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ ...noRecheck, lastCheckedAt: "2031-03-03T08:02:00Z", unchangedRuns: 7 }}
      />,
    );
    const marker = screen.getByTestId("recheck-last-checked");
    expect(marker).toHaveTextContent("Sprawdzone ostatnio");
    expect(marker).toHaveTextContent("bez zmian");
  });

  it("nie zmyśla znacznika, gdy serwer go nie przysłał", () => {
    render(<OrderMailQueueView {...base} state="ready" items={[doc()]} recheck={noRecheck} />);
    expect(screen.queryByTestId("recheck-last-checked")).toBeNull();
  });

  it("po biegu, który coś zmienił, znacznik nie mówi „bez zmian”", () => {
    render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ ...noRecheck, runs: [recheckRun()], lastCheckedAt: "2031-03-03T08:02:00Z", unchangedRuns: 0 }}
      />,
    );
    expect(screen.getByTestId("recheck-last-checked")).not.toHaveTextContent("bez zmian");
  });

  it("opisuje okno godzin przysłane przez serwer, a nie zaszyte w kodzie", () => {
    const { rerender } = render(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ ...noRecheck, window: { start_hour: 8, end_hour: 18, enabled: true } }}
      />,
    );
    expect(screen.getByTestId("recheck-history")).toHaveTextContent("08:00–18:00");
    // Wyrównane godziny = okno wyłączone, czyli bieg całą dobę.
    rerender(
      <OrderMailQueueView
        {...base}
        state="ready"
        items={[doc()]}
        recheck={{ ...noRecheck, window: { start_hour: 0, end_hour: 0, enabled: false } }}
      />,
    );
    expect(screen.getByTestId("recheck-history")).toHaveTextContent("całą dobę");
  });

  // FE-N03 (audyt 22.09): alert z `?doc=` nie może otworzyć INNEGO dokumentu.
  it("never substitutes the first listed document for a missing ?doc= target", () => {
    const other = doc({ id: 7, client_name: "Bank Inny" });
    render(<OrderMailQueueView {...base} state="ready" items={[other]} selectedId={42} pinnedState="missing" />);
    expect(screen.getByText(/Nie znaleziono dokumentu #42/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zastosuj/ })).toBeNull();
  });

  it("shows the document fetched by id when it is outside the current list", () => {
    const other = doc({ id: 7, client_name: "Bank Inny" });
    const pinned = doc({ id: 42, client_name: "Bank Wskazany", attachment_name: "wskazany.pdf" });
    render(<OrderMailQueueView {...base} state="ready" items={[other]} selectedId={42} pinnedDoc={pinned} pinnedState="ready" />);
    expect(screen.queryByText(/Nie znaleziono dokumentu/)).toBeNull();
    expect(selectOrderMailDocument([other], 42, pinned, "ready")?.id).toBe(42);
    expect(selectOrderMailDocument([other], null, pinned)?.id).toBe(7);
    expect(selectOrderMailDocument([other], 42, null, "missing")).toBeNull();
    // Wybór kliknięciem (bez przypięcia z adresu) — dalej pierwszy z listy.
    expect(selectOrderMailDocument([other], 42, null, null)?.id).toBe(7);
  });

  it("renders a loading line while the pinned document is fetched, even with an empty list", () => {
    render(<OrderMailQueueView {...base} state="ready" items={[]} total={0} selectedId={42} pinnedState="loading" />);
    expect(screen.getByTestId("order-mail-pinned-loading")).toBeInTheDocument();
    expect(screen.queryByText("Nic do pokazania")).toBeNull();
  });
});

describe("Audyt 24.09 — kolejka poczty zamówień", () => {
  it("rate is shown in the document currency, not always in PLN (S5)", () => {
    const base0 = doc();
    const eur = doc({
      extraction: { ...base0.extraction!, currency: "EUR" },
      proposal: {
        ...base0.proposal!,
        rows: [{ ...base0.proposal!.rows[0], rate_client: "110.00", rate_unit: "hour" }],
      },
    });
    render(<OrderMailQueueView {...base} state="ready" items={[eur]} />);
    const detail = screen.getByTestId("order-mail-detail");
    expect(detail).toHaveTextContent("110,00 EUR/h");
    expect(detail).not.toHaveTextContent("110,00 zł");
  });

  it("an unrecognized document can be dismissed when the server allows it (N2)", () => {
    const onDismiss = vi.fn();
    const unrecognized = doc({
      outcome: "unrecognized_client", client_id: null, client_name: null, can_apply: false, proposal: null,
    });
    const { rerender } = render(
      <OrderMailQueueView {...base} outcome="unrecognized_client" onDismiss={onDismiss} state="ready" items={[unrecognized]} />,
    );
    expect(screen.queryByRole("button", { name: /Odrzuć/ })).toBeNull();
    const dismissable = { ...unrecognized, can_dismiss: true } as OrderMailDocument;
    rerender(
      <OrderMailQueueView {...base} outcome="unrecognized_client" onDismiss={onDismiss} state="ready" items={[dismissable]} />,
    );
    expect(screen.queryByRole("button", { name: /Zastosuj/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Odrzuć/ }));
    expect(onDismiss).toHaveBeenCalledWith(1);
  });
});

describe("Audyt 25.09 — wpisy „Nieudane”", () => {
  it("zakładka „Nieudane” istnieje i przełącza kolejkę na stan failed", () => {
    const onOutcomeChange = vi.fn();
    render(<OrderMailQueueView {...base} onOutcomeChange={onOutcomeChange} state="ready" items={[]} total={0} />);
    fireEvent.click(screen.getByRole("tab", { name: /Nieudane/ }));
    expect(onOutcomeChange).toHaveBeenCalledWith("failed");
  });

  it("nieudany wpis mówi, ile automatycznych prób zostało", () => {
    const failed = doc({
      outcome: "failed", error: "OperationalError('connection reset')", can_apply: false,
      proposal: null, extraction: null, document_meta: { failed_retry: { attempts: 1 } },
    });
    const { rerender } = render(<OrderMailQueueView {...base} outcome="failed" state="ready" items={[failed]} />);
    expect(screen.getByTestId("failed-retry-note")).toHaveTextContent("próba 1 z 3");
    expect(screen.queryByRole("button", { name: /Zastosuj/ })).toBeNull();
    const exhausted = { ...failed, document_meta: { failed_retry: { attempts: 3 } } };
    rerender(<OrderMailQueueView {...base} outcome="failed" state="ready" items={[exhausted]} />);
    expect(screen.getByTestId("failed-retry-note")).toHaveTextContent("3 razy bez skutku");
  });
});
