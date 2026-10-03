/**
 * Błędy API FastAPI → tekst dla użytkownika.
 *
 * Moduł jest czysty: bez instancji axios, interceptorów i efektów ubocznych,
 * więc importują go też strony publiczne, a mock `@/lib/api` w testach
 * komponentów go nie zastępuje. `extractErrorMsg` z `lib/api.ts` stoi na tej
 * samej funkcji `messageFromApiResponse`.
 */
import { isPermission, permissionLabel } from "@/lib/permissions";

// Polskie etykiety pól kontraktu — wspólne dla formularzy i dla tłumaczenia
// backendowego 409 {message: "Missing required fields", missing: [...]}
// (ACTIVATION_REQUIRED_FIELDS w backend/app/services/contract_service.py).
export const CONTRACT_FIELD_LABELS: Record<string, string> = {
  candidate_id: "Kandydat",
  client_id: "Klient",
  start_date: "Data rozpoczęcia",
  end_date: "Data zakończenia",
  rate_candidate: "Stawka kosztowa (kandydata)",
  rate_client: "Stawka przychodowa (klienta)",
  contract_type: "Typ kontraktu",
  work_mode: "Tryb pracy",
  rate_unit: "Jednostka stawki",
};

// Typ błędu z `backend/app/core/null_character_guard.py`: NUL (U+0000) w query,
// ścieżce albo ciele JSON. PostgreSQL go nie przechowuje, więc backend odrzuca
// żądanie 422, zanim cokolwiek zapisze. Znak jest niewidoczny (zwykle przychodzi
// z wklejonego tekstu), dlatego komunikat mówi, co z nim zrobić.
const NULL_CHARACTER_ERROR_TYPE = "null_character";

const ASK_ADMIN_FOR_ACCESS = "Poproś administratora o dostęp.";

/** Części NEXUSA z bramki sekcji (`backend/app/api/section_access.py`). */
const SECTION_LABELS: Record<string, string> = {
  sourcing: "Kandydaci",
  pipeline: "Rekrutacje",
  delivery: "Klienci, kontrakty i zamówienia",
  insights: "Insights",
  finance: "Finanse",
  system_admin: "Administracja",
};

/**
 * Zdanie dla odmowy dostępu, która niesie sam kod (bez `message`):
 *  • `section_access_denied` — bramka sekcji (`{section, required, granted}`
 *    albo `{any_section}`),
 *  • `action_access_denied` — poziom akcji (Generator umów B2B) albo jedno
 *    z uprawnień z ekranu Osoby i role,
 *  • `finance_fields_forbidden` — zapis kwot bez uprawnienia do kwot (nowy
 *    backend dokłada `message` z nazwą brakującego uprawnienia; to zdanie
 *    zostaje dla odpowiedzi bez niego).
 */
function accessRefusalMessage(detail: Record<string, unknown>): string | undefined {
  switch (detail.code) {
    case "section_access_denied": {
      const label =
        typeof detail.section === "string" ? SECTION_LABELS[detail.section] : undefined;
      if (!label) return `Nie masz dostępu do tej części NEXUSA. ${ASK_ADMIN_FOR_ACCESS}`;
      // `granted: "read"` przy wymaganym zapisie = konto widzi tę część, ale
      // niczego w niej nie zmienia.
      if (detail.required === "write" && detail.granted === "read") {
        return `W części „${label}” masz tylko podgląd — ta operacja wymaga uprawnienia do zmian. ${ASK_ADMIN_FOR_ACCESS}`;
      }
      return `Nie masz dostępu do części „${label}”. ${ASK_ADMIN_FOR_ACCESS}`;
    }
    case "action_access_denied": {
      const action = typeof detail.action === "string" ? detail.action : "";
      if (isPermission(action)) {
        return `Brakuje Ci uprawnienia „${permissionLabel(action)}”. ${ASK_ADMIN_FOR_ACCESS}`;
      }
      if (action === "b2b_contract_generator") {
        return `Twój poziom dostępu do Generatora umów B2B nie pozwala na tę operację. ${ASK_ADMIN_FOR_ACCESS}`;
      }
      return `Nie masz uprawnienia do tej operacji. ${ASK_ADMIN_FOR_ACCESS}`;
    }
    case "finance_fields_forbidden":
      return `Nie masz uprawnienia do stawek i kwot — zapisz pozostałe pola bez nich. ${ASK_ADMIN_FOR_ACCESS}`;
    default:
      return undefined;
  }
}

/**
 * Komunikat z ciała odpowiedzi API albo `undefined`, gdy nie ma w nim niczego
 * do pokazania człowiekowi. Każda gałąź zwraca TEKST, nigdy surowy `detail`.
 */
export function messageFromApiResponse(
  status: number | undefined,
  data: unknown,
): string | undefined {
  // 429 = limit zapytań. slowapi odpowiada ciałem {"error": "Rate limit
  // exceeded: N per 1 minute"} — BEZ klucza `detail`, więc bez tej gałęzi
  // wołający spadał na surowe `error.message` i użytkownik dostawał
  // „Request failed with status code 429" (zgłoszenie: Wiktoria Denka).
  if (status === 429) {
    console.error("[api] rate limited:", data);
    return "Zbyt wiele prób w krótkim czasie — odczekaj minutę i spróbuj ponownie.";
  }
  if (!data || typeof data !== "object") return undefined;
  const { detail, message } = data as { detail?: unknown; message?: unknown };
  // `require_roles` (backend/app/api/deps.py) zwraca detail w formie
  // "Requires one of roles: ['admin', 'delivery_lead', ...]" — to nazwy ról z modelu
  // danych, nie komunikat dla użytkownika. Wyciekał wprost do toasta
  // (zgłoszenie generatora umów: użytkownik zobaczył surową listę ról).
  // Tłumimy jak surowe `loc` niżej: raw do konsoli, człowiekowi zdanie.
  if (
    status === 403 &&
    typeof detail === "string" &&
    detail.startsWith("Requires one of roles:")
  ) {
    console.error("[api] role gate:", detail);
    return "Nie masz uprawnień do tej operacji — poproś administratora o dostęp.";
  }
  // FastAPI HTTPException(detail="...") → string detail
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { message: detailMessage, missing } = detail as {
      message?: unknown;
      missing?: unknown;
    };
    // Lifecycle kontraktu: 409 {message: "Missing required fields",
    // missing: [...]}. Surowy `message` gubił LISTĘ pól — użytkownik widział
    // goły angielski banner bez wskazania, czego brakuje (zgłoszenie:
    // formularz „Nowy kontrakt", Jakub Jedynak / CARDIF). Tłumaczymy nazwy
    // pól na etykiety z formularza. Jawny match na message lifecycle'u — sam
    // klucz `missing` mógłby w przyszłości znaczyć co innego w innym endpointzie.
    if (
      detailMessage === "Missing required fields" &&
      Array.isArray(missing) &&
      missing.length > 0
    ) {
      const labels = (missing as string[]).map(
        (field) => CONTRACT_FIELD_LABELS[field] ?? field,
      );
      return `Uzupełnij brakujące pola: ${labels.join(", ")}`;
    }
    // Domenowe konflikty mogą zwracać ustrukturyzowany detail, np.
    // {message, contract_ids}. Użytkownik powinien zobaczyć komunikat, nie
    // "[object Object]" ani ogólny status HTTP. Tędy idzie też odmowa bramki
    // uprawnienia ({code: "permission_denied", message}) — zdanie z serwera
    // nazywa brakujące uprawnienie.
    if (typeof detailMessage === "string") return detailMessage;
    // Odmowy z samym kodem (bramka sekcji, poziom akcji, starszy backend bez
    // `message`): bez tej gałęzi wołający spadał na angielskie
    // „Request failed with status code 403” z axiosa.
    const refusal = accessRefusalMessage(detail as Record<string, unknown>);
    if (refusal) return refusal;
  }
  // FastAPI Pydantic ValidationError → list of { msg, loc, ... }
  if (Array.isArray(detail) && detail.length > 0) {
    if (
      detail.some(
        (item) =>
          (item as { type?: unknown } | null)?.type === NULL_CHARACTER_ERROR_TYPE,
      )
    ) {
      return "Tekst zawiera niedozwolony, niewidoczny znak (NUL) — usuń go albo wpisz tekst ponownie.";
    }
    const first = detail[0] as { msg?: unknown; loc?: unknown } | null;
    if (typeof first?.msg === "string") {
      const loc = Array.isArray(first.loc) ? first.loc : [];
      // Tylko `body` to dane wpisane przez użytkownika — tam nazwa pola
      // + komunikat są actionable (quality finding MEDIUM #23).
      if (loc[0] === "body") {
        const field = loc.slice(1).join(".") || "pole";
        return `${field}: ${first.msg}`;
      }
      // query/path/header ustawia kod aplikacji, nie użytkownik — surowy
      // loc to wyciek wewnętrznego kontraktu (M3-UI-02, np.
      // "query.current_user: Field required" na zakładce Dopasowanie).
      console.error("[api] request contract error:", detail);
      return "Błąd żądania — odśwież stronę lub spróbuj ponownie.";
    }
  }
  if (typeof message === "string") return message;
  return undefined;
}

/**
 * Komunikat błędu API do stanu, toasta albo alertu — ZAWSZE tekst.
 *
 * `detail` z FastAPI bywa stringiem, obiektem (`{message, ...}`) albo TABLICĄ
 * błędów walidacji `{type, loc, msg, input}`. Odczyt `response.data.detail
 * ?? fallback` przepuszczał obiekt dalej: w JSX wywracał stronę (React #31),
 * w szablonie tekstu dawał „[object Object]". Tu `detail` tłumaczy
 * `messageFromApiResponse`, a gdy odpowiedź go nie niesie (sieć, 5xx
 * z HTML-em), wraca `fallback` wołającego. Kształt błędu jest czytany
 * strukturalnie, więc działa też dla odtworzonej odpowiedzi (np. JSON z Bloba).
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null
  )?.response;
  const status =
    typeof response?.status === "number" ? response.status : undefined;
  const detail = (response?.data as { detail?: unknown } | null | undefined)
    ?.detail;
  if (
    status !== 429 &&
    (detail === undefined || detail === null || detail === "")
  ) {
    return fallback;
  }
  return messageFromApiResponse(status, response?.data) ?? fallback;
}
