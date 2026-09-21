/**
 * Zbiorcze „Wyślij CV do klienta" z tabeli rekrutacji.
 *
 * To pętla POJEDYNCZYCH przekazań — każde idzie przez `runCvHandoff`
 * (`lib/cv-handoff.ts`), więc kolejność ruch → link na etapie SPRZED ruchu →
 * stawka jest ta sama co w warsztacie „CV do klienta". Ten moduł dokłada
 * tylko to, czego pojedynczy przepływ nie potrzebuje: decyzję per osoba
 * i wynik, który da się pokazać na jednej liście.
 *
 * Reguły, które łatwo cofnąć „przy okazji":
 * - Osoba BEZ sfinalizowanego CV firmowego nie jest ruszana. Akcja zbiorcza
 *   istnieje po to, żeby powstały linki; ruch bez linku zostawiłby kandydata
 *   na „CV Wysłane", a CV firmowe na etapie, do którego nic już nie prowadzi.
 * - Ruch z nieznanym wynikiem (brak odpowiedzi, 5xx) NIGDY nie jest ponawiany:
 *   mógł się zapisać, a drugie podejście dopisałoby drugi etap „CV Wysłane".
 * - Ostrzeżenie dopuszczalności pyta człowieka RAZ na osobę; „tak" powtarza
 *   ten sam ruch z potwierdzeniem dokładnie jeden raz.
 * - Pętla jest sekwencyjna: okno ostrzeżenia dotyczy jednej osoby naraz,
 *   a serwer nie dostaje N równoległych ruchów tej samej rekrutacji.
 *
 * Czysta funkcja z wstrzykniętymi zależnościami — bez Reacta i bez API.
 */

import {
  CvHandoffError,
  isDefiniteRefusal,
  type CvHandoffPlan,
  type CvHandoffResult,
} from "@/lib/cv-handoff";
import { PIPELINE_VERSION_CONFLICT_MESSAGE } from "@/lib/pipeline-version-conflict";

export interface BulkCvHandoffPerson {
  candidateId: number;
  fullName: string;
  /** Etap SPRZED ruchu — na nim leży CV firmowe i w niego celuje link. */
  sourceStageId: number;
  clientRate: CvHandoffPlan["clientRate"];
}

export interface BulkCvHandoffDeps<P extends BulkCvHandoffPerson = BulkCvHandoffPerson> {
  /** Status CV firmowego etapu (`finalized` = można utworzyć link). */
  getBrandedStatus: (stageId: number) => Promise<string>;
  /** Owija `runCvHandoff` dla jednej osoby. */
  handoff: (person: P, acknowledgeEligibility: boolean) => Promise<CvHandoffResult>;
  /** `true` = „Przenieś mimo to". */
  askEligibility: (person: P, error: unknown) => Promise<boolean>;
  isEligibilityWarning: (error: unknown) => boolean;
  isVersionConflict: (error: unknown) => boolean;
  describeError: (error: unknown) => string;
  expiresInDays: number;
  /** Postęp pętli — wołane PRZED każdą osobą (`index` od zera). */
  onProgress?: (index: number, total: number, person: P) => void;
}

interface OutcomeBase {
  candidateId: number;
  fullName: string;
  sourceStageId: number;
}

export type BulkCvHandoffOutcome =
  /** Ruch i link się udały. `rateFailed` = stawka padła PO ruchu. */
  | (OutcomeBase & {
      kind: "linked";
      suffix: string;
      expiresInDays: number;
      rateFailed: string | null;
    })
  /** Ruch się udał, link nie — ponawialne (sam link, etap sprzed ruchu). */
  | (OutcomeBase & {
      kind: "moved_no_link";
      reason: string;
      expiresInDays: number;
      rateFailed: string | null;
    })
  /** Nic nie ruszone: brak CV firmowego albo nie dało się go sprawdzić. */
  | (OutcomeBase & { kind: "skipped"; reason: string })
  /** Użytkownik zrezygnował po ostrzeżeniu — nic nie ruszone. */
  | (OutcomeBase & { kind: "cancelled"; reason: string })
  /** Serwer jednoznacznie odmówił ruchu (4xx) — nic nie ruszone, bez linku. */
  | (OutcomeBase & { kind: "move_refused"; reason: string })
  /** Nie wiadomo, czy ruch się zapisał — bez ponowienia, bez linku. */
  | (OutcomeBase & { kind: "move_unknown"; reason: string });

export type BulkCvHandoffOutcomeKind = BulkCvHandoffOutcome["kind"];

export const BULK_CV_NO_BRANDED_REASON = "brak CV firmowego";
export const BULK_CV_CANCELLED_REASON = "anulowano po ostrzeżeniu";
export const BULK_CV_MOVE_UNKNOWN_REASON =
  "Nie wiadomo, czy ruch się zapisał — odśwież kartę kandydata, zanim spróbujesz ponownie";
export const BULK_CV_NO_LINK_ADDRESS_REASON = "Serwer nie zwrócił adresu linku.";

function withDetail(head: string, detail: string): string {
  return detail ? `${head}: ${detail}` : head;
}

export async function runBulkCvHandoff<P extends BulkCvHandoffPerson>(
  people: readonly P[],
  deps: BulkCvHandoffDeps<P>,
): Promise<BulkCvHandoffOutcome[]> {
  const outcomes: BulkCvHandoffOutcome[] = [];

  for (let index = 0; index < people.length; index += 1) {
    const person = people[index];
    deps.onProgress?.(index, people.length, person);
    outcomes.push(await handOffOne(person, deps));
  }

  return outcomes;
}

async function handOffOne<P extends BulkCvHandoffPerson>(
  person: P,
  deps: BulkCvHandoffDeps<P>,
): Promise<BulkCvHandoffOutcome> {
  const base: OutcomeBase = {
    candidateId: person.candidateId,
    fullName: person.fullName,
    sourceStageId: person.sourceStageId,
  };

  let status: string;
  try {
    status = await deps.getBrandedStatus(person.sourceStageId);
  } catch (e) {
    return {
      ...base,
      kind: "skipped",
      reason: withDetail(
        "nie udało się sprawdzić CV firmowego",
        deps.describeError(e),
      ),
    };
  }
  if (status !== "finalized") {
    return { ...base, kind: "skipped", reason: BULK_CV_NO_BRANDED_REASON };
  }

  let result: CvHandoffResult;
  try {
    result = await deps.handoff(person, false);
  } catch (first) {
    let failure: unknown = first;
    if (
      first instanceof CvHandoffError &&
      first.step === "move" &&
      deps.isEligibilityWarning(first.reason)
    ) {
      // 409 przed zapisem — ruch się nie wykonał, więc ponowienie z
      // potwierdzeniem jest bezpieczne. Dokładnie RAZ.
      if (!(await deps.askEligibility(person, first.reason))) {
        return { ...base, kind: "cancelled", reason: BULK_CV_CANCELLED_REASON };
      }
      try {
        result = await deps.handoff(person, true);
        return describeMoved(base, result, deps);
      } catch (second) {
        failure = second;
      }
    }
    return describeMoveFailure(base, failure, deps);
  }
  return describeMoved(base, result, deps);
}

function describeMoveFailure<P extends BulkCvHandoffPerson>(
  base: OutcomeBase,
  failure: unknown,
  deps: BulkCvHandoffDeps<P>,
): BulkCvHandoffOutcome {
  if (!(failure instanceof CvHandoffError) || failure.step !== "move") {
    // `runCvHandoff` rzuca wyłącznie na ruchu; cokolwiek innego padło PRZED
    // nim (przygotowanie planu), więc nic nie zostało zmienione.
    return {
      ...base,
      kind: "move_refused",
      reason: deps.describeError(failure) || "Nie udało się przygotować przekazania CV.",
    };
  }
  const reason = failure.reason;
  if (deps.isVersionConflict(reason)) {
    return { ...base, kind: "move_refused", reason: PIPELINE_VERSION_CONFLICT_MESSAGE };
  }
  if (isDefiniteRefusal(reason)) {
    return {
      ...base,
      kind: "move_refused",
      reason: deps.describeError(reason) || "Serwer odmówił przeniesienia.",
    };
  }
  return { ...base, kind: "move_unknown", reason: BULK_CV_MOVE_UNKNOWN_REASON };
}

function describeMoved<P extends BulkCvHandoffPerson>(
  base: OutcomeBase,
  result: CvHandoffResult,
  deps: BulkCvHandoffDeps<P>,
): BulkCvHandoffOutcome {
  const rateFailure = result.failedAfterMove.find((f) => f.step === "client_rate");
  const rateFailed = rateFailure
    ? deps.describeError(rateFailure.reason) || "nie udało się zapisać stawki do klienta"
    : null;

  if (result.shareUrlSuffix) {
    return {
      ...base,
      kind: "linked",
      suffix: result.shareUrlSuffix,
      expiresInDays: deps.expiresInDays,
      rateFailed,
    };
  }
  const linkFailure = result.failedAfterMove.find((f) => f.step === "share_link");
  return {
    ...base,
    kind: "moved_no_link",
    reason: linkFailure
      ? deps.describeError(linkFailure.reason) || "nie udało się utworzyć linku"
      : BULK_CV_NO_LINK_ADDRESS_REASON,
    expiresInDays: deps.expiresInDays,
    rateFailed,
  };
}
