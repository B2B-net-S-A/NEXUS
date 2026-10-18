// E-teczka — wiersze tabeli „Dokumenty” (makieta „Dokumenty osoby”, 17.10.2026).
//
// Jedna lista z dwóch źródeł: dokumenty e-teczki i protokoły sprzętu osoby
// (odnośniki z modułu sprzętu). Słowa stanu jak w makiecie: „dostarczone”,
// „podpisana przez generator”, „podpisany” — bez kolorów krzyczących.

import { formatIsoDatePl } from "@/lib/date-pl";
import {
  DOCUMENT_KIND_LABELS,
  audienceLabel,
  type PersonDocument,
  type PersonProtocol,
} from "@/lib/api/hr-documents";
import type { StatusDotTone } from "@/components/ds/StatusDot";

export interface DocumentRow {
  key: string;
  title: string;
  subline: string | null;
  kindLabel: string;
  status: string;
  /** Druga linia stanu (data, powód usunięcia). */
  statusNote: string | null;
  tone: StatusDotTone;
  validUntil: string;
  audience: string;
  muted: boolean;
  document: PersonDocument | null;
  protocol: PersonProtocol | null;
}

const PROTOCOL_STATUS: Record<PersonProtocol["status"], { label: string; tone: StatusDotTone }> = {
  oczekuje: { label: "czeka na podpis", tone: "warning" },
  podpisany: { label: "podpisany", tone: "success" },
  potwierdzony: { label: "potwierdzony", tone: "success" },
};

/** „Ważny do”: umowa bez daty jest bezterminowa, reszta bez daty — „—”. */
export function validUntilLabel(document: Pick<PersonDocument, "kind" | "valid_until">): string {
  if (document.valid_until) return formatIsoDatePl(document.valid_until);
  return document.kind === "contract" ? "bezterminowo" : "—";
}

export function documentStatus(document: PersonDocument): {
  label: string;
  note: string | null;
  tone: StatusDotTone;
} {
  if (document.deleted) {
    const why = document.deletion_reason === "retention" ? "po terminie" : "pomyłka";
    return {
      label: "usunięty",
      note: `${formatIsoDatePl(document.deleted_at ?? null)} · ${why}`,
      tone: "neutral",
    };
  }
  const day = formatIsoDatePl(document.created_at);
  if (document.source === "agreement") {
    const word = document.kind === "contract" ? "podpisana" : "podpisany";
    return { label: word, note: day, tone: "success" };
  }
  return { label: "dostarczone", note: day, tone: "neutral" };
}

export function documentSubline(document: PersonDocument): string | null {
  if (document.source === "agreement") return "z generatora umów NEXUSA";
  if (document.purpose === "student_status") return "status ucznia lub studenta — zasila kartotekę";
  const size = fileSizeLabel(document.size_bytes);
  return document.file_name ? `${document.file_name} · ${size}` : size;
}

export function documentRow(document: PersonDocument): DocumentRow {
  const status = documentStatus(document);
  return {
    key: `d${document.id}`,
    title: document.title,
    subline: documentSubline(document),
    kindLabel: DOCUMENT_KIND_LABELS[document.kind],
    status: status.label,
    statusNote: status.note,
    tone: status.tone,
    validUntil: document.deleted ? "—" : validUntilLabel(document),
    audience: audienceLabel(document.audience),
    muted: document.deleted,
    document,
    protocol: null,
  };
}

export function protocolRow(protocol: PersonProtocol): DocumentRow {
  const status = PROTOCOL_STATUS[protocol.status] ?? { label: protocol.status, tone: "neutral" };
  const what = protocol.kind === "zwrot" ? "Protokół zwrotu sprzętu" : "Protokół wydania sprzętu";
  return {
    key: `p${protocol.id}`,
    title: `${what} ${protocol.number}`,
    subline: `z modułu sprzętu · ${formatIsoDatePl(protocol.protocol_date)}`,
    kindLabel: DOCUMENT_KIND_LABELS.protocol,
    status: status.label,
    statusNote: protocol.signed_at ? formatIsoDatePl(protocol.signed_at) : null,
    tone: status.tone,
    validUntil: "—",
    audience: "osoba, Kadry, recepcja",
    muted: false,
    document: null,
    protocol,
  };
}

/** Dokumenty (najnowsze pierwsze, usunięte na końcu), potem protokoły sprzętu. */
export function documentRows(
  documents: PersonDocument[],
  protocols: PersonProtocol[] | null,
): DocumentRow[] {
  const live = documents.filter((row) => !row.deleted).map(documentRow);
  const deleted = documents.filter((row) => row.deleted).map(documentRow);
  return [...live, ...(protocols ?? []).map(protocolRow), ...deleted];
}

/** Rozmiar pliku po polsku: „840 KB”, „2,4 MB”. */
export function fileSizeLabel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}
