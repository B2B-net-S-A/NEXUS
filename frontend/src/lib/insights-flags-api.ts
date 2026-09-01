import api from "@/lib/api";

/**
 * Klient `/api/insights/performance-flags` — plakietki ostrzeżeń przy osobie
 * („Słabe wyniki”, „Procedury”) z tabeli „Performance per osoba”.
 *
 * Osobny plik od `insights-api.ts` świadomie: tamten opisuje MIARY liczone
 * w oknie czasu (`period`, `offset`), a flaga jest STANEM na dziś. Wspólny
 * moduł kusiłby, żeby dołożyć jej parametr okresu, którego ona nie ma — i
 * pierwszy konsument zrozumiałby „aktywne ostrzeżenia” jako „ostrzeżenia
 * postawione w tym miesiącu”.
 */

/** Zamknięty katalog — lustro `PerformanceFlagType` z backendu. */
export type PerformanceFlagType = "weak_results" | "procedures";

/**
 * Steruje WYŁĄCZNIE wyglądem plakietki. Kolor przychodzi z serwera, a nie
 * z mapy `flag_type → kolor` po tej stronie: druga taka mapa rozjeżdża się
 * cicho, bo obie wersje się renderują.
 */
export type PerformanceFlagSeverity = "critical" | "warning";

export interface PerformanceFlag {
  id: number;
  user_id: number;
  flag_type: PerformanceFlagType;
  /** Napis na plakietce, np. „Słabe wyniki”. */
  label: string;
  /** Stała treść typu, np. „Bardzo słabe wyniki, wymagana nagła poprawa”. */
  description: string;
  severity: PerformanceFlagSeverity;
  /** Wolny komentarz autora. `null` = nie napisano żadnego. */
  note: string | null;
  is_active: boolean;
  created_at: string | null;
  created_by_id: number | null;
  /**
   * Podpis autora. `null` znaczy „konto autora zostało usunięte”, a NIE
   * „nie wiadomo kto” — zapis bez zalogowanego admina jest niemożliwy.
   */
  created_by_name: string | null;
  cleared_at: string | null;
  cleared_by_id: number | null;
  cleared_by_name: string | null;
}

export interface PerformanceFlagTypeMeta {
  value: PerformanceFlagType;
  label: string;
  description: string;
  severity: PerformanceFlagSeverity;
}

export interface PerformanceFlagsResponse {
  /** Klucz to `user_id` jako STRING — JSON nie ma kluczy liczbowych. */
  flags_by_user: Record<string, PerformanceFlag[]>;
  types: PerformanceFlagTypeMeta[];
  total_active: number;
}

export interface PerformanceFlagHistoryResponse {
  user_id: number;
  user_name: string;
  /** Chip „były pracownik” — wyprowadzany z `User.is_active`, nie flaga. */
  is_former_employee: boolean;
  flags: PerformanceFlag[];
  types: PerformanceFlagTypeMeta[];
}

export interface CreatePerformanceFlagInput {
  user_id: number;
  flag_type: PerformanceFlagType;
  note?: string | null;
}

const BASE = "/api/insights/performance-flags";

/**
 * Klucz zapytania BEZ okresu — flagi są stanem na dziś. Dopisanie tu okresu
 * rozbiłoby cache na okna, których ten endpoint nie zna, i po zdjęciu
 * ostrzeżenia część widoków pokazywałaby je nadal.
 */
export const performanceFlagsQueryKey = [
  "insights",
  "performance-flags",
] as const;

export const performanceFlagHistoryQueryKey = (userId: number) =>
  ["insights", "performance-flags", "history", userId] as const;

export const insightsFlagsApi = {
  /** Wszystkie AKTYWNE plakietki naraz — jeden odczyt na całą tabelę. */
  list: () => api.get<PerformanceFlagsResponse>(BASE).then((r) => r.data),

  /** Pełna historia jednej osoby, także wygaszone. Tylko admin (403 dla reszty). */
  history: (userId: number) =>
    api
      .get<PerformanceFlagHistoryResponse>(`${BASE}/history/${userId}`)
      .then((r) => r.data),

  /** Postaw plakietkę. Tylko admin. 409 = ta osoba ma już aktywną tego typu. */
  create: (input: CreatePerformanceFlagInput) =>
    api.post<PerformanceFlag>(BASE, input).then((r) => r.data),

  /**
   * Popraw komentarz aktywnej plakietki. Tylko admin.
   * Wysyłamy WYŁĄCZNIE `note` — zapis jest częściowy, więc doklejenie
   * `is_active` zdejmowałoby ostrzeżenie przy zwykłej korekcie literówki.
   */
  updateNote: (flagId: number, note: string | null) =>
    api
      .patch<PerformanceFlag>(`${BASE}/${flagId}`, { note })
      .then((r) => r.data),

  /**
   * WYGAŚ plakietkę. Nie ma DELETE — wiersz zostaje razem z autorem i datą,
   * bo pytanie „kto i kiedy to postawił” bywa zadawane pół roku później.
   * Operacji nie da się cofnąć (PATCH `is_active: true` → 409).
   */
  clear: (flagId: number) =>
    api
      .patch<PerformanceFlag>(`${BASE}/${flagId}`, { is_active: false })
      .then((r) => r.data),
};
