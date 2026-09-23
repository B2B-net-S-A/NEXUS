/**
 * Sekwencja „Wyślij klientowi" — krok 06 programu „flow w języku C2"
 * (docs/c2-flow-program.md, PR 6/7).
 *
 * Dziś to trzy osobne kliknięcia w trzech miejscach: stawka do klienta
 * w modalu przy przeciąganiu karty na „CV Wysłane", link dla klienta z modalu
 * na profilu, a sam ruch na tablicy. Makieta zszywa je w jedną akcję —
 * i właśnie dlatego kolejność oraz obsługa błędu muszą być regułą, a nie
 * przypadkiem w komponencie.
 *
 * Kolejność jest LOAD-BEARING: `move → share_link → client_rate`.
 * - Ruch PIERWSZY: link dla klienta to działający, 30-dniowy dostęp do CV
 *   z sekretem zwracanym RAZ. Do 09.2026 link powstawał przed ruchem, więc
 *   każdy ruch odrzucony przez serwer (weto HM, karta „Pending", czarna
 *   lista) zostawiał żywy link do CV kandydata, którego nikt nie wysłał —
 *   i którego adresu nie dało się już odtworzyć. Link powstaje więc
 *   WYŁĄCZNIE po udanym ruchu.
 * - Link celuje w etap SPRZED ruchu: ruch na `cv_sent` tworzy nowy
 *   `CandidateStage` bez dokumentu, a sfinalizowane CV brandowane leży na
 *   etapie „Zweryfikowany". Wołający przekazuje więc identyfikator etapu
 *   złapany PRZED ruchem (serwer nie wymaga, żeby był to etap najnowszy).
 * - Stawka W RUCHU (Pipeline v4, 23.09.2026): poza Nordeą serwer odmawia
 *   ruchu na „CV Wysłane" bez stawki do klienta, więc stawka jedzie w tym
 *   samym żądaniu (`client_rate_*` w `/pipeline/move`) i ląduje na nowym
 *   wierszu etapu. Do 23.09 zapisywał ją osobny PATCH po ruchu.
 *
 * Porażka linku PO ruchu NIE cofa ruchu i nie jest fatalna
 * (lustro tablicy: „Przeniesiono, ale nie udało się zapisać stawki"): ruch
 * jest faktem, którego nie da się odkręcić. Stawkę uzupełnia się z profilu
 * kandydata, a link — z panelu wyników warsztatu, który pamięta etap sprzed
 * ruchu (profil i dok celują w etap najnowszy). Endpoint stawki stoi za bramką finansową
 * (`CandidateFinanceAccess` = wyłącznie admin) — gdyby był fatalny,
 * blokowałby wysyłkę każdemu poza adminem.
 *
 * Żaden krok nie jest pomijany po cichu: pominięcie jest DECYZJĄ zapisaną
 * w planie (`null` = rekruter świadomie nie podał stawki / nie chce linku),
 * a porażka ruchu przerywa sekwencję, zanim cokolwiek powstanie.
 */

import type { RateUnit } from "@/lib/api";

export type CvHandoffStep = "share_link" | "move" | "client_rate";

export const CV_HANDOFF_STEP_LABEL: Record<CvHandoffStep, string> = {
  share_link: "utworzenie linku dla klienta",
  move: "przeniesienie na „CV Wysłane”",
  client_rate: "zapis stawki do klienta",
};

export interface CvHandoffPlan {
  /** `null` = rekruter nie podał stawki (odpowiednik „Pomiń" w modalu). */
  clientRate: { value: number; unit: RateUnit; currency: string } | null;
  /** `null` = wysyłka bez linku (np. brak sfinalizowanego CV brandowanego). */
  shareLink: { expiresInDays: number } | null;
}

export interface CvHandoffDeps {
  createShareLink: (opts: {
    expiresInDays: number;
  }) => Promise<{ shareUrlSuffix: string | null }>;
  /** Ruch na „CV Wysłane" — ze stawką do klienta w tym samym żądaniu. */
  move: (clientRate: CvHandoffPlan["clientRate"]) => Promise<void>;
}

export interface CvHandoffResult {
  completed: CvHandoffStep[];
  skipped: CvHandoffStep[];
  /**
   * Kroki PO ruchu, które padły, choć ruch już się wykonał (link dla klienta,
   * stawka do klienta). Ruch jest faktem — to ostrzeżenie, nie porażka.
   */
  failedAfterMove: { step: CvHandoffStep; reason: unknown }[];
  shareUrlSuffix: string | null;
}

/**
 * Porażka RUCHU — jedynego kroku, który przerywa sekwencję. Ruch idzie
 * pierwszy, więc w chwili tej porażki nic jeszcze nie powstało.
 */
export class CvHandoffError extends Error {
  readonly step: CvHandoffStep;
  readonly completed: CvHandoffStep[];
  readonly reason: unknown;

  constructor(step: CvHandoffStep, completed: CvHandoffStep[], reason: unknown) {
    super(`Krok „${CV_HANDOFF_STEP_LABEL[step]}” nie powiódł się.`);
    this.name = "CvHandoffError";
    this.step = step;
    this.completed = completed;
    this.reason = reason;
  }
}

export async function runCvHandoff(
  plan: CvHandoffPlan,
  deps: CvHandoffDeps,
): Promise<CvHandoffResult> {
  const completed: CvHandoffStep[] = [];
  const skipped: CvHandoffStep[] = [];
  const failedAfterMove: CvHandoffResult["failedAfterMove"] = [];
  let shareUrlSuffix: string | null = null;

  try {
    await deps.move(plan.clientRate);
  } catch (e) {
    throw new CvHandoffError("move", [...completed], e);
  }
  completed.push("move");

  if (plan.shareLink) {
    try {
      const res = await deps.createShareLink(plan.shareLink);
      shareUrlSuffix = res.shareUrlSuffix;
      completed.push("share_link");
    } catch (e) {
      failedAfterMove.push({ step: "share_link", reason: e });
    }
  } else {
    skipped.push("share_link");
  }

  // Stawka pojechała w ruchu — udany ruch = zapisana stawka.
  if (plan.clientRate) completed.push("client_rate");
  else skipped.push("client_rate");

  return { completed, skipped, failedAfterMove, shareUrlSuffix };
}

/** Status HTTP z błędu (axios: `error.response.status`) — `null` bez odpowiedzi. */
function httpStatusOf(reason: unknown): number | null {
  const status = (reason as { response?: { status?: unknown } } | null)?.response
    ?.status;
  return typeof status === "number" ? status : null;
}

/**
 * Czy serwer JEDNOZNACZNIE odmówił (odpowiedź 4xx) — tylko wtedy wiadomo, że
 * ruch się nie zapisał. Brak odpowiedzi (limit czasu, zerwane połączenie,
 * „Network Error" po 500 bez nagłówków CORS) i 5xx z bramki albo serwera nie
 * mówią, czy transakcja zdążyła się zatwierdzić.
 */
export function isDefiniteRefusal(reason: unknown): boolean {
  const status = httpStatusOf(reason);
  return status !== null && status >= 400 && status < 500;
}

/**
 * Zdanie po polsku dla sekwencji przerwanej na ruchu: co padło i co z tym
 * zrobić. Ruch idzie pierwszy, więc przy tej porażce link i stawka nie
 * powstały. O samym ruchu wiemy tyle, ile powiedział serwer: odmowa (4xx)
 * znaczy „nic się nie zmieniło", ale brak odpowiedzi albo 5xx znaczy „nie
 * wiadomo" — ruch mógł się zapisać, a ponowienie dopisałoby drugi etap
 * „CV Wysłane".
 */
export function describeCvHandoffFailure(
  error: CvHandoffError,
  detail: string,
): string {
  const label = CV_HANDOFF_STEP_LABEL[error.step];
  if (
    error.step === "move" &&
    error.completed.length === 0 &&
    !isDefiniteRefusal(error.reason)
  ) {
    return (
      `Nie wiadomo, czy się udało: ${label}${detail ? ` — ${detail}` : ""}. ` +
      "Serwer nie potwierdził zapisu (limit czasu, zerwane połączenie albo błąd " +
      "serwera), więc kandydat mógł już zostać przeniesiony. Odśwież kartę " +
      "kandydata, zanim spróbujesz ponownie — ponowienie mogłoby dodać drugi " +
      "etap „CV Wysłane”. Link dla klienta nie powstał."
    );
  }
  const head = `Nie udało się: ${label}${detail ? ` — ${detail}` : "."}`;
  if (error.completed.length === 0) {
    return `${head} Nic nie zostało zmienione — link dla klienta nie powstał. Popraw przyczynę i spróbuj ponownie.`;
  }
  const done = error.completed.map((s) => CV_HANDOFF_STEP_LABEL[s]);
  return `${head} Wcześniejsze kroki ZOSTAŁY wykonane (${done.join(", ")}).`;
}

/**
 * Podsumowanie sekwencji, w której ruch się wykonał — mówi też o krokach
 * świadomie pominiętych i o linku/stawce, które padły PO ruchu (ton
 * ostrzeżenia wybiera wołający: `failedAfterMove.length > 0`).
 */
export function describeCvHandoffSuccess(
  result: CvHandoffResult,
  detailOf: (reason: unknown) => string = () => "",
): string {
  const parts = ["Kandydat przeniesiony na „CV Wysłane”."];
  const rateFailure = result.failedAfterMove.find((f) => f.step === "client_rate");
  if (rateFailure) {
    const detail = detailOf(rateFailure.reason);
    parts.push(
      `Stawki do klienta NIE udało się zapisać${detail ? ` (${detail})` : ""} — uzupełnij ją z profilu kandydata.`,
    );
  } else if (result.completed.includes("client_rate")) {
    parts.push("Stawka do klienta zapisana.");
  } else {
    parts.push("Stawka do klienta bez zmian.");
  }
  const linkFailure = result.failedAfterMove.find((f) => f.step === "share_link");
  if (linkFailure) {
    const detail = detailOf(linkFailure.reason);
    // Profil i dok celują w NAJNOWSZY etap („CV Wysłane", bez dokumentu), więc
    // ponowienie ma sens tylko z panelu, który pamięta etap sprzed ruchu.
    parts.push(
      `Linku dla klienta NIE udało się utworzyć${detail ? ` (${detail})` : ""} — ponów go przyciskiem „Utwórz link ponownie” w panelu „Utworzone linki do CV”.`,
    );
  } else if (result.completed.includes("share_link")) {
    parts.push("Link dla klienta utworzony.");
  } else {
    parts.push("Bez linku dla klienta.");
  }
  return parts.join(" ");
}

// ── Podgląd marży (makieta kroku 06) ───────────────────────────────────────

export interface MarginPreviewInput {
  /** Stawka do klienta wpisana w doku (surowa treść pola). */
  clientRate: string;
  clientUnit: RateUnit;
  /** Stawka oczekiwana kandydata z karty pipeline'u. */
  candidateRate: string | number | null | undefined;
  candidateUnit: RateUnit | null | undefined;
  candidateCurrency?: string | null;
  clientCurrency?: string;
}

export interface MarginPreview {
  /** Różnica w tej samej jednostce; `null` = nie da się policzyć. */
  value: number | null;
  /** Udział marży w stawce klienta (0–1); `null` razem z `value`. */
  ratio: number | null;
  /** Zdanie do pola „Marża (podgląd)" — zawsze niepuste. */
  label: string;
  /** Powód, dla którego nie liczymy — do `title`, nigdy zamiast liczby. */
  reason: string | null;
}

/**
 * Marża = stawka klienta − stawka kandydata, WYŁĄCZNIE w tej samej jednostce
 * i walucie.
 *
 * Przeliczanie jednostek jest tu świadomie zabronione: `RATE_UNIT` rządzi
 * także interpretacją stawki klienta, a dzienna stawka przeczytana jako
 * godzinowa rozsadza marżę 8-krotnie (ta sama pułapka co w module zamówień).
 * Nieporównywalne wejście daje „—" z powodem, nie liczbę „na oko".
 */
export function computeMarginPreview({
  clientRate,
  clientUnit,
  candidateRate,
  candidateUnit,
  candidateCurrency,
  clientCurrency = "PLN",
}: MarginPreviewInput): MarginPreview {
  const none = (reason: string): MarginPreview => ({
    value: null,
    ratio: null,
    label: "—",
    reason,
  });

  const client = Number.parseFloat(String(clientRate).replace(",", "."));
  if (!Number.isFinite(client) || client <= 0) {
    return none("Wpisz stawkę do klienta, żeby zobaczyć marżę.");
  }
  if (candidateRate == null || candidateRate === "") {
    return none("Kandydat nie ma zapisanej stawki oczekiwanej.");
  }
  const candidate = Number.parseFloat(String(candidateRate).replace(",", "."));
  if (!Number.isFinite(candidate)) {
    return none("Stawki oczekiwanej kandydata nie da się odczytać jako liczby.");
  }
  if (!candidateUnit || candidateUnit !== clientUnit) {
    return none(
      "Różne jednostki stawek — marży nie liczymy, żeby nie pomylić dnia z godziną.",
    );
  }
  const candidateCur = (candidateCurrency ?? "PLN").trim().toUpperCase();
  if (candidateCur !== clientCurrency.trim().toUpperCase()) {
    return none("Różne waluty stawek — marży nie liczymy bez kursu.");
  }

  const value = Math.round((client - candidate) * 100) / 100;
  const ratio = value / client;
  const unitLabel =
    clientUnit === "hourly"
      ? "PLN/h"
      : clientUnit === "daily"
        ? "PLN/dzień"
        : "PLN/mc";
  return {
    value,
    ratio,
    label: `${value.toLocaleString("pl-PL")} ${unitLabel} · ${Math.round(ratio * 100)} %`,
    reason: null,
  };
}
