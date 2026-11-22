// Zakładka „Start i sprzęt” kontraktu (wariant A, 20.11.2026) — czyste
// reguły nagłówka postępu i „Formalności”, bez Reacta, z testami.
//
// Lista startowa ma dwa źródła: lista wejścia z modułu „Wejście i odejście”
// (`/api/hr/lifecycle/contracts/{id}/entry`) albo — przy wyłączonym module —
// stara lista onboardingu kontraktu (`/api/contracts/{id}/onboarding`).
// Nagłówek liczy postęp z tej, która obowiązuje.

import type { LifecycleTask } from "@/lib/api/hr-lifecycle";
import type { ClientStartDocsList, PairStartDocs } from "@/lib/api/start-documents";
import type { ContractDocument } from "@/lib/contract-document-folders";
import { formatIsoDatePl } from "@/lib/date-pl";
import { pluralPl } from "@/lib/plural-pl";
import { warsawDateOf } from "@/lib/warsaw-date";

export type StartListSource = "entry" | "legacy";

/**
 * Która lista obowiązuje — ta sama reguła co `ContractEntryTab`: brak modułu
 * (404) albo `module_on: false` to stara lista; `null` — jeszcze nie wiadomo.
 */
export function startListSource(entry: {
  notFound: boolean;
  view: { module_on: boolean } | null | undefined;
}): StartListSource | null {
  if (entry.notFound) return "legacy";
  if (!entry.view) return null;
  return entry.view.module_on ? "entry" : "legacy";
}

export interface StartProgress {
  done: number;
  total: number;
  /** Dzień założenia listy (kalendarz firmy), gdy wiadomo. */
  createdOn: string | null;
}

/** Lista wejścia: zrobione albo pominięte zamyka pozycję (jak kroki nad listą). */
export function entryProgress(tasks: readonly Pick<LifecycleTask, "status">[], startedAt: string | null): StartProgress {
  return {
    done: tasks.filter((task) => task.status !== "open").length,
    total: tasks.length,
    createdOn: warsawDateOf(startedAt),
  };
}

export interface LegacyItem {
  status: "pending" | "done" | "na";
  created_at: string;
}

/** Stara lista: „nie dotyczy” nie liczy się do kroków (jak dotąd pasek postępu). */
export function legacyProgress(items: readonly LegacyItem[]): StartProgress {
  const counted = items.filter((item) => item.status !== "na");
  const first = items.map((item) => item.created_at).sort()[0] ?? null;
  return {
    done: counted.filter((item) => item.status === "done").length,
    total: counted.length,
    createdOn: warsawDateOf(first),
  };
}

/** „0 z 8 kroków”, „1 z 1 kroku” — dopełniacz po „z”. */
export function ofSteps(done: number, total: number): string {
  return `${done} z ${total} ${total === 1 ? "kroku" : "kroków"}`;
}

export function percentOf(progress: Pick<StartProgress, "done" | "total">): number {
  return progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
}

function dayNumber(iso: string): number {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86_400_000;
}

/** „dziś”, „jutro”, „za 11 dni”, „wczoraj”, „5 dni temu” — liczone w dniach kalendarza. */
export function relativeDayPl(iso: string, today: string): string {
  const days = dayNumber(iso) - dayNumber(today);
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  if (days === -1) return "wczoraj";
  const n = Math.abs(days);
  return days > 0 ? `za ${n} ${pluralPl(n, "dzień", "dni", "dni")}` : `${n} ${pluralPl(n, "dzień", "dni", "dni")} temu`;
}

/** Podtytuł nagłówka: kiedy start i co z listą („nic jeszcze nie odhaczono”). */
export function startSubtitle({
  startDate,
  today,
  progress,
}: {
  startDate: string | null;
  today: string;
  progress: StartProgress | null;
}): string {
  const started = startDate != null && startDate <= today;
  const when = !startDate
    ? "Kontrakt bez daty startu"
    : started
      ? `Współpraca od ${formatIsoDatePl(startDate)}`
      : `Start ${formatIsoDatePl(startDate)} (${relativeDayPl(startDate, today)})`;
  if (!progress || progress.total === 0) {
    return `${when} · ${started ? "listy startowej nie założono" : "listy startowej jeszcze nie ma"}`;
  }
  return [
    when,
    progress.createdOn ? `lista założona ${formatIsoDatePl(progress.createdOn)}` : null,
    progress.done === 0 ? "nic jeszcze nie odhaczono" : progress.done >= progress.total ? "wszystko odhaczone" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Najnowsza umowa w dokumentach kontraktu (`doc_type: contract`). */
export function agreementDocument(docs: readonly ContractDocument[] | null | undefined): ContractDocument | null {
  const agreements = (docs ?? []).filter((doc) => doc.doc_type === "contract");
  return agreements.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
}

export type CheckState = "ok" | "check" | "missing";

export interface CheckView {
  state: CheckState;
  detail: string;
  /** Dokąd prowadzi link przy wierszu. */
  target: "documents" | "client";
}

/**
 * „Dokumenty do startu” pary osoba–rekrutacja (lista klienta, `start-documents`).
 * Bez listy u klienta para jest `null` — wtedy liczy się decyzja klienta
 * („Klient nie wymaga dokumentów”, 0747) albo jej brak.
 */
export function startDocsCheck({
  hasJob,
  pair,
  clientList,
  today,
}: {
  hasJob: boolean;
  pair: PairStartDocs | null | undefined;
  clientList: Pick<ClientStartDocsList, "items" | "not_required"> | null | undefined;
  today: string;
}): CheckView {
  if (!hasJob) {
    return {
      state: "check",
      detail: "Kontrakt bez rekrutacji — dokumenty do startu prowadzi się przy parze osoba–rekrutacja, więc stanu nie da się odczytać.",
      target: "client",
    };
  }
  if (pair) {
    if (pair.total === 0) {
      return { state: "ok", detail: "Nic z listy klienta nie dotyczy tej osoby.", target: "documents" };
    }
    if (pair.done >= pair.total) {
      return { state: "ok", detail: `Komplet: ${pair.done} z ${pair.total} z listy klienta.`, target: "documents" };
    }
    const missing = pair.items
      .filter((item) => item.state === "missing" || item.state === "returned")
      .map((item) => item.name);
    const late = pair.deadline != null && pair.deadline < today;
    return {
      state: late ? "missing" : "check",
      detail: [
        missing.length ? `Brakuje: ${missing.join(", ")}` : null,
        `${pair.done} z ${pair.total} gotowe`,
        pair.deadline ? `${late ? "termin minął" : "termin"} ${formatIsoDatePl(pair.deadline)}` : null,
      ]
        .filter(Boolean)
        .join(" · ")
        .concat("."),
      target: "documents",
    };
  }
  if (clientList?.not_required) {
    return {
      state: "ok",
      detail: `Klient nie wymaga dokumentów do startu (zaznaczono ${formatIsoDatePl(warsawDateOf(clientList.not_required.at))}).`,
      target: "client",
    };
  }
  return {
    state: "check",
    detail: "Klient nie ma w NEXUSIE listy dokumentów do startu, więc nie wiadomo, czego wymaga.",
    target: "client",
  };
}
