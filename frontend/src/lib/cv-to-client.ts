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

/** Gotowe CV etapu tej osoby z innych rekrutacji („Użyj innego CV”). */
export function stageCvSourcesQueryKey(stageId: number | null) {
  return ["cv-stage-sources", stageId] as const;
}

/**
 * Wiersz etapu, na którym leży CV firmowe pary, gdy bieżący wiersz go nie ma.
 *
 * Ruch na kolejną kolumnę zakłada nowy wiersz etapu bez CV, a CV zostaje na
 * wierszu, na którym powstało — serwer wskazuje go w `pair_source_stage_id`
 * (runda 11). `null` = bieżący wiersz ma własne CV albo para nie ma żadnego.
 */
export function pairSourceStageId(
  branded: { status: string; pair_source_stage_id?: number | null } | null | undefined,
): number | null {
  if (!branded || branded.status !== "none") return null;
  return branded.pair_source_stage_id ?? null;
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
  /** `document` = plik Word wybrany z profilu kandydata (09.10.2026). */
  source?: string | null;
  /** CV wybrane zamiast generacji (12.10.2026): skąd i kiedy. */
  origin?: {
    kind?: string | null;
    label?: string | null;
    selected_at?: string | null;
  } | null;
  /** Kopia bez dokumentu generatora: klient wymaga zgody, a CV jej nie ma. */
  consent_missing?: boolean;
}

/**
 * Stan CV do klienta na etapie:
 *  - `ready`   — szkic albo zatwierdzona wersja z generatora lub z pliku Word
 *                wybranego z profilu (albo stara zatwierdzona wersja —
 *                dokument, który mógł już pójść do klienta);
 *  - `legacy`  — szkic starego szablonu „CV firmowe” (HTML bez AI): tylko
 *                odczyt, podpowiedź „Wygeneruj CV”;
 *  - `none`    — nic nie ma.
 */
export type StageCvStatus = "none" | "ready" | "legacy";

export function stageCvStatus(branded: StageBrandedSummary | null | undefined): StageCvStatus {
  if (!branded || branded.status === "none") return "none";
  // Stary szablon: szkic HTML złożony bez generatora. Backend przestaje go
  // renderować i edytować (PATCH szablonu = 410), więc to już tylko podgląd.
  // Plik Word z profilu też nie pochodzi z generatora, ale jest zwykłym,
  // edytowalnym szkicem — nie starym szablonem.
  if (branded.source === "document") return "ready";
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

/**
 * Plakietka i zdanie o pochodzeniu CV wybranego zamiast generacji.
 * `null` = CV z generatora tej rekrutacji (karta mówi o nim po swojemu).
 */
export function stageCvOrigin(
  branded: StageBrandedSummary | null | undefined,
): { badge: string; tone: "neutral" | "warning"; sentence: string } | null {
  if (!branded || stageCvStatus(branded) !== "ready") return null;
  const kind = branded.origin?.kind ?? null;
  const label = branded.origin?.label?.trim() || null;
  const fromJob = label ? `z rekrutacji ${label}` : "z innej rekrutacji";
  if (kind === "reassign") {
    return {
      // Po zatwierdzeniu ktoś je już przejrzał — ostrzeżenie schodzi.
      badge:
        branded.status === "draft"
          ? `przeniesione ${fromJob} — sprawdź przed wysyłką`
          : `przeniesione ${fromJob}`,
      tone: branded.status === "draft" ? "warning" : "neutral",
      sentence: `Przeniesione przy przepięciu ${fromJob}, w wersji po poprawkach rekrutera. Nagłówek ma tytuł tej rekrutacji.`,
    };
  }
  if (kind === "stage_copy") {
    return {
      badge: fromJob,
      tone: "neutral",
      sentence: `Skopiowane ${fromJob}, w wersji po poprawkach rekrutera. Nagłówek ma tytuł tej rekrutacji.`,
    };
  }
  if (kind === "generated_other_job") {
    return {
      badge: fromJob,
      tone: "neutral",
      sentence: `CV z generatora ${fromJob}. Nagłówek ma tytuł tej rekrutacji.`,
    };
  }
  if (kind === "upload" || kind === "profile_file" || branded.source === "document") {
    return {
      badge: "z pliku Word",
      tone: "neutral",
      sentence: `Wczytane z pliku${label ? ` ${label}` : " Word"}. Treść przeniesiona bez AI — sprawdź układ w edytorze.`,
    };
  }
  return null;
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
  // CV wybrane zamiast generacji (kopia, plik) nie ma wiersza generatora,
  // więc każda gotowa generacja wyglądałaby na „nowszą”. Proponujemy tylko
  // te, które powstały PO wyborze — inaczej karta od razu radziłaby nadpisać
  // CV, które rekruter przed chwilą świadomie wskazał.
  const chosenAt = attachedId == null ? Date.parse(branded?.origin?.selected_at ?? "") : NaN;
  const olderThanChoice =
    status === "ready" &&
    Number.isFinite(chosenAt) &&
    !(Date.parse(latestReady?.created_at ?? "") > chosenAt);
  const candidate =
    latestReady &&
    latestReady.id !== attachedId &&
    (attachedId == null || latestReady.id > attachedId) &&
    !(attachedPackage != null && latestReady.package_id === attachedPackage) &&
    !olderThanChoice
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
      // Wiersz generatora mówi o swoim pakiecie; kopia bez niego — sama o sobie.
      consentMissing: attached?.consent_missing === true || branded?.consent_missing === true,
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
