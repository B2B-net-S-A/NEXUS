// Zdarzenia kontraktu (`/api/contracts/{id}/activities`) po ludzku — zamiast
// „via sharepoint_import / doc type annex / size bytes” i surowego JSON-a.
// Formy bezosobowe („Dodano”, „Zmieniono”), bo nie znamy płci autora.
import type { MkActivity } from "./data";
import { fmtDate, fmtNum, personFromEmail } from "./format";

export type ActivityKind = "people" | "money" | "documents" | "system";

export interface HumanActivity {
  id: number;
  at: string;
  who: string;
  /** Zdarzenie z migracji / synchronizacji, nie z ręki człowieka. */
  automatic: boolean;
  kind: ActivityKind;
  title: string;
  detail?: string;
}

const DOC_TYPE: Record<string, string> = {
  contract: "umowa",
  annex: "aneks",
  order: "zamówienie",
  nda: "NDA",
  other: "inny",
};

const FIELD_LABEL: Record<string, string> = {
  rate_client: "stawka klienta",
  rate_candidate: "stawka kandydata",
  end_date: "koniec projektu",
  start_date: "start",
  status: "status",
  line_manager: "line manager",
  work_mode: "tryb pracy",
  team_name: "zespół",
  project_name: "projekt",
};

function num(v: unknown): string {
  return typeof v === "number" ? fmtNum(v) : String(v ?? "—");
}

function val(key: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (key.endsWith("_date") && typeof v === "string") return fmtDate(v);
  if (key.startsWith("rate_")) return num(v);
  return String(v);
}

/** „stawka klienta 175,00 → 163,00 · stawka kandydata 135,00 → 125,00”. */
export function diffLine(oldV: Record<string, unknown> | undefined, newV: Record<string, unknown> | undefined): string {
  if (!newV) return "";
  return Object.entries(newV)
    .filter(([k, v]) => FIELD_LABEL[k] && oldV?.[k] !== v)
    .map(([k, v]) => `${FIELD_LABEL[k]} ${val(k, oldV?.[k])} → ${val(k, v)}`)
    .join(" · ");
}

export function humanizeActivity(a: MkActivity): HumanActivity {
  const d = (a.details ?? {}) as Record<string, unknown>;
  const source = typeof d.source === "string" ? d.source : "";
  const automatic = !a.user_name || /^\d{4}_/.test(source) || source.includes("backfill") || source.includes("sync");
  const who = a.user_name ? personFromEmail(a.user_name) : "NEXUS";
  const base = { id: a.id, at: a.created_at, who, automatic };

  switch (a.action) {
    case "document_uploaded": {
      const type = DOC_TYPE[String(d.doc_type ?? "")] ?? "dokument";
      const fromSp = d.via === "sharepoint_import";
      return {
        ...base,
        kind: "documents",
        title: `Dodano dokument (${type}) „${String(d.filename ?? "")}”`,
        detail: fromSp ? "z SharePointa" : undefined,
      };
    }
    case "document_deleted":
      return { ...base, kind: "documents", title: `Usunięto dokument „${String(d.filename ?? "")}”` };
    case "amendment_rate_change":
      return {
        ...base,
        kind: "money",
        title: "Aneks: zmiana stawek",
        detail: [
          diffLine(d.old as Record<string, unknown>, d.new as Record<string, unknown>),
          d.effective_date ? `od ${fmtDate(String(d.effective_date))}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "amendment_extension":
      return {
        ...base,
        kind: "money",
        title: "Aneks: przedłużenie",
        detail: diffLine(d.old as Record<string, unknown>, d.new as Record<string, unknown>),
      };
    case "synced_with_orders":
      return {
        ...base,
        automatic: true,
        kind: "system",
        title: "Okres zamówienia uzupełniony z zamówień klienta",
        detail: d.client_order_end_date
          ? `zamówienie ${fmtDate(String(d.client_order_start_date ?? ""))} – ${fmtDate(String(d.client_order_end_date))}`
          : undefined,
      };
    case "end_date_cleared":
      return {
        ...base,
        automatic: true,
        kind: "system",
        title: "Umowa oznaczona jako bezterminowa",
        detail: d.previous_end_date ? `wcześniej koniec ${fmtDate(String(d.previous_end_date))}` : undefined,
      };
    case "start_date_corrected":
      return {
        ...base,
        automatic: true,
        kind: "system",
        title: "Poprawiono datę startu",
        detail: `${fmtDate(String(d.previous_start_date ?? ""))} → ${fmtDate(String(d.start_date ?? ""))}`,
      };
    case "rate_unit_converted_to_hourly":
      return { ...base, automatic: true, kind: "system", title: "Stawki przeliczone na godzinowe" };
    case "terminated":
      return {
        ...base,
        kind: "people",
        title: "Zapisano zakończenie współpracy",
        detail: d.terminated_at ? `koniec ${fmtDate(String(d.terminated_at))}` : undefined,
      };
    case "contract_activated":
      return { ...base, kind: "people", title: "Kontrakt aktywowany" };
    case "contract_reopened":
      return { ...base, kind: "people", title: "Kontrakt wznowiony" };
    case "created":
      return { ...base, kind: "people", title: "Utworzono kontrakt" };
    case "updated":
      return {
        ...base,
        kind: "people",
        title: "Zmieniono dane kontraktu",
        detail: d.old && d.new ? diffLine(d.old as Record<string, unknown>, d.new as Record<string, unknown>) : undefined,
      };
    default:
      return { ...base, kind: "system", title: a.action.replace(/_/g, " ") };
  }
}
