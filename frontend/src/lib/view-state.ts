/**
 * Maszyna stanów dla ekranów sterowanych zapytaniem (audyt F-20).
 *
 * Problem, który to zamyka: ekrany robiły `const { data } = useQuery(...)`
 * i renderowały pusty stan albo „nie znaleziono", gdy `data` było `undefined`.
 * Dla 403 z bramki RBAC wyglądało to jak „nie masz żadnych danych", a dla 500
 * jak „rekord nie istnieje". To dokładnie ten wzorzec, przez który 403 na GET
 * bywał zgłaszany jako „skasowało mi dane".
 *
 * Kontrakt:
 *   403 → "forbidden"  — brak uprawnień, ŻADNYCH akcji empty-state
 *   404 → "not_found"  — zasób nie istnieje
 *   5xx / brak sieci → "error" — awaria, z możliwością ponowienia
 *   sukces + 0 rekordów → "empty" — dopiero tutaj wolno zachęcać do dodania
 */

export type ViewState =
  | "loading"
  | "forbidden"
  | "not_found"
  | "error"
  | "empty"
  | "ready"

/** Wyciągnij status HTTP z błędu axios/fetch. `undefined` = błąd sieci. */
export function httpStatusFromError(error: unknown): number | undefined {
  if (!error || typeof error !== "object") return undefined
  const response = (error as { response?: { status?: unknown } }).response
  const status = response?.status ?? (error as { status?: unknown }).status
  return typeof status === "number" ? status : undefined
}

export function isForbiddenError(error: unknown): boolean {
  return httpStatusFromError(error) === 403
}

export function isNotFoundError(error: unknown): boolean {
  return httpStatusFromError(error) === 404
}

export interface ResolveViewStateInput {
  /** Pierwsze ładowanie (React Query `isLoading`). */
  isLoading: boolean
  /** Zapytanie zakończyło się błędem. Pomijalne, gdy podajesz `error`. */
  isError?: boolean
  /** Błąd zapytania — z niego czytamy status HTTP. */
  error?: unknown
  /** Sukces, ale zero rekordów / brak encji. */
  isEmpty?: boolean
  /**
   * React Query `isSuccess`. Gdy podany, `"empty"` wolno zwrócić WYŁĄCZNIE
   * przy sukcesie — inaczej przerwa między ponowieniami udaje pusty wynik.
   *
   * Opcjonalny wyłącznie po to, żeby nie zerwać istniejących wywołań.
   * KAŻDE NOWE wywołanie musi go podawać.
   */
  isSuccess?: boolean
}

/**
 * Zamień stan React Query na jeden z sześciu rozłącznych stanów widoku.
 * Kolejność jest istotna: błąd NIGDY nie może się przebrać za pusty wynik.
 *
 * Gałąź `isSuccess === false` zamyka dziurę, przez którą AWARIA renderowała
 * się jako „brak danych": w przerwie między ponowieniami react-query ma
 * `isLoading=false`, `isError=false` i wciąż puste `data`, więc bez niej
 * jedynym pasującym stanem było `"empty"`. Sekcje obchodziły to, podając
 * `isPending` w miejsce `isLoading` — obejście, nie kontrakt.
 */
export function resolveViewState({
  isLoading,
  isError,
  error,
  isEmpty,
  isSuccess,
}: ResolveViewStateInput): ViewState {
  if (isLoading) return "loading"
  if (isError || error) {
    const status = httpStatusFromError(error)
    if (status === 403) return "forbidden"
    if (status === 404) return "not_found"
    return "error"
  }
  // Jawne `false` (a nie „falsy") — pominięty `isSuccess` zostawia stare
  // zachowanie wywołań sprzed tej zmiany.
  if (isSuccess === false) return "loading"
  if (isEmpty) return "empty"
  return "ready"
}

/** Czy dla tego stanu wolno w ogóle renderować dane / akcje empty-state. */
export function isBlockingViewState(state: ViewState): boolean {
  return state === "forbidden" || state === "not_found" || state === "error"
}
