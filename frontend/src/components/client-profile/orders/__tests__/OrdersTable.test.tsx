/**
 * Tabela zamówień (wersja B, 29.09.2026) — to, czego pilnowały testy dawnej
 * karty `OrderGroupCard` (podział obsady, sekcja „Zakończone", nazwisko jako
 * link do kontraktu z wiersza, paski MD), przeniesione na wiersze tabeli.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OrdersTable } from "@/components/client-profile/orders/OrdersTable";
import { buildSectionRows } from "@/components/client-profile/orders/orders-table-model";
import type { OrderGroupRead } from "@/lib/api/orderGroups";
import { consultantMatchesQuery, effectiveGroupOrderType } from "@/lib/client-order-list";
import {
  makeOffboardingCase as offboardingCase,
  makeOrderGroup as group,
  makeOrderLine as line,
} from "@/components/client-profile/orders/__tests__/fixtures/order-groups";

function renderTable(
  groups: OrderGroupRead[],
  options: { canDecide?: boolean; canManage?: boolean; searchQuery?: string } = {},
) {
  const onSelect = vi.fn();
  // Ta sama plątanina rozwinięć co w `MultiConsultantOrdersTab`.
  function Harness() {
    const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
    const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set());
    const query = options.searchQuery ?? "";
    const rows = buildSectionRows(
      groups.map((item) => ({ kind: "group" as const, group: item })),
      {
        expandedEnded: expanded,
        collapsedEnded: collapsed,
        matchesSearch: query ? (name) => consultantMatchesQuery(name, query) : undefined,
      },
    );
    return (
      <OrdersTable
        sections={[
          { type: effectiveGroupOrderType(groups[0]), itemCount: groups.length, rows },
        ]}
        selectedKey={null}
        onSelect={onSelect}
        onToggleEnded={(groupId, open) => {
          setExpanded((prev) => {
            const next = new Set(prev);
            if (open) next.add(groupId);
            else next.delete(groupId);
            return next;
          });
          setCollapsed((prev) => {
            const next = new Set(prev);
            if (open) next.delete(groupId);
            else next.add(groupId);
            return next;
          });
        }}
        searchQuery={query}
        canDecide={options.canDecide ?? true}
        canManage={options.canManage ?? true}
        canViewFinance
      />
    );
  }
  const view = render(<Harness />);
  return { ...view, onSelect };
}

const rowOf = (lineId: number) => document.getElementById(`order-line-${lineId}`);

describe("OrdersTable — podział obsady", () => {
  it("zakończony konsultant z nierozstrzygniętą sprawą jest w „Zakończone”, nie w obsadzie", () => {
    // Do 09.2026 sprawa `pending` przypinała wiersz do aktywnej obsady, żeby
    // decyzja DL nie zginęła — sekcja odpowiadała na dwa pytania naraz.
    renderTable([
      group({
        lines: [
          line(),
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            status: "completed",
            is_active: false,
            end_date: "2026-08-31",
            cooperation_ended_on: "2026-08-31",
            md_used: 25,
            offboarding_case: offboardingCase(),
          }),
        ],
      }),
    ]);

    expect(rowOf(1)).toHaveAttribute("data-order-row", "line");
    expect(rowOf(2)).toHaveAttribute("data-order-row", "ended-line");
    const toggleRow = screen.getByRole("button", { name: /^Zakończone/ }).closest("tr")!;
    expect(rowOf(1)!.compareDocumentPosition(toggleRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggleRow.compareDocumentPosition(rowOf(2)!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("nagłówek „Zakończone” liczy sprawy czekające na decyzję, a decyzje są na górze", () => {
    // Przeniesienie wiersza nie może ukryć decyzji: licznik jest jedynym
    // sygnałem, że w tej sekcji zostało coś do zrobienia.
    renderTable([
      group({
        lines: [
          line(),
          line({
            id: 3,
            consultant_name: "Piotr Historia",
            status: "completed",
            is_active: false,
            cooperation_ended_on: "2026-07-31",
            history_kept_at: "2026-08-01T09:00:00Z",
          }),
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            status: "completed",
            is_active: false,
            cooperation_ended_on: "2026-08-31",
            offboarding_case: offboardingCase(),
          }),
        ],
      }),
    ]);

    const toggle = screen.getByRole("button", {
      name: /^Zakończone \(2\)\s*· 1 wymaga decyzji$/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const ended = Array.from(document.querySelectorAll('[data-order-row="ended-line"]'));
    expect(ended).toHaveLength(2);
    expect(ended[0]).toHaveTextContent("Anna Zejście");
    expect(ended[0]).toHaveTextContent("Podejmij decyzję");
    expect(ended[0]).toHaveClass("bg-destructive/5");
    expect(ended[1]).toHaveTextContent("Zostawiony jako historia");
    expect(ended[1]).not.toHaveTextContent("Podejmij decyzję");
    expect(ended[1]).not.toHaveClass("bg-destructive/5");
  });

  it("bez spraw do rozstrzygnięcia sekcja jest zwinięta i rozwija się na klik", async () => {
    const user = userEvent.setup();
    renderTable([
      group({
        lines: [
          line(),
          line({
            id: 2,
            consultant_name: "Piotr Historia",
            status: "completed",
            is_active: false,
            cooperation_ended_on: "2026-07-31",
            history_kept_at: "2026-08-01T09:00:00Z",
          }),
        ],
      }),
    ]);

    const toggle = screen.getByRole("button", { name: "Zakończone (1)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Piotr Historia")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Piotr Historia")).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByText("Piotr Historia")).not.toBeInTheDocument();
  });

  it("sekcja z decyzją da się zwinąć ręcznie mimo decyzji", async () => {
    const user = userEvent.setup();
    renderTable([
      group({
        lines: [
          line(),
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            status: "completed",
            is_active: false,
            cooperation_ended_on: "2026-08-31",
          }),
        ],
      }),
    ]);
    await user.click(screen.getByRole("button", { name: /^Zakończone \(1\)/ }));
    expect(screen.queryByText("Anna Zejście")).not.toBeInTheDocument();
  });

  it("następca, który kogoś zastąpił, zostaje w aktywnej obsadzie", async () => {
    // Kryterium zgłoszenia: przenosimy zakończonych, nie zastępców.
    const user = userEvent.setup();
    renderTable([
      group({
        lines: [
          line({
            id: 3,
            consultant_name: "Nowy Zastępca",
            predecessor_order_id: 2,
            predecessor_consultant_name: "Anna Zejście",
          }),
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            status: "completed",
            is_active: false,
            cooperation_ended_on: "2026-08-31",
            replaced_by_order_id: 3,
            replaced_by_consultant_name: "Nowy Zastępca",
          }),
        ],
      }),
    ]);

    expect(rowOf(3)).toHaveAttribute("data-order-row", "line");
    expect(rowOf(3)).toHaveTextContent("zastąpił: Anna Zejście");
    await user.click(screen.getByRole("button", { name: "Zakończone (1)" }));
    expect(rowOf(2)).toHaveAttribute("data-order-row", "ended-line");
    // Decyzja już zapadła — opis zamiast pytania.
    expect(rowOf(2)).toHaveTextContent("Zastąpiony przez Nowy Zastępca");
    expect(rowOf(2)).not.toHaveTextContent("Podejmij decyzję");
  });

  it("zakończeni schodzą z aktywnej obsady, najnowsze zejście na górze", () => {
    // Osoba po zejściu ma DALEJ `status: "active"` — linia MD kończy się
    // budżetem, nie kalendarzem. O sekcji decyduje `is_active` z serwera.
    const departed = (overrides: Parameters<typeof line>[0]) =>
      line({ status: "active", is_active: false, md_used: 30, ...overrides });
    renderTable([
      group({
        lines: [
          line({ id: 1, consultant_name: "Aktywna Osoba" }),
          departed({
            id: 2,
            consultant_name: "Anna Wczesna",
            end_date: "2026-06-30",
            cooperation_ended_on: "2026-06-30",
          }),
          departed({
            id: 3,
            consultant_name: "Zenon Ostatni",
            end_date: "2026-08-31",
            cooperation_ended_on: "2026-08-31",
          }),
        ],
      }),
    ]);

    expect(rowOf(1)).toHaveAttribute("data-order-row", "line");
    const ended = Array.from(document.querySelectorAll('[data-order-row="ended-line"]'));
    // Alfabetycznie byłoby odwrotnie — sekcja sortuje się datą zejścia.
    expect(ended.map((item) => item.id)).toEqual(["order-line-3", "order-line-2"]);
  });
});

describe("OrdersTable — wiersz osoby zakończonej", () => {
  it("wiersz: kto, plakietka, okres, wykorzystanie i decyzja — reszta w panelu", () => {
    renderTable([
      group({
        active_consultants: 0,
        lines: [
          line({
            id: 2,
            consultant_name: "Marian Odeszły",
            status: "active",
            is_active: false,
            start_date: "2026-05-01",
            end_date: "2026-08-31",
            cooperation_ended_on: "2026-08-31",
            md_used: 25.45,
            rate_revenue: 1000,
            origin: "manual",
            added_at: "2026-08-21T09:00:00Z",
            added_by_name: "Anna Przykładowa",
            contract_type: "b2b",
          }),
        ],
      }),
    ]);

    const row = rowOf(2)!;
    expect(row).toHaveTextContent("Zakończył projekt");
    expect(row).toHaveTextContent("01.05.2026 – 31.08.2026");
    expect(row).toHaveTextContent(/25,45 MD · 25\s450,00\szł/);
    expect(within(row).getByText("Podejmij decyzję")).toBeInTheDocument();
    // Bez „Dodany ręcznie", autora, zdania o puli i paska — to jest w panelu.
    expect(row).not.toHaveTextContent(/Dodany ręcznie/i);
    expect(row).not.toHaveTextContent("Anna Przykładowa");
    expect(row).not.toHaveTextContent(/nie wraca/);
    expect(row.querySelector('[role="progressbar"]')).toBeNull();
  });

  it("umowa rozwiązana: plakietka „Zakończył współpracę” i opis decyzji zamiast pytania", async () => {
    const user = userEvent.setup();
    renderTable([
      group({
        lines: [
          line({
            id: 2,
            consultant_name: "Marian Odeszły",
            is_active: false,
            cooperation_ended_on: "2026-08-31",
            history_kept_at: "2026-09-01T09:00:00Z",
            contract_type: "b2b",
            agreement_termination_mode: "mutual_agreement",
            agreement_last_day: "2026-08-31",
          }),
        ],
      }),
    ]);

    await user.click(screen.getByRole("button", { name: "Zakończone (1)" }));
    const row = rowOf(2)!;
    expect(row).toHaveTextContent("Zakończył współpracę");
    expect(row).toHaveTextContent("Zostawiony jako historia");
    expect(row).not.toHaveClass("bg-destructive/5");
    expect(within(row).queryByText("Podejmij decyzję")).toBeNull();
  });

  it("rola bez decyzji o puli widzi, na kogo czeka sprawa", () => {
    renderTable(
      [
        group({
          lines: [
            line({
              id: 2,
              consultant_name: "Anna Zejście",
              is_active: false,
              cooperation_ended_on: "2026-08-31",
              offboarding_case: offboardingCase(),
            }),
          ],
        }),
      ],
      { canDecide: true, canManage: false },
    );
    expect(rowOf(2)).toHaveTextContent("Oczekuje na decyzję Delivery Leada");
    expect(within(rowOf(2)!).queryByText("Podejmij decyzję")).toBeNull();
  });

  it("żaden wiersz nie używa starych nazw zakończenia", () => {
    renderTable([
      group({
        lines: [
          line({
            id: 2,
            consultant_name: "Anna Zejście",
            is_active: false,
            cooperation_ended_on: "2026-08-31",
            offboarding_case: offboardingCase(),
          }),
          line({ id: 3, consultant_name: "Piotr Domknięty", status: "completed", is_active: false }),
        ],
      }),
    ]);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/Zakończenie współpracy/);
    expect(text).not.toMatch(/Zakończony\b/);
  });
});

describe("OrdersTable — nazwisko prowadzi do kontraktu z tego wiersza", () => {
  it("dwie osoby na jednym zamówieniu dostają DWA różne kontrakty", () => {
    renderTable([
      group({
        lines: [
          line({ id: 1, contract_id: 600, consultant_name: "Wojciech Przykładowy" }),
          line({ id: 2, contract_id: 601, consultant_name: "Anna Wzorcowa" }),
        ],
        active_consultants: 2,
      }),
    ]);

    // Sedno ticketu: adres bierze się z LINII, nie z osoby ani z zamówienia —
    // ta sama osoba u innego klienta ma inny kontrakt.
    expect(screen.getByRole("link", { name: "Wojciech Przykładowy" })).toHaveAttribute(
      "href",
      "/contracts/600",
    );
    expect(screen.getByRole("link", { name: "Anna Wzorcowa" })).toHaveAttribute(
      "href",
      "/contracts/601",
    );
  });

  it("wiersz osoby zakończonej też jest linkiem", async () => {
    const user = userEvent.setup();
    renderTable([
      group({
        lines: [
          line({ id: 1, contract_id: 600, consultant_name: "Wojciech Przykładowy" }),
          line({
            id: 2,
            contract_id: 700,
            consultant_name: "Historyczny Konsultant",
            is_active: false,
            status: "completed",
            end_date: "2026-04-30",
          }),
        ],
      }),
    ]);

    await user.click(screen.getByRole("button", { name: "Zakończone (1)" }));
    expect(screen.getByRole("link", { name: "Historyczny Konsultant" })).toHaveAttribute(
      "href",
      "/contracts/700",
    );
  });

  it("nazwą dostępną linku jest NAZWISKO, nie numer kontraktu", () => {
    renderTable([
      group({ lines: [line({ id: 1, contract_id: 600, consultant_name: "Wojciech Przykładowy" })] }),
    ]);
    const link = screen.getByRole("link", { name: "Wojciech Przykładowy" });
    // `title` na kotwicy przejmuje nazwę w drzewie dostępności Chrome (jsdom
    // liczy inaczej) — dlatego pytamy wprost o atrybuty.
    expect(link).not.toHaveAttribute("title");
    expect(link).not.toHaveAttribute("aria-label");
  });

  it("klik w nazwisko nawiguje, klik w resztę wiersza otwiera panel", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderTable([
      group({ lines: [line({ id: 1, contract_id: 600, consultant_name: "Wojciech Przykładowy" })] }),
    ]);
    fireEvent.click(screen.getByRole("link", { name: "Wojciech Przykładowy" }));
    expect(onSelect).not.toHaveBeenCalled();
    await user.click(rowOf(1)!);
    expect(onSelect).toHaveBeenCalledWith("l:1");
  });

  it("poprzednik i następca NIE są linkami do kontraktu", () => {
    renderTable([
      group({
        lines: [
          line({
            id: 1,
            contract_id: 600,
            consultant_name: "Wojciech Przykładowy",
            predecessor_order_id: 41,
            predecessor_consultant_name: "Poprzedni Konsultant",
            replaced_by_order_id: 42,
            replaced_by_consultant_name: "Następny Konsultant",
          }),
        ],
      }),
    ]);
    // Te nazwiska niosą wyłącznie `*_order_id` — kontraktu nie da się z nich
    // wyprowadzić, więc link musiałby go zgadywać.
    expect(screen.queryByRole("link", { name: /Poprzedni Konsultant/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Następny Konsultant/ })).toBeNull();
  });
});

describe("OrdersTable — budżet i zużycie w wierszach", () => {
  const scoped = () =>
    group({
      client_id: 115,
      executive_contract: {
        id: 71,
        number: "UW/242/2031",
        status: "active",
        framework_contract_id: 12,
        project_part: "cz2",
      },
      md_positions_total: 360,
      md_used_total: 154,
      contract_value_pln: 2_295_200,
      used_value_pln: 711_480,
      lines: [
        line({
          id: 2,
          consultant_name: "Marcin Następca",
          md_total: 190,
          md_remaining: 206,
          md_used: 154,
          md_optional_total: 170,
          md_base_used: 154,
          md_optional_used: 0,
        }),
      ],
    });

  it("linia z zakresami dostaje paski podstawy i opcji, zamówienie — MD pozycji bez kwot", () => {
    renderTable([scoped()]);
    const row = rowOf(2)!;
    expect(row.querySelector('[aria-label="Podstawa — wykorzystano MD"]')).not.toBeNull();
    expect(row.querySelector('[aria-label="Opcja — wykorzystano MD"]')).not.toBeNull();
    const groupRow = document.getElementById("order-group-anchor-15")!;
    expect(groupRow).toHaveTextContent("Umowa wykonawcza UW/242/2031 · Cz. II");
    expect(groupRow).toHaveTextContent(/wykorzystano 154 \/ 360 MD/);
    // Kwoty umowy są w panelu, nie w wierszu tabeli.
    expect(groupRow).not.toHaveTextContent(/2\s295\s200/);
  });

  it("BIK/Polkomtel bez umowy wykonawczej zostaje przy pasku „pozostało / całość”", () => {
    renderTable([
      group({
        md_positions_total: 50,
        md_used_total: 50,
        contract_value_pln: 60_000,
        used_value_pln: 60_000,
        lines: [line({ md_used: 50, md_base_used: 50, md_optional_used: null })],
      }),
    ]);
    const row = rowOf(1)!;
    expect(within(row).getByRole("progressbar", { name: "Pozostałe MD" })).toBeInTheDocument();
    expect(within(row).queryByRole("progressbar", { name: /Podstawa/ })).toBeNull();
    expect(screen.queryByText(/Umowa wykonawcza/)).toBeNull();
    expect(screen.queryByText(/60\s000/)).toBeNull();
  });

  it("MD per osoba ma przycisk „Zużycie”, kosztowe i wspólna pula — nie", async () => {
    const user = userEvent.setup();
    const { onSelect, unmount } = renderTable([group()]);
    await user.click(screen.getByRole("button", { name: "Zużycie MD — Michał Przykładowy" }));
    expect(onSelect).toHaveBeenCalledWith("l:1", "zuzycie");
    unmount();

    renderTable([
      group({
        is_cost_based: true,
        budget_amount: 1000,
        budget_used: 0,
        budget_remaining: 1000,
        lines: [line({ md_total: null, md_remaining: null })],
      }),
    ]);
    expect(screen.queryByRole("button", { name: /Zużycie MD/ })).toBeNull();
    expect(rowOf(1)).toHaveTextContent("zafakturowano —");
  });

  it("anulowane zamówienie pokazuje datę anulowania w kalendarzu firmy", () => {
    renderTable([
      group({
        status: "cancelled",
        status_label: "Anulowane",
        // 23:30 UTC 28.09 to już 29.09 w Warszawie.
        cancelled_at: "2026-09-28T23:30:00Z",
      }),
    ]);
    expect(document.getElementById("order-group-anchor-15")).toHaveTextContent(
      "anulowane 29.09.2026",
    );
  });

  it("wyszukiwanie podświetla wiersz szukanej osoby i rozwija zakończonych", () => {
    renderTable(
      [
        group({
          lines: [
            line({ id: 1, consultant_name: "Anna Nowak" }),
            line({
              id: 2,
              consultant_name: "Zofia Kowalska",
              is_active: false,
              status: "completed",
              history_kept_at: "2026-07-01T09:00:00Z",
            }),
          ],
        }),
      ],
      { searchQuery: "Kowal Zof" },
    );
    expect(screen.getByRole("button", { name: "Zakończone (1)" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(rowOf(2)).toHaveClass("bg-primary/5");
    expect(rowOf(1)).not.toHaveClass("bg-primary/5");
  });
});

describe("OrdersTable — kontraktor z pojedynczym zamówieniem", () => {
  const contractor = (orderType: "periodic" | "md") =>
    ({
      contract_id: 466,
      candidate_id: 5,
      candidate_name: "Mateusz Wzorcowy",
      contract_status: "active",
      contract_start_date: "2026-09-01",
      contract_end_date: null,
      rate_candidate: 150,
      rate_client_currency: "PLN",
      rate_candidate_currency: "PLN",
      rate_unit: "daily",
      initial_job_id: null,
      initial_job_title: null,
      latest_order_id: 1,
      latest_order_end_date: "2026-12-31",
      latest_order_rate_client: 1450,
      latest_order_monthly_margin: null,
      days_to_latest_end: 90,
      orders: [
        {
          id: 1,
          client_id: 1,
          contract_id: 466,
          job_id: null,
          framework_contract_id: null,
          title: "9/98/2031/PR",
          description: null,
          status: "active",
          order_type: orderType,
          start_date: "2026-09-01",
          end_date: "2026-12-31",
          rate_unit: "daily",
          rate_candidate: 150,
          rate_client: 1450,
          total_value: null,
          currency: "PLN",
          rate_client_currency: "PLN",
          rate_candidate_currency: "PLN",
          project_part: null,
          filename: null,
          has_file: false,
          content_type: null,
          size_bytes: null,
          created_by_user_id: null,
          notes: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
          candidate_id: 5,
          candidate_name: null,
          contract_status: "active",
          job_title: null,
          monthly_margin: null,
          days_to_end: 90,
        },
      ],
    }) as never;

  function renderSection(type: "periodic" | "md") {
    const rows = buildSectionRows([{ kind: "contractor", contractor: contractor(type) }], {
      expandedEnded: new Set(),
      collapsedEnded: new Set(),
    });
    render(
      <OrdersTable
        sections={[{ type, itemCount: 1, rows }]}
        selectedKey={null}
        onSelect={vi.fn()}
        onToggleEnded={vi.fn()}
        searchQuery=""
        canDecide
        canManage
        canViewFinance
      />,
    );
    const row = document.getElementById("contractor-row-466")!;
    const headers = Array.from(row.closest("table")!.querySelectorAll("thead th")).map(
      (th) => th.textContent,
    );
    return { row, headers, cells: row.querySelectorAll("td") };
  }

  it("w sekcji „Okresowe” wiersz ma kolumny numeru, okresu, stawek i stanu", () => {
    const { row, headers, cells } = renderSection("periodic");
    expect(cells).toHaveLength(headers.length);
    expect(cells[headers.indexOf("Nr zamówienia")]).toHaveTextContent("9/98/2031/PR");
    expect(cells[headers.indexOf("Okres")]).toHaveTextContent("01.09.2026");
    expect(cells[headers.indexOf("Stan")]).toHaveTextContent("Aktywne");
    expect(within(row).getByRole("link", { name: "Mateusz Wzorcowy" })).toHaveAttribute(
      "href",
      "/contracts/466",
    );
  });

  it("w sekcji MD stawki stoją pod „Koszt”/„Przychód”, a nie pod kolumnami MD", () => {
    // Regresja przeglądu 29.09.2026: wiersz kontraktora renderował kolumny
    // okresowe pod nagłówkiem MD — numer zamówienia stał pod „Koszt".
    const { headers, cells } = renderSection("md");
    expect(cells).toHaveLength(headers.length);
    expect(cells[headers.indexOf("Koszt")]).toHaveTextContent(/150/);
    expect(cells[headers.indexOf("Koszt")]).not.toHaveTextContent("9/98/2031/PR");
    expect(cells[headers.indexOf("Przychód")]).toHaveTextContent(/1\s?450/);
    expect(cells[headers.indexOf("Uwagi")]).toHaveTextContent("Aktywne");
    expect(cells[headers.indexOf("Zostało MD")]).toHaveTextContent("9/98/2031/PR");
  });
});
