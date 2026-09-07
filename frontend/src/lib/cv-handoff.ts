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
 * Kolejność jest LOAD-BEARING: `client-rate → share-token → move`.
 * Ruch na `cv_sent` tworzy po stronie backendu NOWY `CandidateStage`, a link
 * dla klienta jest przypięty do etapu, na którym leży sfinalizowane CV
 * brandowane. Link tworzony PO ruchu celowałby w świeży etap bez dokumentu
 * (409 „brak sfinalizowanego CV"), więc jedyną poprawną kolejnością jest ta,
 * w której link powstaje jeszcze na etapie „Zweryfikowany".
 *
 * Żaden krok nie jest pomijany po cichu: pominięcie jest DECYZJĄ zapisaną
 * w planie (`null` = rekruter świadomie nie podał stawki / nie chce linku),
 * a porażka przerywa sekwencję i mówi, co się udało do tej pory.
 */

import type { RateUnit } from "@/lib/api";

export type CvHandoffStep = "client_rate" | "share_link" | "move";

export const CV_HANDOFF_STEP_LABEL: Record<CvHandoffStep, string> = {
  client_rate: "zapis stawki do klienta",
  share_link: "utworzenie linku dla klienta",
  move: "przeniesienie na „CV Wysłane”",
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
  shareUrlSuffix: string | null;
}

/** Porażka JEDNEGO kroku — niesie, co się udało przed nią. */
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
  let shareUrlSuffix: string | null = null;

  if (plan.clientRate) {
    try {
      await deps.saveClientRate(plan.clientRate);
    } catch (e) {
      throw new CvHandoffError("client_rate", completed, e);
    }
    completed.push("client_rate");
  } else {
    skipped.push("client_rate");
  }

  if (plan.shareLink) {
    try {
      const res = await deps.createShareLink(plan.shareLink);
      shareUrlSuffix = res.shareUrlSuffix;
    } catch (e) {
      throw new CvHandoffError("share_link", completed, e);
    }
    completed.push("share_link");
  } else {
    skipped.push("share_link");
  }

  try {
    await deps.move();
  } catch (e) {
    throw new CvHandoffError("move", completed, e);
  }
  completed.push("move");

  return { completed, skipped, shareUrlSuffix };
}

/**
 * Zdanie po polsku dla przerwanej sekwencji: co padło, co ZOSTAŁO zrobione
 * i co z tym zrobić. Bez tej drugiej połowy rekruter nie wie, czy powtórzenie
 * akcji zdubluje stawkę albo link.
 */
export function describeCvHandoffFailure(
  error: CvHandoffError,
  detail: string,
): string {
  const done = error.completed.map((s) => CV_HANDOFF_STEP_LABEL[s]);
  const head = `Nie udało się: ${CV_HANDOFF_STEP_LABEL[error.step]}${detail ? ` — ${detail}` : "."}`;
  if (done.length === 0) {
    return `${head} Nic nie zostało zmienione — popraw przyczynę i spróbuj ponownie.`;
  }
  return `${head} Wcześniejsze kroki ZOSTAŁY wykonane (${done.join(", ")}) — powtórzenie akcji je powtórzy.`;
}

/** Podsumowanie udanej sekwencji — mówi też o krokach świadomie pominiętych. */
export function describeCvHandoffSuccess(result: CvHandoffResult): string {
  const parts = ["Kandydat przeniesiony na „CV Wysłane”."];
  if (result.completed.includes("client_rate")) {
    parts.push("Stawka do klienta zapisana.");
  } else {
    parts.push("Bez stawki do klienta — uzupełnij ją później na karcie rekrutacji.");
  }
  if (result.completed.includes("share_link")) {
    parts.push("Link dla klienta utworzony.");
  } else {
    parts.push("Bez linku dla klienta.");
  }
  return parts.join(" ");
}
