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
 * Kolejność jest LOAD-BEARING: `share_link → move → client_rate`.
 * - Link PRZED ruchem: ruch na `cv_sent` tworzy po stronie backendu NOWY
 *   `CandidateStage`, a link dla klienta jest przypięty do etapu, na którym
 *   leży sfinalizowane CV brandowane. Link tworzony PO ruchu celowałby
 *   w świeży etap bez dokumentu (409 „brak sfinalizowanego CV").
 * - Stawka PO ruchu: `update_latest_client_rate` pisze na NAJNOWSZYM etapie
 *   pary (kandydat, rekrutacja), a „każdy ruch na nowy etap startuje z pustą
 *   stawką" (docstring endpointu). Stawka zapisana przed ruchem lądowałaby na
 *   etapie „Zweryfikowany", a nowy „CV Wysłane" zostałby z NULL — tablica
 *   robi ruch → stawkę z dokładnie tego powodu (komentarz w `KanbanBoardV2`).
 *
 * Porażka stawki NIE cofa ruchu i nie jest fatalna (lustro tablicy:
 * „Przeniesiono, ale nie udało się zapisać stawki"): ruch jest faktem,
 * którego nie da się odkręcić, a endpoint stawki stoi za bramką finansową
 * (`CandidateFinanceAccess` = wyłącznie admin) — gdyby był pierwszy i fatalny,
 * blokowałby wysyłkę każdemu poza adminem.
 *
 * Żaden krok nie jest pomijany po cichu: pominięcie jest DECYZJĄ zapisaną
 * w planie (`null` = rekruter świadomie nie podał stawki / nie chce linku),
 * a porażka przed ruchem przerywa sekwencję i mówi, co się udało do tej pory.
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
  saveClientRate: (rate: {
    value: number;
    unit: RateUnit;
    currency: string;
  }) => Promise<void>;
  createShareLink: (opts: {
    expiresInDays: number;
  }) => Promise<{ shareUrlSuffix: string | null }>;
  move: () => Promise<void>;
}

export interface CvHandoffResult {
  completed: CvHandoffStep[];
  skipped: CvHandoffStep[];
  /**
   * Kroki PO ruchu, które padły, choć ruch już się wykonał (dziś: tylko
   * stawka do klienta). Ruch jest faktem — to ostrzeżenie, nie porażka.
   */
  failedAfterMove: { step: CvHandoffStep; reason: unknown }[];
  shareUrlSuffix: string | null;
}

/** Porażka kroku PRZED ruchem — niesie, co się udało przed nią. */
export class CvHandoffError extends Error {
  readonly step: CvHandoffStep;
  readonly completed: CvHandoffStep[];
  readonly reason: unknown;
  /**
   * Sekret linku utworzonego przed porażką. Token v2 zwraca go DOKŁADNIE RAZ
   * (lista tokenów już go nie ma), więc bez tego pola padnięty ruch
   * zostawiałby żywy link, którego adresu nikt nie odtworzy.
   */
  readonly shareUrlSuffix: string | null;

  constructor(
    step: CvHandoffStep,
    completed: CvHandoffStep[],
    reason: unknown,
    shareUrlSuffix: string | null = null,
  ) {
    super(`Krok „${CV_HANDOFF_STEP_LABEL[step]}” nie powiódł się.`);
    this.name = "CvHandoffError";
    this.step = step;
    this.completed = completed;
    this.reason = reason;
    this.shareUrlSuffix = shareUrlSuffix;
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

  if (plan.shareLink) {
    try {
      const res = await deps.createShareLink(plan.shareLink);
      shareUrlSuffix = res.shareUrlSuffix;
    } catch (e) {
      throw new CvHandoffError("share_link", completed, e, null);
    }
    completed.push("share_link");
  } else {
    skipped.push("share_link");
  }

  try {
    await deps.move();
  } catch (e) {
    throw new CvHandoffError("move", completed, e, shareUrlSuffix);
  }
  completed.push("move");

  if (plan.clientRate) {
    try {
      await deps.saveClientRate(plan.clientRate);
      completed.push("client_rate");
    } catch (e) {
      failedAfterMove.push({ step: "client_rate", reason: e });
    }
  } else {
    skipped.push("client_rate");
  }

  return { completed, skipped, failedAfterMove, shareUrlSuffix };
}

/**
 * Zdanie po polsku dla sekwencji przerwanej PRZED ruchem: co padło, co
 * ZOSTAŁO zrobione i co z tym zrobić. Bez tej drugiej połowy rekruter nie
 * wie, czy powtórzenie akcji zdubluje link.
 */
export function describeCvHandoffFailure(
  error: CvHandoffError,
  detail: string,
): string {
  const head = `Nie udało się: ${CV_HANDOFF_STEP_LABEL[error.step]}${detail ? ` — ${detail}` : "."}`;
  if (error.completed.length === 0) {
    return `${head} Nic nie zostało zmienione — popraw przyczynę i spróbuj ponownie.`;
  }
  const done = error.completed.map((s) => CV_HANDOFF_STEP_LABEL[s]);
  const linkNote = error.completed.includes("share_link")
    ? " Link dla klienta JUŻ ISTNIEJE (adres w doku) — przy ponowieniu odznacz „Utwórz link”, inaczej powstanie drugi."
    : "";
  return `${head} Wcześniejsze kroki ZOSTAŁY wykonane (${done.join(", ")}).${linkNote}`;
}

/**
 * Podsumowanie sekwencji, w której ruch się wykonał — mówi też o krokach
 * świadomie pominiętych i o stawce, która padła PO ruchu (ton ostrzeżenia
 * wybiera wołający: `failedAfterMove.length > 0`).
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
  if (result.completed.includes("share_link")) {
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
