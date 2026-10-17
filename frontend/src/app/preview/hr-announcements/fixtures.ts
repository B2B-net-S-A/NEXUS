/**
 * Dane harnessu „Opieka → Komunikaty” (makiety M7–M8, O12). Osoby, klienci
 * i adresy są ZMYŚLONE (`hr-fixtures.ts`, strażnik `harness-fictional-data`).
 */

import type {
  AnnouncementDetail,
  AnnouncementList,
  AnnouncementRecipient,
  AnnouncementRow,
  AnnouncementSettings,
  Audience,
  AudienceOptions,
  AudiencePreview,
  RecipientCounts,
} from "@/lib/api/care-announcements";

import { HR_CAST, HR_CLIENTS, HR_CONSULTANTS } from "../hr-fixtures";

export const AUTHOR = HR_CAST.natalia;
export const HEAD = { ...HR_CAST.adam, name: "Adam Wzorcowy" };
export const PENDING_ID = 4103;
export const SENT_ID = 4102;
export const CLIENT_SENT_ID = 4101;
export const DRAFT_ID = 4104;

function counts(overrides: Partial<RecipientCounts> = {}): RecipientCounts {
  return {
    pending: 0,
    sending: 0,
    sent: 0,
    failed: 0,
    uncertain: 0,
    bounced: 0,
    excluded_no_email: 0,
    excluded_opted_out: 0,
    cancelled: 0,
    unsubscribed: 0,
    ...overrides,
  };
}

export function settings(overrides: Partial<AnnouncementSettings> = {}): AnnouncementSettings {
  return {
    sending_enabled: true,
    transport: "simulate",
    sender: "administracja@example.com",
    approval_threshold: 20,
    rate_per_minute: 30,
    ...overrides,
  };
}

function row(overrides: Partial<AnnouncementRow> & { id: number }): AnnouncementRow {
  return {
    marker: `[Komunikat ${overrides.id}/7F2A]`,
    kind: "mandatory",
    status: "sent",
    subject: "Komunikat",
    author: { id: AUTHOR.id, name: AUTHOR.name },
    audience: { group: "all" },
    audience_label: "wszyscy aktywni konsultanci",
    recipient_count: 0,
    requires_approval: false,
    approver: null,
    created_at: "2026-10-10T08:40:00+00:00",
    submitted_at: "2026-10-10T08:55:00+00:00",
    approved_at: null,
    queued_at: "2026-10-10T09:02:00+00:00",
    send_started_at: "2026-10-10T09:05:00+00:00",
    send_finished_at: "2026-10-10T09:09:00+00:00",
    cancelled_at: null,
    counts: counts(),
    replies: { reply: 0, bounce: 0 },
    can_approve: false,
    ...overrides,
  };
}

export function rows(viewer: "head" | "author"): AnnouncementRow[] {
  const items = [
    row({
      id: PENDING_ID,
      status: "pending",
      subject: "Od listopada faktury do 5. dnia miesiąca",
      recipient_count: 124,
      requires_approval: true,
      queued_at: null,
      send_started_at: null,
      send_finished_at: null,
      counts: counts({ pending: 124, excluded_no_email: 2 }),
      can_approve: viewer === "head",
    }),
    row({
      id: SENT_ID,
      kind: "informational",
      subject: "Spotkanie konsultantów 28.11",
      author: { id: HR_CAST.julia.id, name: HR_CAST.julia.name },
      recipient_count: 119,
      requires_approval: true,
      approver: { id: HEAD.id, name: HEAD.name },
      approved_at: "2026-10-10T09:02:00+00:00",
      counts: counts({ sent: 117, bounced: 2, excluded_opted_out: 5, unsubscribed: 1 }),
      replies: { reply: 23, bounce: 2 },
    }),
    row({
      id: CLIENT_SENT_ID,
      subject: "Nowe zasady wejścia do biura klienta",
      author: { id: HR_CAST.kamil.id, name: HR_CAST.kamil.name },
      audience: { group: "client", client_ids: [HR_CLIENTS.bank.id] },
      audience_label: `klient: ${HR_CLIENTS.bank.name}`,
      recipient_count: 14,
      created_at: "2026-10-02T08:40:00+00:00",
      send_started_at: "2026-10-02T10:00:00+00:00",
      send_finished_at: "2026-10-02T10:01:00+00:00",
      counts: counts({ sent: 14 }),
      replies: { reply: 3, bounce: 0 },
    }),
  ];
  return viewer === "head"
    ? items
    : [
        row({
          id: DRAFT_ID,
          status: "draft",
          subject: "Ankieta o sprzęcie od klienta",
          queued_at: null,
          send_started_at: null,
          send_finished_at: null,
          submitted_at: null,
        }),
        items[0],
      ];
}

export function list(
  viewer: "head" | "author",
  overrides: Partial<AnnouncementSettings> = {},
): AnnouncementList {
  const user = viewer === "head" ? HEAD : AUTHOR;
  return {
    items: rows(viewer),
    me: { user_id: user.id, can_author: true, can_approve: viewer === "head", is_admin: false },
    settings: settings(overrides),
  };
}

const PEOPLE = [
  { ...HR_CONSULTANTS.michal, client: HR_CLIENTS.bank.name },
  { ...HR_CONSULTANTS.karolina, client: HR_CLIENTS.bank.name },
  { ...HR_CONSULTANTS.bartosz, client: HR_CLIENTS.telecom.name },
  { ...HR_CONSULTANTS.anna, client: HR_CLIENTS.clinic.name },
  { ...HR_CONSULTANTS.pawel, client: HR_CLIENTS.insurance.name },
];

function recipients(status: AnnouncementRecipient["status"]): AnnouncementRecipient[] {
  return PEOPLE.map((person, index) => ({
    candidate_id: person.id,
    contract_id: 8100 + index,
    client_id: null,
    client_name: person.client,
    name: person.name,
    email: index === 4 ? null : person.email,
    owner_name: AUTHOR.name,
    status: index === 4 ? "excluded_no_email" : status,
    simulated: status === "sent",
  }));
}

export function detail(id: number, viewer: "head" | "author"): AnnouncementDetail {
  const base = rows(viewer).find((entry) => entry.id === id) ?? rows("head")[0];
  const sent = base.status === "sent";
  return {
    ...base,
    body: "Cześć {imię},\n\nod faktur za listopad prosimy o przesyłanie ich do 5. dnia kolejnego miesiąca. Raport godzin bez zmian.\n\nW razie pytań odpisz na tę wiadomość albo napisz do swojej opiekunki lub opiekuna: {opiekun}.",
    content_version: 2,
    tested_at: "2026-10-17T13:42:00+00:00",
    test_current: true,
    return_note: null,
    submitted_by: base.author,
    recipients: base.status === "draft" ? [] : recipients(sent ? "sent" : "pending"),
    reply_cases: sent
      ? [
          { case_id: 5201, kind: "reply", title: "RE: Spotkanie konsultantów 28.11", case_status: "new", created_at: "2026-10-10T11:30:00+00:00" },
          { case_id: 5202, kind: "reply", title: "Odp: Spotkanie — czy będzie online?", case_status: "done", created_at: "2026-10-10T12:10:00+00:00" },
        ]
      : [],
    can_edit: base.status === "draft" && viewer === "author",
    can_test: base.status === "draft" && viewer === "author",
    can_submit: base.status === "draft" && viewer === "author",
    can_cancel: ["draft", "pending", "queued"].includes(base.status),
  };
}

export function options(): AudienceOptions {
  return {
    clients: Object.values(HR_CLIENTS).map((client, index) => ({
      id: client.id,
      name: client.name,
      consultants: [42, 31, 27, 26][index] ?? 1,
    })),
    owners: [
      { id: AUTHOR.id, name: AUTHOR.name, consultants: 64 },
      { id: HR_CAST.julia.id, name: HR_CAST.julia.name, consultants: 62 },
    ],
    forms: [
      { value: "b2b", label: "B2B", consultants: 118 },
      { value: "uop", label: "UoP", consultants: 3 },
      { value: "zlecenie", label: "Zlecenie", consultants: 5 },
    ],
    consultants: PEOPLE.map((person) => ({
      candidate_id: person.id,
      name: person.name,
      client_name: person.client,
    })),
    total: 126,
  };
}

/** Podgląd odbiorców grupy „wszyscy” (M7: 126 w grupie, 2 bez adresu, 124 dostanie). */
export function preview(audience: Audience = { group: "all" }): AudiencePreview {
  const small = audience.group !== "all";
  const rowsFor = recipients("pending").map((entry) => ({
    ...entry,
    form: "b2b" as const,
    end_date: null,
  }));
  return small
    ? {
        total: 5,
        will_receive: 4,
        excluded_no_email: 1,
        excluded_opted_out: 0,
        requires_approval: false,
        rows: rowsFor,
      }
    : {
        total: 126,
        will_receive: 124,
        excluded_no_email: 2,
        excluded_opted_out: 0,
        requires_approval: true,
        rows: rowsFor,
      };
}
