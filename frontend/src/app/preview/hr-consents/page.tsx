"use client";

/**
 * Harness „Zgody” — wydatki i premie poza umową (makiety 20.10.2026).
 *
 * Prawdziwe `PeopleSectionNav` + `ApprovalsScreen` / `MyConsentsScreen` na
 * zasianym cache, ZERO zapytań (`hr-harness.tsx`). Stany (`?state=`):
 * - `inbox` (domyślnie) — zatwierdzający (admin): premia poza umową z liczbami
 *   „NEXUS sprawdził”, delegacja poparta przez przełożoną, subskrypcja,
 *   prezent, dopłata do decyzji (faktura +18%); od 22.10.2026 jedna lista
 *   z chipami — „Wszystko” pokazuje zgody razem z urlopem Kamila do decyzji,
 *   „Zdecydowane” zgody już rozstrzygnięte;
 * - `supervisor` — przełożona: delegacja ponad próg („Popieram”) i prezent
 *   w progu („Zatwierdź”);
 * - `mine` — autorka: pytanie od zatwierdzającego, zgoda w toku, rozliczenia
 *   (etap 3): delegacja czeka na fakturę, szkolenie z fakturą +18% („Poproś
 *   o dopłatę”), subskrypcja roczna z pytaniem o odnowienie;
 * - `form` — „Poproś o zgodę” (panel „Kto zdecyduje” pyta serwer — w harnessie
 *   pokazuje komunikat o braku sieci); przy premii Julia jest na B2B (pole
 *   „Podstawa w umowie” wymagane, 0491), Kamil na umowie o pracę.
 * Zapisy blokuje harness.
 */

import { PageHeader } from "@/components/ds/PageHeader";
import { MyConsentsScreen } from "@/components/hr/approvals/MyConsentsScreen";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import {
  approvalKeys,
  type ApprovalDocument,
  type ApprovalRequestRow,
  type ApprovalSettlement,
  type ApprovalTopupRow,
} from "@/lib/api/hr-approvals";
import { leaveKeys, type PendingLeaveRow } from "@/lib/api/hr-leave";
import { timeKeys } from "@/lib/api/hr-time";
import { defaultQueueMonth } from "@/components/hr/time/time-format";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";

const STATE_KEYS = ["inbox", "supervisor", "mine", "form"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "inbox", label: "Zatwierdzający", href: "?state=inbox&tab=consents" },
  {
    key: "supervisor",
    label: "Przełożona",
    href: "?state=supervisor&tab=consents",
  },
  { key: "mine", label: "Moje zgody" },
  { key: "form", label: "Poproś o zgodę", href: "?state=form&new=1" },
] as const;

const NOTES: Record<State, string> = {
  inbox: "Dane fikcyjne, bez zapytań. Ogląda zatwierdzający (admin).",
  supervisor: "Dane fikcyjne, bez zapytań. Ogląda przełożona — próg delegacji 1 500 zł.",
  mine: "Dane fikcyjne, bez zapytań. Ogląda autorka zgód.",
  form: "Dane fikcyjne, bez zapytań. „Kto zdecyduje” liczy serwer — tu bez sieci. Premia: Julia na B2B, Kamil na UoP.",
};

function iso(daysFromToday: number): string {
  const date = new Date();
  date.setDate(date.getDate() + daysFromToday);
  return date.toISOString().slice(0, 10);
}

function moment(daysAgo: number, hour = 9): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  date.setHours(hour, 12, 0, 0);
  return date.toISOString();
}

const NOW = new Date();

function row(
  partial: Partial<ApprovalRequestRow> & Pick<ApprovalRequestRow, "id" | "kind" | "title">,
): ApprovalRequestRow {
  return {
    kind_label: "Inny wydatek",
    status: "pending_final",
    status_label: "Czeka na zatwierdzającego",
    purpose: "",
    amount: "100.00",
    decided_amount: null,
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    amount_text: "100 zł brutto",
    payer: "company_invoice",
    link_url: null,
    needed_by: null,
    starts_on: null,
    ends_on: null,
    beneficiary_user_id: null,
    beneficiary_name: null,
    payout_year: null,
    payout_month: null,
    requester_user_id: HR_CAST.ola.id,
    requester_name: HR_CAST.ola.name,
    supervisor_user_id: null,
    supervisor_name: null,
    needs_final: true,
    final_approver_names: [HR_CAST.admin.name],
    endorsed_by_name: null,
    endorsed_at: null,
    endorse_note: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    decision_channel: null,
    bonus_id: null,
    submitted_at: moment(0, 8),
    can_decide: true,
    decides_as: "final",
    can_edit: false,
    can_withdraw: false,
    context: null,
    ...partial,
  };
}

function doc(partial: Partial<ApprovalDocument> & Pick<ApprovalDocument, "id">): ApprovalDocument {
  return {
    source: "upload",
    doc_type: "invoice",
    status: "pinned",
    status_label: "do rozliczenia",
    approval_request_id: null,
    match_reason: "upload",
    match_reason_label: "dołączona do zgody",
    ksef_number: null,
    seller_nip: null,
    seller_name: "Organizator Przykładowy sp. z o.o.",
    invoice_number: "FV 7/10/2026",
    issue_date: iso(-2),
    currency: "PLN",
    net_amount: null,
    vat_amount: null,
    gross_amount: "1416.00",
    file_name: "faktura.pdf",
    has_file: true,
    read_status: "read",
    topup: null,
    settled_at: null,
    settled_by_name: null,
    settle_note: null,
    close_note: null,
    comparison: null,
    can_edit: true,
    can_remove: true,
    can_request_topup: false,
    can_decide_topup: false,
    can_settle: false,
    ...partial,
  };
}

function settlement(partial: Partial<ApprovalSettlement> & Pick<ApprovalSettlement, "status" | "status_label">): ApprovalSettlement {
  return {
    expires_on: iso(21),
    renews_on: null,
    renewal_asked_for: null,
    renewal_confirmed_for: null,
    ended_on: null,
    settled_at: null,
    settled_by_name: null,
    seller_nip: null,
    client_id: null,
    client_name: null,
    tolerance_percent: 10,
    comparison: null,
    documents: [],
    can_add_document: true,
    can_answer_renewal: false,
    can_end: false,
    ...partial,
  };
}

const OVER = {
  status: "over" as const,
  approved: "1200.00",
  documented: "1416.00",
  limit: "1320.00",
  excess: "216.00",
  percent: 18,
};

function topupRows(): ApprovalTopupRow[] {
  return [
    {
      request_id: 21,
      title: "Konferencja rekruterów IT — bilet",
      kind_label: "Szkolenie",
      requester_name: HR_CAST.ola.name,
      amount_text: "1 200 zł brutto",
      document: doc({
        id: 31,
        approval_request_id: 21,
        comparison: OVER,
        topup: {
          status: "pending",
          amount: "216.00",
          requested_at: moment(0, 9),
          decided_at: null,
          decided_by_name: null,
          note: null,
        },
        can_edit: false,
        can_remove: false,
        can_decide_topup: true,
      }),
    },
  ];
}

const CONTEXT = {
  kind_month: { count: 2, amount: "3500.00" },
  kind_year: { count: 11, amount: "18200.00" },
  all_month: { count: 14, amount: "21380.00" },
};

function inboxRows(): ApprovalRequestRow[] {
  return [
    row({
      id: 1,
      kind: "bonus",
      kind_label: "Wynagrodzenie dodatkowe",
      title: "Trzy przejęte rekrutacje",
      purpose:
        "Przejęła 3 rekrutacje po odejściu kolegi i domknęła je w 2 tygodnie. Standardowa premia z placementu dotyczy tylko jednej z nich.",
      amount: "1500.00",
      amount_text: "1 500 zł brutto",
      payer: null,
      needed_by: iso(1),
      beneficiary_user_id: HR_CAST.julia.id,
      beneficiary_name: HR_CAST.julia.name,
      payout_year: NOW.getFullYear(),
      payout_month: NOW.getMonth() + 1,
      contract_basis: "§ 6 ust. 2 umowy z 01.03.2025",
      requester_user_id: HR_CAST.marta.id,
      requester_name: HR_CAST.marta.name,
      context: {
        ...CONTEXT,
        beneficiary_year: {
          automatic: "9400.00",
          outside_contract: "0.00",
          manual: "0.00",
          same_month_automatic: "0.00",
        },
      },
    }),
    row({
      id: 2,
      kind: "trip",
      kind_label: "Delegacja",
      title: "Gdańsk — warsztat u klienta",
      purpose: "Warsztat z hiring managerem, dwie rekrutacje. Hotel 1 noc, pociąg, diety.",
      amount: "2180.00",
      amount_text: "2 180 zł brutto",
      payer: "reimbursement",
      needed_by: iso(1),
      starts_on: iso(2),
      ends_on: iso(3),
      requester_user_id: HR_CAST.tomasz.id,
      requester_name: HR_CAST.tomasz.name,
      supervisor_user_id: HR_CAST.marta.id,
      supervisor_name: HR_CAST.marta.name,
      endorsed_by_name: HR_CAST.marta.name,
      endorsed_at: moment(0, 10),
      endorse_note: "Ważny klient, warto.",
      context: { ...CONTEXT, kind_month: { count: 3, amount: "3900.00" } },
    }),
    row({
      id: 3,
      kind: "subscription",
      kind_label: "Subskrypcja",
      title: "Narzędzie do ogłoszeń — 3 licencje",
      purpose:
        "Automatyczne publikowanie ogłoszeń w trzech kanałach. Dziś ok. 6 h ręcznej pracy tygodniowo.",
      amount: "240.00",
      amount_basis: "net",
      recurrence: "monthly",
      amount_text: "240 zł netto / mies.",
      link_url: "https://example.com/cennik",
      requester_user_id: HR_CAST.ewa.id,
      requester_name: HR_CAST.ewa.name,
      context: { ...CONTEXT, kind_month: { count: 1, amount: "610.00" } },
    }),
    row({
      id: 4,
      kind: "gift",
      kind_label: "Prezent",
      title: "Prezent dla klienta — 10 lat współpracy",
      purpose: "Kosz upominkowy dla zespołu klienta na rocznicę.",
      amount: "450.00",
      amount_text: "450 zł brutto",
      requester_user_id: HR_CAST.adam.id,
      requester_name: HR_CAST.adam.name,
      context: { ...CONTEXT, kind_month: { count: 1, amount: "200.00" } },
    }),
  ];
}

function supervisorRows(): ApprovalRequestRow[] {
  return [
    row({
      id: 2,
      kind: "trip",
      kind_label: "Delegacja",
      status: "pending_supervisor",
      status_label: "U przełożonego",
      title: "Gdańsk — warsztat u klienta",
      purpose: "Warsztat z hiring managerem, dwie rekrutacje. Hotel 1 noc, pociąg, diety.",
      amount: "2180.00",
      amount_text: "2 180 zł brutto",
      payer: "reimbursement",
      needed_by: iso(1),
      requester_user_id: HR_CAST.tomasz.id,
      requester_name: HR_CAST.tomasz.name,
      supervisor_user_id: HR_CAST.marta.id,
      supervisor_name: HR_CAST.marta.name,
      decides_as: "supervisor",
      context: { ...CONTEXT, all_month: { count: 10, amount: "13880.00" } },
    }),
    row({
      id: 5,
      kind: "gift",
      kind_label: "Prezent",
      status: "pending_supervisor",
      status_label: "U przełożonego",
      title: "Kwiaty dla kandydatki — powitanie",
      purpose: "Pierwszy dzień u klienta, mały gest od zespołu.",
      amount: "150.00",
      amount_text: "150 zł brutto",
      requester_user_id: HR_CAST.julia.id,
      requester_name: HR_CAST.julia.name,
      supervisor_user_id: HR_CAST.marta.id,
      supervisor_name: HR_CAST.marta.name,
      needs_final: false,
      decides_as: "supervisor",
      context: {
        ...CONTEXT,
        kind_month: { count: 1, amount: "200.00" },
        all_month: { count: 10, amount: "13880.00" },
      },
    }),
  ];
}

function mineRows(): ApprovalRequestRow[] {
  const base = {
    requester_user_id: HR_CAST.ola.id,
    requester_name: HR_CAST.ola.name,
    supervisor_user_id: HR_CAST.marta.id,
    supervisor_name: HR_CAST.marta.name,
    can_decide: false,
    decides_as: null,
  } as const;
  return [
    row({
      ...base,
      id: 11,
      kind: "training",
      kind_label: "Szkolenie",
      status: "returned",
      status_label: "Pytanie do Ciebie",
      title: "Konferencja rekruterów IT — bilet",
      purpose: "Dwa dni prelekcji o sourcingu, materiały dla zespołu.",
      amount: "1200.00",
      amount_text: "1 200 zł brutto",
      endorsed_by_name: HR_CAST.marta.name,
      endorsed_at: moment(2, 11),
      decided_by_name: HR_CAST.admin.name,
      decided_at: moment(1, 8),
      decision_note: "Czy jest tańsza pula biletów early bird? Dopisz, proszę.",
      submitted_at: moment(2, 9),
      can_edit: true,
      can_withdraw: true,
    }),
    row({
      ...base,
      id: 12,
      kind: "other",
      kind_label: "Inny wydatek",
      status: "pending_supervisor",
      status_label: "U przełożonego",
      title: "Monitor do pracy zdalnej",
      purpose: "Drugi ekran do pracy z kilkoma rekrutacjami naraz.",
      amount: "890.00",
      amount_text: "890 zł brutto",
      submitted_at: moment(0, 9),
      can_edit: true,
      can_withdraw: true,
    }),
    row({
      ...base,
      id: 13,
      kind: "trip",
      kind_label: "Delegacja",
      status: "approved",
      status_label: "Zatwierdzona",
      title: "Kraków — spotkanie z klientem",
      purpose: "Spotkanie kwartalne, pociąg w obie strony.",
      amount: "640.00",
      amount_text: "640 zł brutto",
      needs_final: false,
      decided_by_name: HR_CAST.marta.name,
      decided_at: moment(9, 14),
      submitted_at: moment(10, 9),
      settlement: settlement({ status: "open", status_label: "czeka na fakturę" }),
    }),
    row({
      ...base,
      id: 21,
      kind: "training",
      kind_label: "Szkolenie",
      status: "approved",
      status_label: "Zatwierdzona",
      title: "Warsztaty z sourcingu — bilet",
      purpose: "Dwa dni warsztatów, materiały dla zespołu.",
      amount: "1200.00",
      amount_text: "1 200 zł brutto",
      endorsed_by_name: HR_CAST.marta.name,
      endorsed_at: moment(6, 11),
      decided_by_name: HR_CAST.admin.name,
      decided_at: moment(5, 8),
      submitted_at: moment(6, 9),
      settlement: settlement({
        status: "documented",
        status_label: "do rozliczenia",
        comparison: OVER,
        documents: [
          doc({ id: 31, approval_request_id: 21, comparison: OVER, can_request_topup: true }),
        ],
      }),
    }),
    row({
      ...base,
      id: 22,
      kind: "subscription",
      kind_label: "Subskrypcja",
      status: "approved",
      status_label: "Zatwierdzona",
      title: "Narzędzie do ogłoszeń — licencja roczna",
      purpose: "Publikowanie ogłoszeń w trzech kanałach.",
      amount: "2400.00",
      recurrence: "yearly",
      amount_text: "2 400 zł brutto / rok",
      decided_by_name: HR_CAST.admin.name,
      decided_at: moment(330, 8),
      submitted_at: moment(331, 9),
      settlement: settlement({
        status: "active",
        status_label: "w rejestrze",
        renews_on: iso(26),
        renewal_asked_for: iso(26),
        can_answer_renewal: true,
        can_end: true,
        documents: [
          doc({
            id: 32,
            approval_request_id: 22,
            source: "ksef",
            seller_name: "Dostawca Przykładowy sp. z o.o.",
            invoice_number: "FV/2025/11/18",
            issue_date: iso(-330),
            gross_amount: "2400.00",
            status: "settled",
            status_label: "rozliczona",
            file_name: null,
            has_file: false,
            comparison: { ...OVER, status: "fits", approved: "2400.00", documented: "2400.00", limit: "2640.00", excess: null, percent: null },
            can_edit: false,
            can_remove: false,
          }),
        ],
      }),
    }),
  ];
}

/** Zgody, o których zatwierdzający już zdecydował („Zdecydowane”). */
function decidedRows(): ApprovalRequestRow[] {
  return [
    row({
      id: 31,
      kind: "training",
      kind_label: "Szkolenie",
      title: "Kurs negocjacji",
      status: "approved",
      status_label: "Zatwierdzona",
      amount: "1200.00",
      amount_text: "1 200 zł brutto",
      submitted_at: moment(9, 9),
      decided_by_name: HR_CAST.admin.name,
      decided_at: moment(8, 14),
      can_decide: false,
      decides_as: null,
    }),
    row({
      id: 32,
      kind: "gift",
      kind_label: "Prezent",
      title: "Kosz świąteczny dla klienta",
      status: "rejected",
      status_label: "Odrzucona",
      amount: "450.00",
      amount_text: "450 zł brutto",
      submitted_at: moment(12, 9),
      decided_by_name: HR_CAST.admin.name,
      decided_at: moment(11, 10),
      can_decide: false,
      decides_as: null,
    }),
  ];
}

/** Urlop do decyzji obok zgód — „Wszystko” to jedna lista (22.10.2026). */
function pendingLeave(): PendingLeaveRow[] {
  const kamil = HR_CAST.kamil;
  return [
    {
      id: "lv-c-1",
      user_id: kamil.id,
      user_name: kamil.name,
      leave_type: "vacation",
      leave_type_label: "Urlop wypoczynkowy",
      status: "pending",
      start_date: iso(20),
      end_date: iso(24),
      half_day: null,
      days_total: "5",
      paid_days: "5",
      unpaid_days: "0",
      note: null,
      substitute_user_id: HR_CAST.ola.id,
      substitute_name: HR_CAST.ola.name,
      forward_mail_consent: false,
      oof_internal_message: null,
      oof_external_message: null,
      decided_by_name: null,
      decided_at: null,
      decision_note: null,
      source: "self",
      created_at: moment(1, 9),
      can_cancel: false,
      department: kamil.department,
      manager_name: HR_CAST.marta.name,
      work_total: 0,
      work_by_kind: [],
      department_absent: [],
      type_visible: true,
      can_decide: true,
    },
  ];
}

function consentsConfig(me: Partial<HrConfig["me"]>): HrConfig {
  const config = hrConfig(me);
  return {
    ...config,
    modules: { ...config.modules, approvals: true },
    open_modules: { ...config.open_modules, approvals: true },
  };
}

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "inbox");
  const client = harnessQueryClient();
  let user: HarnessUser = HR_CAST.admin;
  let config = consentsConfig({ is_admin: true, has_profile: false });
  if (state === "inbox") {
    const rows = inboxRows();
    client.setQueryData(approvalKeys.list("inbox"), rows);
    for (const item of rows) client.setQueryData(approvalKeys.detail(item.id), item);
    client.setQueryData(approvalKeys.list("decided"), decidedRows());
    client.setQueryData(approvalKeys.topups, topupRows());
    client.setQueryData(approvalKeys.count, rows.length + 1);
    client.setQueryData(hrKeys.counts, {
      approvals: 2,
      consents: rows.length + 1,
      cases: null,
    });
  } else if (state === "supervisor") {
    user = HR_CAST.marta;
    config = consentsConfig({ is_manager: true, direct_reports: 9 });
    const rows = supervisorRows();
    client.setQueryData(approvalKeys.list("inbox"), rows);
    for (const item of rows) client.setQueryData(approvalKeys.detail(item.id), item);
    client.setQueryData(approvalKeys.list("decided"), []);
    client.setQueryData(approvalKeys.topups, []);
    client.setQueryData(hrKeys.counts, {
      approvals: 1,
      consents: rows.length,
      cases: null,
    });
  } else {
    user = HR_CAST.ola;
    config = consentsConfig({});
    client.setQueryData(approvalKeys.list("mine"), mineRows());
    client.setQueryData(approvalKeys.beneficiaries, [
      { user_id: HR_CAST.julia.id, name: HR_CAST.julia.name, needs_contract_basis: true },
      { user_id: HR_CAST.kamil.id, name: HR_CAST.kamil.name, needs_contract_basis: false },
    ]);
    client.setQueryData(hrKeys.counts, {
      approvals: null,
      consents: 0,
      cases: null,
    });
  }
  // Nieobecności i raporty godzin w tej samej liście „Akceptacji” — zasiane,
  // bez zapytań: urlop Kamila u zatwierdzającego, pusta historia i kolejka.
  const leave = state === "inbox" ? pendingLeave() : [];
  client.setQueryData(leaveKeys.pending, {
    items: leave,
    total: leave.length,
    covering: [],
    reported: [],
  });
  client.setQueryData(leaveKeys.history({ status: null, user_id: null }), {
    items: [],
    counts: { all: 0, pending: 0, approved: 0, rejected: 0, cancelled: 0 },
  });
  client.setQueryData(leaveKeys.people, []);
  const period = defaultQueueMonth();
  client.setQueryData(timeKeys.team(period.year, period.month), {
    year: period.year,
    month: period.month,
    norm_hours: 168,
    items: [],
  });
  client.setQueryData(hrKeys.config, config);
  return { user, client, value: { state, config } };
}

export default function HrConsentsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  const mine = state === "mine" || state === "form";
  return (
    <HrHarnessShell
      client={ready.client}
      title="Zgody"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      <div className="space-y-4">
        <PageHeader
          title={mine ? "Moje zgody" : "Akceptacje"}
          description={
            mine
              ? "Wydatki i wynagrodzenie dodatkowe, o które prosisz — i kto o nich decyduje."
              : "Nieobecności, raporty godzin i zgody do decyzji — w jednej liście."
          }
          density="compact"
        />
        {/* „Moje zgody” są w „Moim czasie” (przebudowa „Ludzi”, 22.10.2026). */}
        {mine ? null : <PeopleSectionNav config={config} active="approvals" />}
        {mine ? <MyConsentsScreen /> : <ApprovalsScreen config={config} />}
      </div>
    </HrHarnessShell>
  );
}
