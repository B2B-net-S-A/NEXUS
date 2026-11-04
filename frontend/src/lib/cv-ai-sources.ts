/**
 * „Z czego powstało” (decyzja D4, 13.10.2026) — materiał, który model czyta
 * przy generacji CV w rekrutacji.
 *
 * Serwer podaje same liczby (`GET /api/candidates/stages/{id}/cv/ai-sources`),
 * treść widać w panelu osoby. Przełączniki idą w `POST /api/cv-generator/generate`
 * jako `sources` (tylko z etapem). Oryginalne CV i Profil Championa wchodzą
 * zawsze, notatki ze stawką są zawsze wycinane (`money_text`) — tego nie da
 * się włączyć, więc karta pokazuje je jako informację.
 *
 * Tu tylko czyste reguły i zdania; komponent `AiSourcesRows` je rysuje
 * w karcie „CV do klienta” i w oknie generatora.
 */

import api from "@/lib/api";
import { countForm } from "@/lib/cv-qc";

export type CvAiSourceKey = "answers" | "notes" | "transcripts" | "prep";
export type CvAiSourceToggles = Record<CvAiSourceKey, boolean>;

export const CV_AI_SOURCE_KEYS: readonly CvAiSourceKey[] = ["answers", "notes", "transcripts", "prep"];

/**
 * Lustro `AI_SOURCE_DEFAULTS` (`standalone_service.py`): rozmowy nie mają pola
 * rekrutacji, a prep niesie ocenę rekrutera — oba domyślnie wyłączone.
 */
export const CV_AI_SOURCE_DEFAULTS: CvAiSourceToggles = {
  answers: true,
  notes: true,
  transcripts: false,
  prep: false,
};

export interface CvAiSourceCount {
  count: number;
  /**
   * Odpowiedzi: ile przeczy pytaniu (nie są dowodem). Transkrypty: ile rozmów
   * jest sprzed okna tej rekrutacji (nie wchodzą nigdy).
   */
  excluded: number;
}

/** Plik CV osoby do wyboru w kroku „Plik CV” (21.10.2026). */
export interface CvAiSourceFile {
  document_id: number;
  filename: string | null;
  uploaded_at: string | null;
  is_primary: boolean;
  /** „Nieaktualne” albo z kwarantanny tożsamości — nie proponujemy domyślnie. */
  outdated: boolean;
  /** Ten sam plik co kopia „Oryginał CV” tej rekrutacji. */
  stage_original: boolean;
}

/** Plik, z którego powstała bieżąca wersja CV etapu (21.10.2026). */
export interface CvAiSourceUsedFile {
  document_id: number;
  filename: string | null;
  outdated: boolean;
  stage_original: boolean;
  /** Pliku nie ma już wśród plików CV osoby. */
  removed: boolean;
}

/** Odpowiedź `GET …/cv/ai-sources`. */
export interface CvAiSources {
  /** Plik zaznaczony domyślnie: kopia „Oryginał CV” etapu, a bez niej główne CV. */
  original_cv: { document_id: number; filename: string | null; uploaded_at: string | null } | null;
  /** Pliki CV osoby w kolejności generatora; starszy serwer ich nie podaje. */
  cv_files?: CvAiSourceFile[];
  champion: boolean;
  answers: CvAiSourceCount;
  notes: CvAiSourceCount;
  transcripts: CvAiSourceCount;
  prep: CvAiSourceCount;
  rate_notes: CvAiSourceCount;
  defaults: Partial<CvAiSourceToggles>;
  /** Wybór, z którego powstała bieżąca wersja CV etapu (`null` = sprzed zmiany). */
  last_used: Partial<CvAiSourceToggles> | null;
  /** Plik CV bieżącej wersji („Powstało z”); brak = CV sprzed 21.10.2026 albo spoza generatora. */
  last_source_cv?: CvAiSourceUsedFile | null;
}

export const cvAiSourcesQueryKey = (stageId: number) => ["cv-ai-sources", stageId] as const;

export function fetchCvAiSources(stageId: number): Promise<CvAiSources> {
  return api.get<CvAiSources>(`/api/candidates/stages/${stageId}/cv/ai-sources`).then((r) => r.data);
}

/**
 * Przełączniki na start: wybór z bieżącej wersji CV etapu, a bez niej —
 * domyślne z serwera (i te z frontu, gdyby serwer klucza nie podał).
 */
export function initialAiSources(
  data: Pick<CvAiSources, "defaults" | "last_used"> | null | undefined,
): CvAiSourceToggles {
  const base = data?.last_used ?? data?.defaults ?? null;
  const out = { ...CV_AI_SOURCE_DEFAULTS };
  for (const key of CV_AI_SOURCE_KEYS) {
    const fromBase = base?.[key];
    const fromDefaults = data?.defaults?.[key];
    if (typeof fromBase === "boolean") out[key] = fromBase;
    else if (typeof fromDefaults === "boolean") out[key] = fromDefaults;
  }
  return out;
}

/** Jak wiersz źródła zachowuje się w karcie. */
export type CvAiSourceMode = "toggle" | "always" | "never" | "missing";

export interface CvAiSourceRow {
  id: CvAiSourceKey | "original" | "champion" | "rate_notes";
  label: string;
  detail: string;
  mode: CvAiSourceMode;
  /** Przełącznik bez materiału — nic by nie zmienił. */
  empty?: boolean;
}

function excludedSentence(count: number, verbs: [string, string, string], tail: string): string {
  const few = count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14);
  const verb = count === 1 ? verbs[0] : few ? verbs[1] : verbs[2];
  return `${count} ${verb}${tail}`;
}

/**
 * Wiersze „Z czego powstało” w kolejności karty. Zdania mówią, ile materiału
 * jest i czego model nie dostanie, bez treści notatek.
 */
export function aiSourceRows(data: CvAiSources): CvAiSourceRow[] {
  const rows: CvAiSourceRow[] = [];
  rows.push(
    data.original_cv
      ? {
          id: "original",
          label: "Oryginalne CV",
          detail: data.original_cv.filename?.trim() || "plik CV kandydata",
          mode: "always",
        }
      : {
          id: "original",
          label: "Oryginalne CV",
          detail: "brak pliku CV — dodaj go na profilu kandydata",
          mode: "missing",
        },
  );
  rows.push(
    data.champion
      ? { id: "champion", label: "Profil Championa", detail: "wymagania tej rekrutacji", mode: "always" }
      : { id: "champion", label: "Profil Championa", detail: "brak", mode: "missing" },
  );

  const answers = data.answers;
  rows.push({
    id: "answers",
    label: "Odpowiedzi ze screeningu",
    detail:
      answers.count === 0
        ? "brak odpowiedzi w tej rekrutacji"
        : [
            countForm(answers.count, ["odpowiedź", "odpowiedzi", "odpowiedzi"]),
            answers.excluded > 0
              ? excludedSentence(
                  answers.excluded,
                  ["przeczy", "przeczą", "przeczy"],
                  answers.excluded === 1 ? " pytaniu — nie jest dowodem" : " pytaniu — nie są dowodem",
                )
              : null,
          ]
            .filter(Boolean)
            .join(", "),
    mode: "toggle",
    empty: answers.count === 0,
  });

  rows.push({
    id: "notes",
    label: "Notatki tej rekrutacji",
    detail:
      data.notes.count === 0
        ? "brak notatek w tej rekrutacji"
        : countForm(data.notes.count, ["notatka", "notatki", "notatek"]),
    mode: "toggle",
    empty: data.notes.count === 0,
  });

  const transcripts = data.transcripts;
  const usable = Math.max(0, transcripts.count - transcripts.excluded);
  rows.push({
    id: "transcripts",
    label: "Transkrypty rozmów",
    detail:
      transcripts.count === 0
        ? "brak nagranych rozmów"
        : [
            countForm(transcripts.count, ["rozmowa", "rozmowy", "rozmów"]),
            transcripts.excluded > 0
              ? excludedSentence(
                  transcripts.excluded,
                  ["spoza tej rekrutacji nie wchodzi", "spoza tej rekrutacji nie wchodzą", "spoza tej rekrutacji nie wchodzi"],
                  "",
                )
              : null,
          ]
            .filter(Boolean)
            .join(", "),
    mode: "toggle",
    empty: usable === 0,
  });

  rows.push({
    id: "prep",
    label: "Podsumowania prepu",
    detail:
      data.prep.count === 0
        ? "brak podsumowań prepu"
        : countForm(data.prep.count, ["podsumowanie", "podsumowania", "podsumowań"]),
    mode: "toggle",
    empty: data.prep.count === 0,
  });

  rows.push({
    id: "rate_notes",
    label: "Notatki ze stawką",
    detail:
      data.rate_notes.count > 0
        ? `zawsze wycinane · ${countForm(data.rate_notes.count, ["notatka", "notatki", "notatek"])}`
        : "zawsze wycinane",
    mode: "never",
  });
  return rows;
}
