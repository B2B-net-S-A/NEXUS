/**
 * Podtytuł jobbara rekrutacji (makieta „flow w języku C2", k2–k8).
 *
 * Jedna linia zamiast rzędu odznak z ikonami:
 * `Warszawa / hybryda · budżet do 122,50 PLN/h · deadline 30.09 · Marta K.`
 *
 * Czysta funkcja zwracająca SEGMENTY, nie gotowy JSX — dzięki temu test
 * sprawdza treść, a nie sposób jej złamania na wiersze, a warstwa widoku
 * decyduje, czym je rozdzielić.
 *
 * Segment, którego nie ma, po prostu NIE WYCHODZI. Nie ma tu wartości
 * zastępczych typu „—": podtytuł jest ciągiem faktów, a pusty myślnik między
 * dwoma kropkami czyta się jak fakt, którego nikt nie podał.
 * Jedyny wyjątek to właściciel — jego brak jest sprawą do załatwienia (nikt
 * nie dostanie alertów deadline'u), więc mówimy o nim wprost.
 */

/** Etykiety trybu pracy — lustro `RemotePolicy` (`backend/app/models/job.py`). */
const REMOTE_POLICY_LABEL: Record<string, string> = {
  onsite: "stacjonarnie",
  hybrid: "hybryda",
  remote: "zdalnie",
};

/**
 * „Marta Kowalska" → „Marta K.".
 *
 * Nagłówek ma jedną linię na cztery fakty, więc nazwisko skraca się do
 * inicjału — imię zostaje w całości, bo to po nim rozpoznaje się osobę
 * w rozmowie. Nazwisko jednoczłonowe zostaje jak jest (nie ma czego skracać),
 * wieloczłonowe („Anna Nowak-Kowalska") skraca się do pierwszej litery
 * pierwszego członu, tak jak zapisuje się je w mailu.
 */
export function shortenPersonName(name: string | null | undefined): string | null {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length < 2) return trimmed;
  const last = parts[parts.length - 1];
  const initial = last.slice(0, 1).toLocaleUpperCase("pl-PL");
  return `${parts.slice(0, -1).join(" ")} ${initial}.`;
}

/** `2026-09-30` → `30.09`. Rok pomijamy — nagłówek mówi o bieżącej pracy. */
export function formatDeadlineShort(
  deadline: string | null | undefined,
): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(deadline ?? "");
  if (!match) return null;
  const [, , month, day] = match;
  return `${day}.${month}`;
}

/** `122.5` → `122,50` (waluta dopisuje wołający). */
function formatRate(value: number): string {
  return value.toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** `15000`, `20000` → `15 000–20 000 PLN`; jedna granica też ma sens. */
function formatSalaryRange(
  min: number | null | undefined,
  max: number | null | undefined,
): string | null {
  const fmt = (v: number) => v.toLocaleString("pl-PL");
  if (typeof min === "number" && typeof max === "number") {
    return `${fmt(min)}–${fmt(max)} PLN`;
  }
  if (typeof min === "number") return `od ${fmt(min)} PLN`;
  if (typeof max === "number") return `do ${fmt(max)} PLN`;
  return null;
}

export interface JobHeaderSubtitleInput {
  location?: string | null;
  remotePolicy?: string | null;
  /**
   * Twardy sufit stawki kandydackiej. Pole podlega redakcji finansowej — rola
   * bez uprawnień dostaje je jako `null` i wtedy segment po prostu nie
   * wychodzi (kwota zastąpiona myślnikiem sugerowałaby, że jej nie ustalono).
   */
  rateBudgetHourly?: number | null;
  /**
   * Widełki z ogłoszenia — DAWNA odznaka nagłówka, przeniesiona do tej linii.
   * To inna liczba niż `rateBudgetHourly` (sufit z Championa dla kandydata),
   * więc oba segmenty wychodzą obok siebie, a nie zamiast siebie.
   */
  salaryMin?: number | null;
  salaryMax?: number | null;
  deadline?: string | null;
  ownerName?: string | null;
  /** Krok 07 — hiring manager jest tam decydentem, nie ciekawostką. */
  hiringManagerName?: string | null;
  /** Krok 08 — ilu z `headcount` etatów jest już obsadzonych. */
  hired?: number | null;
  headcount?: number | null;
}

export function buildJobHeaderSubtitle({
  location,
  remotePolicy,
  rateBudgetHourly,
  salaryMin,
  salaryMax,
  deadline,
  ownerName,
  hiringManagerName,
  hired,
  headcount,
}: JobHeaderSubtitleInput): string[] {
  const segments: string[] = [];

  const place = (location ?? "").trim();
  const mode = remotePolicy ? REMOTE_POLICY_LABEL[remotePolicy] : undefined;
  if (place && mode) segments.push(`${place} / ${mode}`);
  else if (place) segments.push(place);
  else if (mode) segments.push(mode);

  if (typeof rateBudgetHourly === "number" && rateBudgetHourly > 0) {
    segments.push(`budżet do ${formatRate(rateBudgetHourly)} PLN/h`);
  }

  const salary = formatSalaryRange(salaryMin, salaryMax);
  if (salary) segments.push(salary);

  const due = formatDeadlineShort(deadline);
  if (due) segments.push(`deadline ${due}`);

  const owner = shortenPersonName(ownerName);
  segments.push(owner ?? "właściciel: nieprzypisany");

  // Hiring manager idzie PEŁNYM nazwiskiem, w odróżnieniu od właściciela:
  // to osoba po stronie klienta, o której rozmawia się z klientem — inicjał
  // zmuszałby do sprawdzania, kto to, zanim się o niej napisze.
  const manager = (hiringManagerName ?? "").trim();
  if (manager) segments.push(`HM: ${manager} (decydent)`);

  if (typeof hired === "number" && typeof headcount === "number") {
    segments.push(`obsada ${hired} / ${headcount}`);
  }

  return segments;
}
