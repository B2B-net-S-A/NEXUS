/**
 * CV po potwierdzeniu (21.10.2026, zgłoszenie zespołu, decyzja Artura).
 *
 * Ruch na „Zweryfikowany” nie generuje już CV. Rekruter potwierdza w karcie
 * „CV do klienta” trzy rzeczy — plik CV, odpowiedzi ze screeningu i dodatkowe
 * notatki do CV — w dowolnej kolejności; „Generuj” odblokowuje się po trzech.
 * Zmiana pliku albo treści notatki po potwierdzeniu zdejmuje potwierdzenie,
 * bo generacja dostałaby co innego niż to, co rekruter widział.
 *
 * Tu tylko czyste reguły i zdania; panel `CvGeneratePanel` je rysuje.
 */

import { isClientCvFilename } from "@/lib/candidate-files";
import type { CvAiSourceFile, CvAiSources } from "@/lib/cv-ai-sources";

export type CvConfirmStep = "file" | "answers" | "notes";

export const CV_CONFIRM_STEPS: readonly CvConfirmStep[] = ["file", "answers", "notes"];

/** Co rekruter potwierdził: id pliku, odpowiedzi, treść notatek (po `trim`). */
export interface CvConfirmations {
  file: number | null;
  answers: boolean;
  notes: string | null;
}

export const NO_CONFIRMATIONS: CvConfirmations = { file: null, answers: false, notes: null };

const STEP_NAME: Record<CvConfirmStep, string> = {
  file: "plik",
  answers: "odpowiedzi",
  notes: "notatki",
};

/** Kroki jeszcze bez potwierdzenia dla bieżącego pliku i treści notatek. */
export function confirmationsLeft(
  confirmed: CvConfirmations,
  current: { fileId: number | null; noteDraft: string },
): CvConfirmStep[] {
  const left: CvConfirmStep[] = [];
  if (current.fileId == null || confirmed.file !== current.fileId) left.push("file");
  if (!confirmed.answers) left.push("answers");
  if (confirmed.notes === null || confirmed.notes !== current.noteDraft.trim()) left.push("notes");
  return left;
}

/** „Potwierdzone 1 z 3”. */
export function confirmedCountLabel(left: readonly CvConfirmStep[]): string {
  return `Potwierdzone ${CV_CONFIRM_STEPS.length - left.length} z ${CV_CONFIRM_STEPS.length}`;
}

/** Zdanie pod wyłączonym „Generuj”: „Potwierdź jeszcze: odpowiedzi, notatki”. */
export function confirmLeftSentence(left: readonly CvConfirmStep[]): string | null {
  if (left.length === 0) return null;
  return `Potwierdź jeszcze: ${left.map((step) => STEP_NAME[step]).join(", ")}`;
}

/**
 * Pliki do wyboru. Starszy serwer (okno wdrożenia) podaje tylko `original_cv` —
 * wtedy jedyny wybór to ten plik.
 */
export function cvFileChoices(data: Pick<CvAiSources, "original_cv" | "cv_files"> | null | undefined): CvAiSourceFile[] {
  if (data?.cv_files && data.cv_files.length > 0) return data.cv_files;
  const original = data?.original_cv;
  if (!original) return [];
  return [
    {
      document_id: original.document_id,
      filename: original.filename,
      uploaded_at: original.uploaded_at,
      is_primary: false,
      outdated: false,
      stage_original: false,
    },
  ];
}

function shortDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Czym jest plik: „Oryginał CV w tej rekrutacji · główne CV profilu · 14.10.2026”. */
export function cvFileDetail(file: CvAiSourceFile): string {
  const parts: string[] = [];
  if (file.stage_original) parts.push("Oryginał CV w tej rekrutacji");
  if (file.is_primary) parts.push("główne CV profilu");
  if (file.outdated) parts.push("nieaktualne");
  const date = shortDate(file.uploaded_at);
  if (date) parts.push(`wgrane ${date}`);
  return parts.join(" · ") || "plik CV kandydata";
}

/**
 * Żółta ramka przy gotowym CV (21.10.2026): źródło jest podejrzane, gdy to nie
 * kopia „Oryginał CV” rekrutacji, plik „CV dla klienta” („…B2B…”), plik
 * nieaktualny albo usunięty z profilu. `null` = źródło w porządku albo nieznane
 * (CV sprzed zmiany — nie zgadujemy).
 */
export function sourceCvWarning(
  data: Pick<CvAiSources, "last_source_cv" | "cv_files" | "original_cv"> | null | undefined,
): string | null {
  const used = data?.last_source_cv;
  if (!used) return null;
  const name = used.filename ?? "ten plik";
  const original = (data?.cv_files ?? []).find((file) => file.stage_original) ?? null;
  const tail = original && original.document_id !== used.document_id
    ? ` Oryginał CV w tej rekrutacji to ${original.filename ?? "inny plik"}.`
    : "";
  if (used.removed) return `CV powstało z pliku ${name}, którego nie ma już w profilu.${tail}`;
  if (used.outdated) return `CV powstało z pliku ${name}, oznaczonego jako nieaktualny.${tail}`;
  if (isClientCvFilename(used.filename)) return `CV powstało z ${name} — to „CV dla klienta”, nie CV kandydata.${tail}`;
  if (original && !used.stage_original) return `CV powstało z ${name}, a nie z Oryginału CV tej rekrutacji.${tail}`;
  return null;
}

/**
 * Plik dla „Napisz od nowa” (audyt 22.10.2026): ten, z którego powstało
 * poprawiane CV — „Napisz od nowa” poprawia to CV, a nie przełącza po cichu
 * źródła. `null` = plik domyślny (Oryginał CV), gdy poprzedniego źródła nie
 * znamy albo jest usunięty, nieaktualny lub to „CV dla klienta” (ramka przy
 * gotowym CV i tak mówi wtedy, że źródło jest złe).
 */
export function rewriteSourceFileId(
  data: Pick<CvAiSources, "last_source_cv"> | null | undefined,
): number | null {
  const used = data?.last_source_cv;
  if (!used || used.removed || used.outdated || isClientCvFilename(used.filename)) return null;
  return used.document_id;
}
