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
import { stageCvStatus, type StageBrandedSummary } from "@/lib/cv-to-client";
import { formatDate } from "@/lib/utils";

export interface DockSnapshotInput {
  has_snapshot: boolean;
  original_snapshot_at?: string | null;
  original_cv_filename?: string | null;
}

export interface DockProfileCvDoc {
  id: number;
  filename: string;
  is_primary: boolean;
  uploaded_at: string | null;
  created_at: string;
}

export type DockOriginalCv =
  | { kind: "loading" }
  | { kind: "snapshot"; date: string | null; filename: string | null }
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
    case "snapshot":
      return `Oryginał CV: dołączony do zgłoszenia${state.date ? ` · ${formatDate(state.date)}` : ""}`;
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

export function companyCvSentence(
  branded: DockBrandedInput | null | undefined,
  opts: { pairHasCompanyCv?: boolean | null } = {},
): {
  text: string;
  tone: "success" | "info" | "neutral" | "warning";
} {
  const status = stageCvStatus(branded);
  if (status === "none") {
    // Etap nie ma własnego CV (brak wiersza → 404 albo stan „none”), a para
    // ma CV firmowe gdzie indziej — ramka „Następny etap” pokazuje wtedy ✓,
    // więc „brak” byłby sprzecznością na jednym ekranie.
    if (opts.pairHasCompanyCv) {
      return { text: "CV firmowe: gotowe (nie podpięte do tego etapu)", tone: "success" };
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
