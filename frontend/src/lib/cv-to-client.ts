/**
 * „CV do klienta” — czysta reguła stanu karty w panelu osoby i plakietek na
 * profilu / w doku kanbana (generator CV v3).
 *
 * Źródła są dwa i oba już istnieją:
 *  - CV etapu (`GET /api/candidates/stages/{id}/cv/branded`) — szkic albo
 *    zatwierdzona wersja, którą rekruter edytuje i pobiera;
 *  - lista wygenerowanych CV tej pary (`GET /api/cv-generator/generated
 *    ?candidate_id&job_id`) — generacje w toku, gotowe, auto-CV, zgoda RODO
 *    i kontrola AI.
 *
 * Serwer podpina gotowe CV do etapu sam, gdy etap nie ma jeszcze szkicu
 * (`attach_as_stage_draft`). Karta tylko opisuje stan — niczego nie blokuje:
 * ruch na „CV wysłane” działa niezależnie od niej („Kanban bez bramek”).
 * Zgoda RODO blokuje wyłącznie POBRANIE pliku (serwer odpowiada 409).
 */

/** Lista wygenerowanych CV pary — prefiks `cv-generated` jak reszta generatora
 *  (dołączenie zgody i nowa generacja unieważniają go hurtem). */
export function cvToClientRowsQueryKey(candidateId: number, jobId: number) {
  return ["cv-generated", "to-client", candidateId, jobId] as const;
}

/** CV etapu — klucz wspólny z edytorem, dokiem kanbana, profilem i warsztatem. */
export function stageBrandedQueryKey(stageId: number | null) {
  return ["cv-branded", stageId] as const;
}

/** Minimalny kształt odpowiedzi `GET /api/cv-generator/generated`. */
export interface StageGeneratedCvRow {
  id: number;
  status: "processing" | "ready" | "failed" | string;
  filename?: string | null;
  origin?: string | null;
  stage_id?: number | null;
  package_id?: number | null;
  needs_review?: boolean;
  language?: string | null;
  content_mode?: string | null;
  created_at?: string | null;
  error_message?: string | null;
  factual_review?: {
    status: "verified" | "advisory" | "unavailable" | string;
    findings?: number;
  } | null;
  /** Reguła klienta wymaga zrzutu zgody RODO (dziś PKO BP). */
  consent_required?: boolean;
  /** …i dokument go nie ma — pobranie odpowie 409 `consent_required`. */
  consent_missing?: boolean;
}

/** Część `CVBrandedState`, której karta potrzebuje. */
export interface StageBrandedSummary {
  status: "none" | "draft" | "finalized" | string;
  from_generator?: boolean;
  generated_document_id?: number | null;
}

/**
 * Stan CV do klienta na etapie:
 *  - `ready`   — szkic albo zatwierdzona wersja z generatora (albo stara
 *                zatwierdzona wersja — dokument, który mógł już pójść do klienta);
 *  - `legacy`  — szkic starego szablonu „CV firmowe” (HTML bez AI): tylko
 *                odczyt, podpowiedź „Wygeneruj CV”;
 *  - `none`    — nic nie ma.
 */
export type StageCvStatus = "none" | "ready" | "legacy";

export function stageCvStatus(branded: StageBrandedSummary | null | undefined): StageCvStatus {
  if (!branded || branded.status === "none") return "none";
  // Stary szablon: szkic HTML złożony bez generatora. Backend przestaje go
  // renderować i edytować (PATCH szablonu = 410), więc to już tylko podgląd.
  if (branded.status === "draft" && branded.from_generator !== true) return "legacy";
  return "ready";
}

/**
 * Etykieta plakietki „CV do klienta: …” (profil kandydata, dok kanbana).
 * `null` = nic nie pokazujemy (brak CV to nie plakietka, tylko przycisk).
 */
export function stageCvBadge(
  branded: StageBrandedSummary | null | undefined,
): { label: string; tone: "success" | "info" | "neutral" } | null {
  const status = stageCvStatus(branded);
  if (status === "none") return null;
  if (status === "legacy") return { label: "CV do klienta: stary szablon", tone: "neutral" };
  return branded?.status === "finalized"
    ? { label: "CV do klienta: gotowe", tone: "success" }
    : { label: "CV do klienta: szkic", tone: "info" };
}

export type CvToClientKind =
  | "ready"
  | "legacy"
  | "generating"
  | "unattached"
  | "failed"
  | "none";

export interface CvToClientState {
  kind: CvToClientKind;
  /** Wiersz generacji, z której pochodzi CV etapu (jeśli jest na liście). */
  attached: StageGeneratedCvRow | null;
  /**
   * Gotowa generacja, której etap NIE używa i która jest nowsza od podpiętej
   * (poza drugim językiem z tego samego pakietu). Karta proponuje „Użyj nowej
   * wersji”. Przy `unattached` to wiersz do podpięcia.
   */
  candidate: StageGeneratedCvRow | null;
  /** Generacja w toku (ręczna albo auto-CV). */
  generating: StageGeneratedCvRow | null;
  /** Nieudana generacja zlecona z tej karty. */
  failed: StageGeneratedCvRow | null;
  /** Dokument etapu nie ma zrzutu zgody, której wymaga reguła klienta. */
  consentMissing: boolean;
  /** Liczba uwag niezależnej kontroli AI (0 = brak albo kontrola nie biegła). */
  findings: number;
  /** Auto-CV, którego nikt jeszcze nie przejrzał. */
  needsReview: boolean;
}

function byNewest(rows: readonly StageGeneratedCvRow[]): StageGeneratedCvRow[] {
  return [...rows].sort((a, b) => b.id - a.id);
}

export function resolveCvToClient({
  branded,
  rows,
  pendingGeneratedId = null,
}: {
  branded: StageBrandedSummary | null | undefined;
  rows: readonly StageGeneratedCvRow[] | null | undefined;
  /** Id generacji zleconej z tej karty — czekamy, aż serwer ją podepnie. */
  pendingGeneratedId?: number | null;
}): CvToClientState {
  const list = byNewest(rows ?? []);
  const status = stageCvStatus(branded);
  const attachedId = branded?.generated_document_id ?? null;
  const attached = attachedId != null ? (list.find((r) => r.id === attachedId) ?? null) : null;
  const generating = list.find((r) => r.status === "processing") ?? null;
  const pending = pendingGeneratedId != null
    ? (list.find((r) => r.id === pendingGeneratedId) ?? null)
    : null;
  const latestReady = list.find((r) => r.status === "ready") ?? null;
  const attachedPackage = attached?.package_id ?? null;
  const candidate =
    latestReady &&
    latestReady.id !== attachedId &&
    (attachedId == null || latestReady.id > attachedId) &&
    !(attachedPackage != null && latestReady.package_id === attachedPackage)
      ? latestReady
      : null;

  const base = {
    attached,
    candidate,
    generating,
    failed: null as StageGeneratedCvRow | null,
    consentMissing: false,
    findings: 0,
    needsReview: false,
  };

  if (status === "ready") {
    const findings =
      attached?.factual_review?.status === "advisory"
        ? Math.max(0, attached.factual_review.findings ?? 0)
        : 0;
    return {
      ...base,
      kind: "ready",
      consentMissing: attached?.consent_missing === true,
      findings,
      needsReview: attached?.needs_review === true,
    };
  }
  if (generating) return { ...base, kind: "generating" };
  if (pending?.status === "failed") return { ...base, kind: "failed", failed: pending };
  if (status === "legacy") return { ...base, kind: "legacy" };
  // Gotowe CV bez podpięcia (np. serwer nie podpiął, bo etap miał wtedy
  // szkic, albo generacja poszła bez etapu) — jedno kliknięcie je podpina.
  if (candidate) {
    return { ...base, kind: "unattached", consentMissing: candidate.consent_missing === true };
  }
  return { ...base, kind: "none" };
}

/** Czy karta ma dalej odpytywać serwer (generacja w toku albo czekamy na podpięcie). */
export function cvToClientShouldPoll(
  state: CvToClientState,
  pendingGeneratedId: number | null,
): boolean {
  // Generacja w toku — także obok gotowego CV („Wygeneruj ponownie”): nowa
  // wersja ma się pojawić sama jako „Użyj nowej wersji”.
  if (state.generating) return true;
  if (pendingGeneratedId == null) return false;
  // Zleciliśmy generację z tej karty: dopóki wiersza nie widać albo etap nie
  // dostał jeszcze szkicu, pytamy dalej (serwer podpina CV chwilę PO tym, jak
  // wiersz jest już „ready”). Porażka i podpięte CV kończą odpytywanie; sufit
  // czasu trzyma wołający — etap ze starym szkicem nie dostanie podpięcia nigdy.
  return state.kind === "none" || state.kind === "unattached" || state.kind === "legacy";
}
