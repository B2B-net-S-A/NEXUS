import { describe, expect, it } from "vitest";

import type {
  ClientOrderRead,
  ContractWithOrdersRead,
  OrderType,
} from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import {
  DEFAULT_ORDER_LIST_FILTERS,
  consultantMatchesQuery,
  contractClosed,
  contractorMatchesPill,
  contractorOrderType,
  effectiveClientOrderType,
  effectiveGroupOrderType,
  filterMaterializedContractorShells,
  filterAndSortContractors,
  filterAndSortOrderGroups,
  flattenOrderGroupIds,
  isCurrentOrder,
  lacksCurrentOrder,
  orderGroupMatchesPill,
  sortOrderLinesByConsultant,
  usesSharedMdPool,
  visibleLegacyOrderIds,
} from "@/lib/client-order-list";

function line(
  id: number,
  consultantName: string,
  overrides: Partial<OrderLineRead> = {},
): OrderLineRead {
  return {
    id,
    group_id: 1,
    contract_id: id,
    candidate_id: id,
    consultant_name: consultantName,
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    rate_cost: 100,
    rate_revenue: 150,
    input_value: 100,
    input_mode: "md",
    md_total: 100,
    md_remaining: 50,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    ...overrides,
  };
}

function group(
  id: number,
  orderNumber: string,
  overrides: Partial<OrderGroupRead> = {},
): OrderGroupRead {
  return {
    id,
    client_id: 10,
    order_number: orderNumber,
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    notes: null,
    created_at: `2026-08-${String(id).padStart(2, "0")}T10:00:00Z`,
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    is_md_budget_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
    md_budget_total: null,
    md_budget_used: null,
    md_budget_remaining: null,
    md_budget_manual_adjustment: null,
    predecessor_group_id: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    file_uploaded_at: null,
    can_add_consultant: true,
    lines: [line(id, "Jan Kowalski")],
    active_consultants: 1,
    event_count: 0,
    future_orders: [],
    ...overrides,
  };
}

function contractor(
  contractId: number,
  candidateName: string,
  overrides: Partial<ContractWithOrdersRead> = {},
): ContractWithOrdersRead {
  return {
    contract_id: contractId,
    candidate_id: contractId,
    candidate_name: candidateName,
    contract_status: "active",
    contract_start_date: "2026-01-01",
    contract_end_date: "2026-12-31",
    rate_candidate: 100,
    rate_unit: "monthly",
    initial_job_id: null,
    initial_job_title: null,
    latest_order_id: null,
    latest_order_end_date: null,
    latest_order_rate_client: null,
    latest_order_monthly_margin: null,
    days_to_latest_end: null,
    orders: [],
    ...overrides,
  };
}

function clientOrder(
  id: number,
  orderType: OrderType,
  overrides: Partial<ClientOrderRead> = {},
): ClientOrderRead {
  return {
    id,
    client_id: 10,
    contract_id: id,
    job_id: null,
    framework_contract_id: null,
    title: `ORDER-${id}`,
    description: null,
    status: "cancelled",
    order_type: orderType,
    start_date: "2026-04-01",
    end_date: "2026-05-01",
    rate_client: 150,
    total_value: null,
    md_quantity: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: `2026-04-${String(id).padStart(2, "0")}T10:00:00Z`,
    updated_at: `2026-04-${String(id).padStart(2, "0")}T10:00:00Z`,
    candidate_id: id,
    candidate_name: `Kandydat ${id}`,
    contract_status: "ended",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...overrides,
  };
}

describe("client order list filters", () => {
  it("matches first and last name fragments in either order and without accents", () => {
    expect(consultantMatchesQuery("Łukasz Żółć", "zol luk")).toBe(true);
    expect(consultantMatchesQuery("Łukasz Żółć", "Anna Żółć")).toBe(false);
  });

  it("keeps the whole multi-consultant order when one consultant matches", () => {
    const item = group(1, "274607", {
      lines: [line(1, "Anna Nowak"), line(2, "Zofia Kowalska")],
    });
    expect(
      filterAndSortOrderGroups(
        [item],
        "Kowal Zof",
        DEFAULT_ORDER_LIST_FILTERS,
      ),
    ).toEqual([item]);
  });

  it("filters at 80% budget usage and combines it with ending-soon", () => {
    const near = group(1, "A", {
      end_date: "2026-09-10",
      lines: [line(1, "A B", { md_total: 100, md_remaining: 20 })],
    });
    const below = group(2, "B", {
      end_date: "2026-09-10",
      lines: [line(2, "C D", { md_total: 100, md_remaining: 21 })],
    });
    const result = filterAndSortOrderGroups(
      [below, near],
      "",
      {
        ...DEFAULT_ORDER_LIST_FILTERS,
        nearBudget: true,
        endingSoon: true,
        endingDays: 30,
      },
      "2026-08-21",
    );
    expect(result.map((item) => item.id)).toEqual([1]);
  });

  it("generic explicit MD z linią ignoruje błędną pulę grupową", () => {
    const near = group(1, "CP-MD-NEAR", {
      order_type: "md",
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 80,
      md_budget_remaining: 20,
      lines: [
        line(1, "A B", {
          input_mode: null,
          input_value: null,
          md_total: null,
          md_remaining: null,
        }),
      ],
    });
    const below = group(2, "CP-MD-BELOW", {
      order_type: "md",
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 79,
      md_budget_remaining: 21,
      lines: [
        line(2, "C D", {
          input_mode: null,
          input_value: null,
          md_total: null,
          md_remaining: null,
        }),
      ],
    });

    expect(usesSharedMdPool(near)).toBe(false);
    expect(
      filterAndSortOrderGroups(
        [below, near],
        "",
        { ...DEFAULT_ORDER_LIST_FILTERS, nearBudget: true },
        "2026-08-21",
      ),
    ).toEqual([]);
  });

  it.each(
    [
      [38339, "Cyfrowy Polsat"],
      [155, "Lotte Wedel"],
    ] as const,
  )(
    "filtr 80%% zachowuje specjalną pulę MD klienta %s (%s)",
    (clientId, _clientLabel) => {
      const near = group(1, "SHARED-MD-NEAR", {
        client_id: clientId,
        order_type: "md",
        is_md_budget_based: true,
        md_budget_total: 100,
        md_budget_used: 80,
        md_budget_remaining: 20,
        lines: [
          line(1, "A B", {
            input_mode: null,
            input_value: null,
            md_total: null,
            md_remaining: null,
          }),
        ],
      });

      expect(usesSharedMdPool(near)).toBe(true);
      expect(
        filterAndSortOrderGroups(
          [near],
          "",
          { ...DEFAULT_ORDER_LIST_FILTERS, nearBudget: true },
          "2026-08-21",
        ).map((item) => item.id),
      ).toEqual([1]);
    },
  );

  it("jawne MD bez linii ignoruje błędną pulę grupową", () => {
    const empty = group(1, "MD-EMPTY", {
      order_type: "md",
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 99,
      md_budget_remaining: 1,
      lines: [],
      active_consultants: 0,
    });

    expect(
      filterAndSortOrderGroups(
        [empty],
        "",
        { ...DEFAULT_ORDER_LIST_FILTERS, nearBudget: true },
        "2026-08-21",
      ),
    ).toEqual([]);
  });

  it("sorts groups by average consultant rate and lines alphabetically", () => {
    const cheaper = group(1, "A", {
      lines: [
        line(1, "Zofia Nowak", { rate_cost: 100 }),
        line(2, "Adam Kowalski", { rate_cost: 200 }),
      ],
    });
    const dearer = group(2, "B", {
      lines: [line(3, "Beata Lis", { rate_cost: 175 })],
    });
    expect(
      filterAndSortOrderGroups(
        [cheaper, dearer],
        "",
        { ...DEFAULT_ORDER_LIST_FILTERS, sort: "cost_desc" },
      ).map((item) => item.id),
    ).toEqual([2, 1]);
    expect(
      sortOrderLinesByConsultant(cheaper.lines).map((item) => item.consultant_name),
    ).toEqual(["Adam Kowalski", "Zofia Nowak"]);
  });

  it("sorts groups by the alphabetically first consultant, Z→A being the exact reverse", () => {
    const groups = [
      group(2, "B", { lines: [line(3, "Beata Lis")] }),
      group(3, "C", { lines: [line(4, "\u0141ukasz \u017b\u00f3\u0142\u0107")] }),
      // Grupa wielo-konsultantowa jedzie po SWOIM pierwszym alfabetycznie
      // nazwisku, nie po kolejności linii z serwera.
      group(1, "A", { lines: [line(1, "Zofia Nowak"), line(2, "Adam Kowalski")] }),
    ];
    const asc = filterAndSortOrderGroups([...groups], "", {
      ...DEFAULT_ORDER_LIST_FILTERS,
      sort: "consultant_asc",
    });
    expect(asc.map((item) => item.id)).toEqual([1, 2, 3]);

    const desc = filterAndSortOrderGroups([...groups], "", {
      ...DEFAULT_ORDER_LIST_FILTERS,
      sort: "consultant_desc",
    });
    // Odwrotność, a nie „grupa po ostatnim nazwisku" — inaczej grupa
    // [Adam, Zofia] stałaby na czele OBU porządków.
    expect(desc.map((item) => item.id)).toEqual([3, 2, 1]);
  });

  it("keeps a consultant-less order group last in both directions", () => {
    const groups = [
      group(9, "EMPTY", { lines: [] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    // Pusty klucz nigdy nie otwiera listy „A\u2192Z" — tam użytkownik spodziewa
    // się realnego „A", nie wiersza bez konsultanta.
    expect(ids("consultant_asc")).toEqual([1, 2, 9]);
    expect(ids("consultant_desc")).toEqual([2, 1, 9]);
  });

  it("sorts contractors alphabetically with Polish folding", () => {
    const contractors = [
      contractor(3, "\u017banna Zaj\u0105c"),
      contractor(1, "\u0141ukasz Domaga\u0142a"),
      contractor(2, "Adam \u015awi\u0105tek"),
      contractor(4, ""),
    ];
    const names = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortContractors([...contractors], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.contract_id);
    // \u0141 sk\u0142ada si\u0119 do „l", \u015a do „s", \u017b do „z" \u2014 tak jak w wyszukiwarce
    // (`foldText`), wi\u0119c kolejno\u015b\u0107 to Adam < \u0141ukasz < \u017banna.
    expect(names("consultant_asc")).toEqual([2, 1, 3, 4]);
    expect(names("consultant_desc")).toEqual([3, 1, 2, 4]);
  });

  it("filtruje i sortuje po datach reprezentatywnego anulowanego cost/MD", () => {
    const cancelledMd = contractor(1, "Anulowane MD", {
      orders: [
        clientOrder(1, "md", {
          start_date: "2026-04-10",
          end_date: "2026-05-10",
          created_at: "2026-04-10T10:00:00Z",
        }),
      ],
    });
    const cancelledCost = contractor(2, "Anulowane kosztowe", {
      orders: [
        clientOrder(2, "cost", {
          start_date: "2026-04-20",
          end_date: "2026-05-20",
          created_at: "2026-04-20T10:00:00Z",
        }),
      ],
    });

    expect(
      filterAndSortContractors(
        [cancelledMd, cancelledCost],
        "",
        {
          ...DEFAULT_ORDER_LIST_FILTERS,
          startFrom: "2026-04-01",
          startTo: "2026-04-30",
          endFrom: "2026-05-01",
          endTo: "2026-05-31",
        },
        "2026-08-29",
      ).map((item) => item.contract_id),
    ).toEqual([2, 1]);
  });

  it("traktuje serwerowy myślnik jak brak konsultanta, nie jak nazwisko", () => {
    // `consultant_display_name` (backend) zwraca „—" dla linii bez kandydata.
    // Myślnik wypada w kolacji PRZED każdą literą, więc bez odsiania wiersz bez
    // konsultanta otwierałby listę „A→Z".
    const groups = [
      group(9, "DASH", { lines: [line(9, "—")] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    expect(ids("consultant_asc")).toEqual([1, 2, 9]);
    expect(ids("consultant_desc")).toEqual([2, 1, 9]);
  });

  it("nie daje się wynieść na szczyt A→Z śmieciowi przyklejonemu do nazwiska", () => {
    // Realny wiersz z produkcji Nordei: „{ } Wojciech Łazowski". Backend keyuje
    // nazwiska po [a-z0-9], więc import go dopasowuje bez problemu — rozjazd był
    // wyłącznie w sortowaniu, gdzie `{` wypada przed każdą literą.
    const groups = [
      group(3, "C", { lines: [line(3, "{ } Wojciech Łazowski")] }),
      group(1, "A", { lines: [line(1, "Adam Kowalski")] }),
      group(2, "B", { lines: [line(2, "Zofia Nowak")] }),
    ];
    const ids = (sort: "consultant_asc" | "consultant_desc") =>
      filterAndSortOrderGroups([...groups], "", {
        ...DEFAULT_ORDER_LIST_FILTERS,
        sort,
      }).map((item) => item.id);
    // Ł składa się do „l", więc Adam < Wojciech < Zofia.
    expect(ids("consultant_asc")).toEqual([1, 3, 2]);
    expect(ids("consultant_desc")).toEqual([2, 3, 1]);
  });

  it("exports nested future orders in their visible order", () => {
    const future = group(2, "FUTURE");
    const current = group(1, "CURRENT", { future_orders: [future] });
    expect(flattenOrderGroupIds([current])).toEqual([1, 2]);
  });

  it("eksportuje jedno, aktualne zamówienie na konsultanta", () => {
    // Wcześniej szła tu cała historia kontraktora, więc ta sama osoba
    // pojawiała się w arkuszu tyle razy, ile zamówień przewinęło się przez
    // jej kontrakt — razem z zakończonymi i jeszcze nierozpoczętymi.
    const today = "2026-09-01";
    const rows = [
      contractor(1, "Jarosław Suchanek", {
        orders: [
          clientOrder(10, "periodic", {
            title: "PRZESZLE",
            status: "completed",
            start_date: "2025-01-01",
            end_date: "2025-12-31",
          }),
          clientOrder(11, "periodic", {
            title: "BIEZACE",
            status: "active",
            start_date: "2026-04-01",
            end_date: "2026-09-30",
          }),
          clientOrder(12, "periodic", {
            title: "PRZYSZLE",
            status: "active",
            start_date: "2026-11-01",
            end_date: "2027-04-30",
          }),
        ],
      }),
    ];

    expect(visibleLegacyOrderIds(rows, "", today)).toEqual([11]);
  });

  it("uznaje kończące się i bezterminowe zamówienie za aktualne", () => {
    const today = "2026-09-01";
    expect(
      isCurrentOrder(
        { status: "active", start_date: "2026-01-01", end_date: "2026-09-02" },
        today,
      ),
    ).toBe(true);
    expect(
      isCurrentOrder(
        { status: "active", start_date: "2026-01-01", end_date: null },
        today,
      ),
    ).toBe(true);
    expect(
      isCurrentOrder(
        { status: "completed", start_date: "2026-01-01", end_date: null },
        today,
      ),
    ).toBe(false);
    expect(
      isCurrentOrder(
        { status: "active", start_date: "2026-10-01", end_date: null },
        today,
      ),
    ).toBe(false);
  });

  it("chowa kartę kontraktora, po której został wyłącznie martwy duplikat", () => {
    // Zamówienie zakończone/anulowane nie jest osobnym zaangażowaniem — po
    // sprzątnięciu duplikatu (migracja 0262) osoba ma być na liście RAZ,
    // jako linia zamówienia MD.
    const md = group(1, "MD", {
      lines: [line(11, "Jarosław Suchanek", { contract_id: 11 })],
    });

    const result = filterMaterializedContractorShells(
      [
        contractor(11, "Jarosław Suchanek", {
          orders: [
            clientOrder(900, "periodic", {
              title: "ZAM_1453_2026",
              status: "cancelled",
              end_date: "2026-09-30",
            }),
          ],
        }),
        contractor(12, "Osoba z żywym okresowym", {
          orders: [
            clientOrder(901, "periodic", {
              title: "ZAM-OKRESOWE",
              status: "active",
              end_date: null,
            }),
          ],
        }),
      ],
      [
        md,
        group(2, "MD-2", {
          lines: [line(12, "Osoba z żywym okresowym", { contract_id: 12 })],
        }),
      ],
      "2026-09-01",
    );

    expect(result.map((item) => item.contract_id)).toEqual([12]);
  });

  it("usuwa tylko puste shelle kontraktów obecnych w grupach, także przyszłych", () => {
    const future = group(2, "FUTURE", {
      lines: [line(22, "Future Person", { contract_id: 22 })],
    });
    const current = group(1, "CURRENT", {
      lines: [line(11, "Current Person", { contract_id: 11 })],
      future_orders: [future],
    });

    const result = filterMaterializedContractorShells(
      [
        contractor(11, "Shell bieżącej grupy"),
        contractor(22, "Shell przyszłej grupy"),
        contractor(33, "Prawidłowy draft bez grupy", {
          contract_status: "draft",
        }),
      ],
      [current],
    );

    expect(result.map((item) => item.contract_id)).toEqual([33]);
  });

  it("resolves legacy and explicit order types without guessing from names", () => {
    expect(effectiveGroupOrderType(group(1, "MD"))).toBe("md");
    expect(
      effectiveGroupOrderType(group(2, "COST", { is_cost_based: true })),
    ).toBe("cost");
    expect(
      effectiveGroupOrderType(
        group(3, "EXPLICIT", { order_type: "md", is_cost_based: true }),
      ),
    ).toBe("md");
    expect(effectiveClientOrderType({ order_type: null })).toBe("periodic");
    expect(effectiveClientOrderType({ order_type: null }, "md")).toBe("md");
    expect(effectiveClientOrderType({ order_type: "periodic" }, "md")).toBe(
      "periodic",
    );
    expect(effectiveClientOrderType({ order_type: "cost" })).toBe("cost");
    expect(contractorOrderType(contractor(1, "Bez zamówienia"))).toBe("periodic");
  });

  it("uses the same status predicates for unified counters and rows", () => {
    expect(orderGroupMatchesPill(group(1, "ACTIVE"), "active")).toBe(true);
    expect(
      orderGroupMatchesPill(
        group(2, "DONE", { status: "completed" }),
        "completed",
      ),
    ).toBe(true);
    expect(orderGroupMatchesPill(group(3, "NO-DRAFT"), "draft")).toBe(false);
    expect(
      contractorMatchesPill(
        contractor(4, "Draft", { contract_status: "draft" }),
        "draft",
      ),
    ).toBe(true);
  });
});

// ── Reguła zakładki „Zakończeni" (09.2026) ──────────────────────────────────
// O przynależności decyduje wyłącznie umowa z modułu Kontrakty — status i data
// zakończenia — nigdy sam upływ okresu zamówienia.
describe("reguła zakładki Zakończeni", () => {
  const TODAY = "2026-09-03";
  const past = (over: Partial<ClientOrderRead> = {}) =>
    clientOrder(1, "periodic", {
      status: "completed",
      start_date: "2026-07-01",
      end_date: "2026-08-31",
      ...over,
    });

  it("umowa zamknięta = status końcowy ORAZ data końca, która minęła", () => {
    expect(
      contractClosed(
        contractor(1, "Wczoraj", { contract_status: "ended", contract_end_date: "2026-09-02" }),
        TODAY,
      ),
    ).toBe(true);
    // Do daty końca włącznie osoba pracuje.
    expect(
      contractClosed(
        contractor(2, "Dziś", { contract_status: "ended", contract_end_date: "2026-09-03" }),
        TODAY,
      ),
    ).toBe(false);
    expect(
      contractClosed(
        contractor(3, "Jutro", { contract_status: "ended", contract_end_date: "2026-09-30" }),
        TODAY,
      ),
    ).toBe(false);
    // Bez daty nie ma czego minąć — „ended" bez daty to zaszłość, nie zakończenie.
    expect(
      contractClosed(
        contractor(4, "Bezterminowa", { contract_status: "ended", contract_end_date: null }),
        TODAY,
      ),
    ).toBe(false);
    expect(
      contractClosed(
        contractor(5, "Aktywna", { contract_status: "active", contract_end_date: "2026-01-01" }),
        TODAY,
      ),
    ).toBe(false);
  });

  it("upływ okresu zamówienia NIE przenosi do Zakończonych — zostaje dopisek", () => {
    // Klimczak po 31.08: umowa aktywna (bezterminowa), zamówienie minęło.
    const klimczak = contractor(469, "Piotr Klimczak", {
      contract_status: "active",
      contract_end_date: null,
      days_to_latest_end: -3,
      orders: [past()],
    });
    expect(contractorMatchesPill(klimczak, "active", TODAY)).toBe(true);
    expect(contractorMatchesPill(klimczak, "completed", TODAY)).toBe(false);
    expect(lacksCurrentOrder(klimczak, TODAY)).toBe(true);

    // Przedłużenie dodane (zaczyna się później) — dopisek znika.
    const extended = contractor(469, "Piotr Klimczak", {
      contract_status: "active",
      orders: [
        past(),
        clientOrder(2, "periodic", { status: "active", start_date: "2026-09-01", end_date: "2026-12-31" }),
      ],
    });
    expect(lacksCurrentOrder(extended, TODAY)).toBe(false);
    // Bezterminowe zamówienie obejmuje dziś; anulowane i szkice nie liczą się.
    expect(
      lacksCurrentOrder(
        contractor(7, "Open", { orders: [clientOrder(3, "periodic", { status: "active", start_date: "2026-01-01", end_date: null })] }),
        TODAY,
      ),
    ).toBe(false);
    expect(
      lacksCurrentOrder(
        contractor(8, "Anulowane", { orders: [clientOrder(4, "periodic", { status: "cancelled", start_date: "2026-01-01", end_date: null })] }),
        TODAY,
      ),
    ).toBe(true);
  });

  it("umowa z datą końca dziś lub później trzyma osobę w Aktywnych do dnia X włącznie", () => {
    const endsToday = contractor(10, "Kończy dziś", {
      contract_status: "ended",
      contract_end_date: TODAY,
      orders: [past({ end_date: TODAY })],
    });
    expect(contractorMatchesPill(endsToday, "active", TODAY)).toBe(true);
    expect(contractorMatchesPill(endsToday, "completed", TODAY)).toBe(false);
    // Od dnia X+1 — Zakończeni.
    expect(contractorMatchesPill(endsToday, "active", "2026-09-04")).toBe(false);
    expect(contractorMatchesPill(endsToday, "completed", "2026-09-04")).toBe(true);
  });
});

