/**
 * Dane fikcyjne harnessu „Dokumenty osoby” (e-teczka, etap 5, E4) — z makiety
 * rekomendacji „NEXUS a eBI24” (17.10.2026). Osoby, tytuły i kwoty są zmyślone.
 */
import type {
  PersonDocument,
  PersonDocuments,
  PersonProtocol,
  RetentionDue,
  RetentionEntry,
} from "@/lib/api/hr-documents";

/** Osoba z makiety: zlecenie, recepcja. */
export const CELINA = { id: 120, name: "Celina Testowa", email: "celina.testowa@example.com" };

const SHA = "0".repeat(63);

function document(id: number, values: Partial<PersonDocument>): PersonDocument {
  return {
    id,
    user_id: CELINA.id,
    kind: "other",
    purpose: null,
    title: "Dokument",
    source: "upload",
    source_ref: null,
    file_name: null,
    mime: "application/pdf",
    size_bytes: 184_320,
    sha256: `${SHA}${id % 10}`,
    valid_until: null,
    audience: { person: true, payroll: true, equipment: false },
    added_by_name: "Paulina Kadrowa",
    created_at: "2026-02-28T10:15:00+01:00",
    deleted: false,
    ...values,
  };
}

export const CELINA_DOCUMENTS: PersonDocument[] = [
  document(7003, {
    kind: "statement",
    purpose: "student_status",
    title: "Oświadczenie studenta",
    file_name: "oswiadczenie-studenta.pdf",
    valid_until: "2027-06-30",
    created_at: "2026-10-02T09:00:00+02:00",
  }),
  document(7002, {
    kind: "annex",
    title: "Aneks: stawka 32,00 zł/h od 01.10",
    source: "agreement",
    source_ref: "hr_agreement:41",
    added_by_name: null,
    created_at: "2026-09-25T14:20:00+02:00",
  }),
  document(7001, {
    kind: "contract",
    title: "Umowa zlecenia z 01.03.2026",
    source: "agreement",
    source_ref: "hr_agreement:17",
    added_by_name: null,
  }),
];

export const CELINA_PROTOCOLS: PersonProtocol[] = [
  {
    id: 8801,
    number: "PZO/2026/10/004",
    kind: "wydanie",
    protocol_date: "2026-10-01",
    status: "podpisany",
    signed_at: "2026-10-01T12:00:00+02:00",
    has_signed_file: true,
  },
];

/** Kadry widzą też ślad usuniętej pomyłki. */
const REMOVED = document(7000, {
  kind: "certificate",
  title: "Zaświadczenie (wgrane do złej osoby)",
  file_name: null,
  audience: { person: true, payroll: true, equipment: false },
  deleted: true,
  deleted_at: "2026-10-03T08:30:00+02:00",
  deletion_reason: "mistake",
  deleted_by_name: "Paulina Kadrowa",
  created_at: "2026-10-03T08:10:00+02:00",
});

export function hrView(): PersonDocuments {
  return {
    user_id: CELINA.id,
    can_manage: true,
    documents: [...CELINA_DOCUMENTS, REMOVED],
    protocols: CELINA_PROTOCOLS,
  };
}

export function personView(): PersonDocuments {
  return {
    user_id: CELINA.id,
    can_manage: false,
    documents: CELINA_DOCUMENTS,
    protocols: CELINA_PROTOCOLS,
  };
}

/** Płace: tylko dokumenty ze znacznikiem Płac, bez protokołów sprzętu. */
export function payrollView(): PersonDocuments {
  return {
    user_id: CELINA.id,
    can_manage: false,
    documents: CELINA_DOCUMENTS.filter((row) => row.audience.payroll),
    protocols: null,
  };
}

export function emptyView(): PersonDocuments {
  return { user_id: CELINA.id, can_manage: true, documents: [], protocols: [] };
}

const RETENTION: RetentionEntry[] = [
  { kind: "contract", label: "umowa", years: 10, default_years: 10 },
  { kind: "annex", label: "aneks", years: 10, default_years: 10 },
  { kind: "statement", label: "oświadczenie", years: 10, default_years: 10 },
  { kind: "certificate", label: "zaświadczenie", years: 10, default_years: 10 },
  { kind: "protocol", label: "protokół", years: 10, default_years: 10 },
  { kind: "other", label: "inne", years: 5, default_years: 5 },
];

export function retentionDue(): RetentionDue {
  return {
    items: [
      {
        id: 6101,
        user_id: 131,
        person_name: "Borys Wzorcowy",
        kind: "other",
        title: "Notatka z rozmowy końcowej",
        source: "upload",
        created_at: "2019-11-20T10:00:00+01:00",
        last_day: "2020-01-31",
        delete_from: "2026-01-01",
      },
      {
        id: 6102,
        user_id: 132,
        person_name: "Anna Przykładowa",
        kind: "other",
        title: "Potwierdzenie odbioru karty",
        source: "upload",
        created_at: "2020-05-04T10:00:00+02:00",
        last_day: "2020-06-30",
        delete_from: "2026-01-01",
      },
    ],
    retention: RETENTION,
  };
}

export function retentionEmpty(): RetentionDue {
  return { items: [], retention: RETENTION };
}
