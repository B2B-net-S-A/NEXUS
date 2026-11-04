/**
 * Sekcja „CV” w doku osoby na Tablicy — dwa różne dokumenty, dwa zdania.
 *
 * Do 24.09.2026 dok pokazywał plakietkę „Brak CV w momencie zgłoszenia”
 * (etap nie ma kopii CV z chwili dodania — `GET …/cv/original` →
 * `has_snapshot: false`) i tuż pod nią przycisk „Pokaż CV oryginalne”, który
 * otwierał okno z tym samym „brakiem”. Tymczasem CV zwykle leży w profilu
 * kandydata — tylko nie zostało skopiowane do zgłoszenia. Czyste funkcje
 * niżej rozróżniają:
 *  - CV firmowe (CV etapu z generatora): brak / szkic / zatwierdzone + data,
 *  - oryginał: kopia ze zgłoszenia / plik z profilu / naprawdę brak pliku.
 *
 * „Brak pliku” pada wyłącznie wtedy, gdy WIEMY, że profil nie ma CV
 * (lista dokumentów wczytana i pusta) — nieudany odczyt to nie brak.
 */

import type { MoveRequirementItem } from "@/lib/api/moveRequirements";
import { isClientCvFilename } from "@/lib/candidate-files";
import { stageCvStatus, type StageBrandedSummary, type StageGeneratedCvRow } from "@/lib/cv-to-client";
import { formatDate } from "@/lib/utils";

export interface DockSnapshotInput {
  has_snapshot: boolean;
  original_snapshot_at?: string | null;
  original_cv_filename?: string | null;
  /**
   * `manual_upload` = wgrane z rekrutacji, `manual_refresh` = podmienione z profilu,
   * `quarantine_restore` = wróciło CV osoby, bo wgrane było CV kogoś innego,
   * `client_cv_repair` = jednorazowa naprawa 15.10.2026: kopia trzymała CV do
   * klienta („B2B_…”), wróciła do CV kandydata z profilu,
   * `contract_repair` = jednorazowa naprawa 30.10.2026: to samo dla kopii umowy.
   */
  original_snapshot_source?: string | null;
}

export interface DockProfileCvDoc {
  id: number;
  filename: string;
  is_primary: boolean;
  uploaded_at: string | null;
  created_at: string;
  /** Plik oznaczony jako nieaktualny — serwer nie bierze go jako bieżącego CV. */
  outdated_at?: string | null;
}

export type DockOriginalCv =
  | { kind: "loading" }
  | { kind: "snapshot"; date: string | null; filename: string | null; source: string | null }
  | { kind: "profile"; date: string | null; doc: DockProfileCvDoc }
  | { kind: "none" }
  /** Etap bez kopii, a profilu nie udało się sprawdzić. */
  | { kind: "unknown" };

/** Główne CV profilu — ta sama kolejność co karta CV na profilu kandydata. */
export function primaryProfileCv<T extends DockProfileCvDoc>(
  docs: readonly T[],
  cvFilename?: string | null,
): T | null {
  return (
    docs.find((d) => d.is_primary) ??
    (cvFilename ? docs.find((d) => d.filename === cvFilename) : undefined) ??
    docs[0] ??
    null
  );
}

export function dockOriginalCv(input: {
  snapshot: DockSnapshotInput | null | undefined;
  snapshotLoading: boolean;
  /** `undefined` = nie wczytano (w toku albo błąd — patrz `profileDocsFailed`). */
  profileDocs: readonly DockProfileCvDoc[] | undefined;
  profileDocsFailed: boolean;
  cvFilename?: string | null;
}): DockOriginalCv {
  if (input.snapshot?.has_snapshot) {
    return {
      kind: "snapshot",
      date: input.snapshot.original_snapshot_at ?? null,
      filename: input.snapshot.original_cv_filename ?? null,
      source: input.snapshot.original_snapshot_source ?? null,
    };
  }
  if (input.snapshotLoading) return { kind: "loading" };
  if (input.profileDocs) {
    const doc = primaryProfileCv(input.profileDocs, input.cvFilename);
    if (doc) return { kind: "profile", date: doc.uploaded_at ?? doc.created_at ?? null, doc };
    return { kind: "none" };
  }
  if (input.profileDocsFailed) return { kind: "unknown" };
  return { kind: "loading" };
}

export function originalCvSentence(state: DockOriginalCv): string {
  switch (state.kind) {
    case "loading":
      return "Oryginał CV: sprawdzamy…";
    case "snapshot": {
      const when = state.date ? ` · ${formatDate(state.date)}` : "";
      if (state.source === "manual_upload") {
        return `Oryginał CV: wgrane w rekrutacji${state.filename ? ` · ${state.filename}` : ""}${when}`;
      }
      if (state.source === "manual_refresh") {
        return `Oryginał CV: z profilu${state.filename ? ` · ${state.filename}` : ""} · podmienione${state.date ? ` ${formatDate(state.date)}` : ""}`;
      }
      if (state.source === "client_cv_repair" || state.source === "contract_repair") {
        // Naprawy 15.10 i 30.10.2026: kopia trzymała CV do klienta albo umowę,
        // wróciła do CV kandydata.
        return `Oryginał CV: z profilu${state.filename ? ` · ${state.filename}` : ""}${when}`;
      }
      if (state.source === "quarantine_restore") {
        // Bramka tożsamości: wgrane CV nie pasowało do osoby, kopia wróciła do jej CV.
        return `Oryginał CV: poprzednie CV${state.filename ? ` · ${state.filename}` : ""} — wgrane nie pasowało do tej osoby`;
      }
      return `Oryginał CV: dołączony do zgłoszenia${when}`;
    }
    case "profile":
      return `Oryginał CV: z profilu${state.date ? ` (${formatDate(state.date)})` : ""} — do zgłoszenia nie dołączono pliku`;
    case "none":
      return "Oryginał CV: brak pliku — ani w zgłoszeniu, ani w profilu kandydata";
    case "unknown":
      return "Oryginał CV: do zgłoszenia nie dołączono pliku (nie udało się sprawdzić profilu)";
  }
}

export interface DockBrandedInput extends StageBrandedSummary {
  updated_at?: string | null;
  finalized_at?: string | null;
}

/**
 * Czy PARA (kandydat × rekrutacja) ma CV firmowe — z listy `move-requirements`
 * (pozycja `company_cv`, reguła `company_cv_refs`: CV etapu, gotowe CV
 * z generatora albo plik „…B2B…”). `null` = lista tego nie mówi.
 */
export function pairCompanyCv(
  items: readonly MoveRequirementItem[] | null | undefined,
): boolean | null {
  const item = items?.find((i) => i.key === "company_cv");
  if (!item) return null;
  return item.status === "ok";
}

/**
 * Zdanie o CV firmowym PARY (osoba × rekrutacja). `branded` to stan CV z
 * wiersza, na którym CV leży — bieżącego albo wskazanego przez serwer
 * (`pair_source_stage_id`, `useStageBrandedCv`). Do 14.10.2026 CV z
 * poprzedniego etapu dostawało dopisek „…z etapu X, nie podpięte do
 * bieżącego etapu”, który Delivery Lead czytał jak „tu nie ma CV” (D2).
 */
export function companyCvSentence(
  branded: DockBrandedInput | null | undefined,
  opts: { pairHasCompanyCv?: boolean | null } = {},
): {
  text: string;
  tone: "success" | "info" | "neutral" | "warning";
} {
  const status = stageCvStatus(branded);
  if (status === "none") {
    // Para nie ma CV etapu, ale lista wymagań liczy CV firmowe z plików
    // kandydata (gotowe CV z generatora albo plik „…B2B…”) — ramka „Następny
    // etap” pokazuje wtedy ✓, więc „brak” byłby sprzecznością na jednym ekranie.
    if (opts.pairHasCompanyCv) {
      return { text: "CV firmowe: gotowe (w plikach kandydata)", tone: "success" };
    }
    return { text: "CV firmowe: brak", tone: "warning" };
  }
  if (status === "legacy") {
    return { text: "CV firmowe: stary szablon (tylko podgląd)", tone: "neutral" };
  }
  if (branded?.status === "finalized") {
    const when = branded.finalized_at ?? branded.updated_at ?? null;
    return { text: `CV firmowe: zatwierdzone${when ? ` ${formatDate(when)}` : ""}`, tone: "success" };
  }
  const when = branded?.updated_at ?? null;
  return { text: `CV firmowe: szkic${when ? ` · zmienione ${formatDate(when)}` : ""}`, tone: "info" };
}

/** Kopię z uploadu zapisujemy po dokumencie — margines na zegar i kolejność zapisów. */
const NEWER_MARGIN_MS = 60_000;

/**
 * Plik, który serwer skopiuje jako CV rekrutacji (`get_current_cv`): tylko
 * PDF, DOC i DOCX, najpierw główne, potem najnowsze. Główne CV w TXT czy ODT
 * nie trafia do kopii — przegląd kodu 13.10.2026: ramka obiecywała plik,
 * którego „Użyj w tej rekrutacji” nie kopiowało. Plik „nieaktualny” też nie
 * (`cv_source.current_cv_filters`, audyt 13.10.2026).
 */
export function stageCopySource<T extends DockProfileCvDoc>(docs: readonly T[]): T | null {
  const usable = docs.filter((d) => /\.(pdf|docx?)$/i.test(d.filename) && !d.outdated_at);
  const at = (d: T) => Date.parse(d.uploaded_at ?? d.created_at) || 0;
  return [...usable].sort((a, b) => Number(b.is_primary) - Number(a.is_primary) || at(b) - at(a))[0] ?? null;
}

/**
 * Pliki CV z profilu bez pliku z kwarantanny tożsamości (CV innej osoby —
 * znacznik `_identity_quarantine_source` w `cv_extracted_data`). Audyt
 * 13.10.2026, pkt 8: kopia etapu jest po kwarantannie pusta, a dok sięgał
 * wtedy po najnowszy plik z profilu, czyli właśnie cudze CV. Plik, który ktoś
 * po zwolnieniu znów ustawił jako główne, zostaje. Znacznik wskazuje ostatni
 * plik z kwarantanny. Dok i podgląd CV po „Rozwiń” stosują tę samą regułę.
 */
export function withoutQuarantinedCv<T extends { id: number; is_primary: boolean }>(
  docs: readonly T[] | undefined,
  extracted: unknown,
): readonly T[] | undefined {
  const marker =
    extracted && typeof extracted === "object"
      ? (extracted as { _identity_quarantine_source?: { kind?: unknown; id?: unknown } })
          ._identity_quarantine_source
      : undefined;
  if (!docs || marker?.kind !== "document" || typeof marker.id !== "number") return docs;
  return docs.filter((doc) => doc.id !== marker.id || doc.is_primary);
}

/**
 * CV z profilu nowsze niż kopia CV tej rekrutacji (D4, 13.10.2026): CV wpadło
 * mailem albo ktoś wgrał je w profilu lub w innej rekrutacji osoby. Liczy się
 * plik, który „Użyj w tej rekrutacji” naprawdę skopiuje (`stageCopySource`).
 * Po wgraniu z tej rekrutacji kopia powstaje po dokumencie, więc ramka się
 * nie pokazuje. `null` = nie ma nowszego albo nie da się porównać.
 *
 * CV do klienta („B2B_…”) nie jest nowszym CV kandydata (15.10.2026): wgrane
 * z kafelka zostaje w profilu obok głównego CV, a u osoby bez wskazanego
 * głównego CV (stare importy) byłoby najnowszym plikiem — ramka namawiałaby
 * wtedy do zrobienia z niego oryginału.
 */
export function newerProfileCv<T extends DockProfileCvDoc>(
  original: DockOriginalCv,
  docs: readonly T[] | undefined,
): T | null {
  if (original.kind !== "snapshot" || !original.date || !docs) return null;
  const primary = stageCopySource(docs);
  if (!primary || isClientCvFilename(primary.filename)) return null;
  const primaryAt = Date.parse(primary.uploaded_at ?? primary.created_at);
  const snapshotAt = Date.parse(original.date);
  if (!Number.isFinite(primaryAt) || !Number.isFinite(snapshotAt)) return null;
  return primaryAt - snapshotAt >= NEWER_MARGIN_MS ? primary : null;
}

/**
 * Od kiedy jest obecny szkic CV firmowego: dokument generatora → wybór
 * gotowego CV (kopia, plik Word) → ostatnia zmiana. `updated_at` rośnie przy
 * każdej poprawce, więc jest tylko zapasem.
 */
export function companyDraftSince(
  branded: (StageBrandedSummary & { updated_at?: string | null }) | null | undefined,
  rows: readonly Pick<StageGeneratedCvRow, "id" | "created_at">[] | undefined,
): string | null {
  if (!branded) return null;
  const attached = branded.generated_document_id;
  if (attached != null) {
    const row = rows?.find((r) => r.id === attached);
    if (row?.created_at) return row.created_at;
  }
  return branded.origin?.selected_at ?? branded.updated_at ?? null;
}

/**
 * Szkic CV firmowego starszy niż CV podmienione w tej rekrutacji (D3) —
 * powstał z poprzedniego pliku. Tylko szkic: zatwierdzonego CV i wysłanych
 * linków nowe CV nie zmienia. Tylko kopia podmieniona ręcznie (upload albo
 * „Użyj w tej rekrutacji”): kopia z chwili zgłoszenia jest z definicji źródłem
 * szkicu. Naprawa `client_cv_repair` też nie — nikt nie wgrał nowego CV,
 * kopia tylko przestała być plikiem „B2B_…”.
 */
export function companyCvStale(input: {
  brandedStatus: string | null | undefined;
  original: DockOriginalCv;
  draftSince: string | null;
}): boolean {
  const { brandedStatus, original, draftSince } = input;
  if (brandedStatus !== "draft" || original.kind !== "snapshot") return false;
  if (original.source !== "manual_upload" && original.source !== "manual_refresh") return false;
  if (!original.date || !draftSince) return false;
  return Date.parse(original.date) > Date.parse(draftSince);
}
