"use client";

/**
 * QC CV (Rekrutacja v5, decyzje Artura 23.09.2026 i 02.10.2026) — kontrola CV
 * firmowego przed „CV wysłane” / Cpro.
 *
 * Po lewej CV z bloków tekstu (pogrubienia jak w dokumencie; żółte = termin,
 * który powinien być pogrubiony; czerwona krawędź = stanowisko bez opisu
 * umiejętności krytycznej, bursztynowa = brak, który nie blokuje). Po prawej
 * trzy grupy: „Do poprawy przed wysłaniem” (jedna karta na rzecz, z przyciskiem
 * naprawy), „Warto poprawić — nie blokuje” i zwinięte „W porządku”. Blokują
 * tylko: brak CV, umiejętności krytyczne, treści spoza oryginału i reguły
 * klienta. Poprawki AI (GPT-6 Luna) pokazują źródło — rekruter je akceptuje,
 * edytuje albo odrzuca. Każda zmiana zwraca świeży wynik QC. Od 14.10.2026
 * (D5) propozycje ładują się same, gdy QC ma pozycję z poprawką AI — serwer
 * liczy je zaraz po automacie, więc zwykle to odczyt z pamięci.
 *
 * Karta krytycznej w roli pokazuje dowód z oryginału (zdanie z opisu roli,
 * lista technologii albo nazwa stanowiska) — bez zdania w oryginale karta każe
 * zapytać kandydata (AI ułoży zdanie dopiero z notatek). Treść spoza oryginału da się
 * zamknąć przez „Potwierdzone z kandydatem”: serwer zapisuje notatkę pary,
 * a lista potwierdzeń stoi pod ramką „Co sprawdza QC”.
 *
 * Treść CV, dowodów i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 * „Przepuść mimo QC” widzą tylko osoby z uprawnieniem „Rekrutacje: zakładanie,
 * zamykanie, wysyłka CV do klienta” (serwer i tak odmawia reszcie). W trybie
 * doradczym (`advisory`, 12.10.2026) QC nie blokuje: kto może, mówi serwer
 * (`can_override`), przycisk nazywa się „Przesuń mimo uwag…”, a po zapisaniu
 * powodu karta od razu idzie dalej.
 *
 * „To nieprawda” (D5, 13.10.2026) pomija pozycję dla pary — uwagę blokującą
 * tylko ta sama osoba, która może przesunąć kartę mimo uwag (`can_override`).
 * Pominięte stoją zwinięte w „Pominięte” z „Przywróć”; uwagi wyciszone
 * w „Jakość QC” (D6) — osobno, jako informacja.
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ArrowRight, CheckCircle2, ExternalLink, Loader2, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/Toast";
import { QcOverrideDialog } from "@/components/v2/recruitment/QcOverrideDialog";
import {
  AiFixesView,
  CheckRow,
  Confirmations,
  DismissedSection,
  MutedChecks,
  PassedChecks,
  QcWordFileNote,
  SECTION_TITLE,
  TaskCard,
  qcDismissedEntries,
  type ActionContext,
} from "@/components/v2/recruitment/cv-qc-cards";
import { apiErrorMessage } from "@/lib/api-error";
import {
  invalidateAfterQcChange,
  useCvQc,
  useCvQcFixes,
  useQcApply,
  useQcConfirm,
  useQcDismiss,
  useQcRestore,
  cvQcFixesQueryKey,
  type QcApplyBody,
  type QcCvRun,
  type QcFix,
  type QcFixesResponse,
  type QcResult,
} from "@/lib/api/cvQc";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  CV_NOT_EDITABLE_CODE,
  CV_NOT_EDITABLE_MESSAGE,
  QC_CV_SOURCE_LABEL,
  RODO_SECTION,
  apiErrorCode,
  candidateQuestion,
  highlightTerms,
  qcDismissedMessage,
  roleGaps,
  segmentCv,
  splitChecks,
  taskPendingItem,
  taskTitle,
  thingsLabel,
  unboldedTerms,
  type RoleGap,
} from "@/lib/cv-qc";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const CVBrandedEditModal = dynamic(
  () =>
    import("@/components/v2/modals/CVBrandedEditModal").then(
      (m) => m.CVBrandedEditModal,
    ),
  { ssr: false },
);

/**
 * Który dokument otworzyć w edytorze z wyniku QC (runda 10, F22). Link do
 * panelu osoby prowadził w QC CV do podglądu tylko do odczytu: warsztat CV
 * panelu obsługuje kolumnę „Zweryfikowany”, a CV firmowe leży na etapie,
 * na którym powstało. Edytor otwiera się więc na DOKUMENCIE, który QC
 * sprawdził — CV etapu albo gotowe CV z generatora.
 */
export function qcEditorTarget(
  cv: QcResult["cv"] | null | undefined,
): { stageId: number } | { generatedId: number } | null {
  if (!cv || !cv.editable) return null;
  if ((cv.source === "branded_draft" || cv.source === "branded_finalized") && cv.stage_id != null) {
    return { stageId: cv.stage_id };
  }
  if (cv.source === "generated" && cv.generated_document_id != null) {
    return { generatedId: cv.generated_document_id };
  }
  return null;
}

export interface CvQcDialogProps {
  stageId: number | null;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  /**
   * „Przesuń dalej →” w stopce: wołający zamyka okno i otwiera swoje
   * „Przesuń dalej” (ruch etapu ma jedną drogę). Bez niego przycisku nie ma.
   */
  onMoveNext?: (result: QcResult) => void;
}

// ── CV po lewej ──────────────────────────────────────────────────────────────

function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  return (
    <>
      {highlightTerms(text, terms).map((part, i) =>
        part.match ? (
          <mark
            key={i}
            className="rounded-sm border-b-2 border-warning bg-warning-muted px-0.5 text-warning-muted-foreground"
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

function Runs({ runs, terms }: { runs: QcCvRun[]; terms: string[] }) {
  return (
    <>
      {runs.map((run, j) =>
        run.b ? (
          <strong key={j} className="font-semibold">
            {/* Pogrubione już jest — żółte tylko tam, gdzie pogrubienia brak. */}
            {run.t}
          </strong>
        ) : (
          <Highlighted key={j} text={run.t} terms={terms} />
        ),
      )}
    </>
  );
}

function GapNote({ gap }: { gap: RoleGap }) {
  const rest = gap.requirements.filter((r) => !gap.blocking.includes(r));
  return (
    <>
      {gap.blocking.length > 0 ? (
        <p className="mt-0.5 text-[11px] font-semibold text-destructive">
          {gap.blocking.join(", ")} — w oryginale jest w tej roli, tu brakuje opisu
        </p>
      ) : null}
      {rest.length > 0 ? (
        <p className="mt-0.5 text-[11px] font-medium text-warning-muted-foreground">
          {rest.join(", ")} — w oryginale jest w tej roli, tu brakuje opisu (nie blokuje)
        </p>
      ) : null}
    </>
  );
}

function CvPaper({ data }: { data: QcResult }) {
  const cv = data.cv;
  const terms = useMemo(() => unboldedTerms(data.checks), [data.checks]);
  const segments = useMemo(
    () => (cv ? segmentCv(cv.blocks, roleGaps(data.checks)) : []),
    [cv, data.checks],
  );
  if (!cv) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
        Dla tej osoby nie ma jeszcze CV firmowego — wygeneruj je, a QC sprawdzi je od razu.
      </p>
    );
  }
  if (cv.blocks.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
        Nie udało się odczytać treści CV{cv.filename ? ` (${cv.filename})` : ""} — otwórz plik w edytorze.
      </p>
    );
  }
  return (
    <article
      aria-label="CV firmowe"
      className="mx-auto max-w-[560px] space-y-1.5 rounded-md border border-border bg-card px-6 py-5 text-sm leading-relaxed shadow-xs"
    >
      {segments.map((segment, s) => {
        const blocking = (segment.gap?.blocking.length ?? 0) > 0;
        return (
          <div
            key={s}
            data-qc-gap={segment.gap ? (blocking ? "blocking" : "note") : undefined}
            className={cn(
              segment.gap && "-ml-3 border-l-[3px] pl-2.5",
              segment.gap && (blocking ? "border-destructive" : "border-warning"),
            )}
          >
            {segment.blocks.map((block, i) => {
              if (block.section === RODO_SECTION) {
                // Klauzula zgody stoi pod ostatnią rolą, ale nie jest jej treścią.
                return (
                  <p key={i} data-qc-rodo="true" className="pt-3 text-xs leading-snug text-muted-foreground">
                    {block.runs.map((run) => run.t).join("")}
                  </p>
                );
              }
              if (block.kind === "h") {
                return (
                  <h4
                    key={i}
                    className="pt-3 text-xs font-semibold uppercase tracking-wider text-primary first:pt-0"
                  >
                    <Runs runs={block.runs} terms={terms} />
                  </h4>
                );
              }
              if (block.kind === "li") {
                return (
                  <p key={i} className="flex gap-2 pl-1">
                    <span aria-hidden className="text-muted-foreground">
                      •
                    </span>
                    <span className="min-w-0">
                      <Runs runs={block.runs} terms={terms} />
                    </span>
                  </p>
                );
              }
              return (
                <p key={i} className={cn(block.section === "role" && "pt-2 font-medium")}>
                  <Runs runs={block.runs} terms={terms} />
                </p>
              );
            })}
            {segment.gap ? <GapNote gap={segment.gap} /> : null}
          </div>
        );
      })}
    </article>
  );
}

const championHref = (data: QcResult) => `/jobs/${data.job_id}?tab=champion`;

/** Co QC sprawdza i które umiejętności są krytyczne w tej rekrutacji. */
function Explainer({ data }: { data: QcResult }) {
  const critical = data.client_request.critical ?? [];
  const source = data.client_request.critical_source ?? "none";
  const champion = (
    <Link
      href={championHref(data)}
      target="_blank"
      rel="noreferrer"
      className="font-medium underline underline-offset-2"
    >
      profilu Championa
    </Link>
  );
  return (
    <section
      aria-label="Co sprawdza QC"
      className="space-y-1 rounded-lg border border-info/30 bg-info-muted px-3 py-2 text-xs leading-relaxed text-info-muted-foreground"
    >
      <p>
        <strong className="font-semibold">Co sprawdza QC:</strong> czy CV firmowe opisuje umiejętności krytyczne tej
        rekrutacji i czy nie mówi nic ponad oryginalne CV kandydata. Reszta to podpowiedzi — nie zatrzymują wysyłki.
      </p>
      {data.advisory ? (
        <p>
          QC doradza: możesz przesunąć kartę mimo uwag — Delivery Lead zobaczy, co zostało niepoprawione, i może
          cofnąć ją do poprawy.
        </p>
      ) : null}
      {critical.length > 0 ? (
        <p>
          Umiejętności krytyczne: <strong className="font-semibold">{critical.join(", ")}</strong>
          {source === "dl" ? (
            " — wybór Delivery Leada."
          ) : (
            <> — podpowiedź z historii rekrutacji. Delivery Lead może je zmienić w {champion}.</>
          )}{" "}
          Opis jest wymagany tylko w tych rolach, w których oryginalne CV opisuje tę umiejętność w opisie roli — sama lista technologii to informacja.
        </p>
      ) : (
        <p>
          Ta rekrutacja nie ma umiejętności krytycznych — zatrzymują tylko treści spoza oryginału i reguły klienta.
          Delivery Lead wybiera je w {champion}.
        </p>
      )}
    </section>
  );
}

function AiFixes({ stageId, ctx }: { stageId: number; ctx: ActionContext }) {
  const queryClient = useQueryClient();
  // D5: bez kliknięcia — sekcja stoi tylko przy pozycji z poprawką AI.
  const fixes = useCvQcFixes(stageId, ctx.editable);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const data = fixes.data;
  const visible = (data?.fixes ?? []).filter((f) => !dismissed.has(f.id));

  const applyFix = (fix: QcFix, text?: string) => {
    const body: QcApplyBody = text ? { action: "ai_fix", fix_id: fix.id, text } : { action: "ai_fix", fix_id: fix.id };
    // Zastosowana poprawka znika z listy; pozostałe zostają do decyzji.
    ctx.apply(body, "Poprawka zastosowana — QC przeliczone.", () =>
      queryClient.setQueryData<QcFixesResponse>(cvQcFixesQueryKey(stageId), (prev) =>
        prev ? { ...prev, fixes: prev.fixes.filter((f) => f.id !== fix.id) } : prev,
      ),
    );
  };

  return (
    <AiFixesView
      sectionId={`qc-ai-${stageId}`}
      ctx={ctx}
      data={data}
      loading={fixes.isFetching && !data}
      failed={fixes.isError}
      visible={visible}
      onRetry={() => void fixes.refetch()}
      onApply={applyFix}
      onDismiss={(id) => setDismissed((prev) => new Set(prev).add(id))}
    />
  );
}

// ── Okno ─────────────────────────────────────────────────────────────────────

const LOAD_ERROR: Record<string, string> = {
  forbidden: "Nie masz dostępu do tej rekrutacji.",
  not_found: "Ten etap kandydata już nie istnieje — odśwież Tablicę.",
  error: "Nie udało się policzyć QC. Spróbuj ponownie.",
};

/** Kolejność jak na Tablicy (`pair_statuses`): zaliczone wygrywa z dawnym obejściem. */
function Verdict({ data }: { data: QcResult }) {
  if (data.passed) {
    return (
      <Badge variant="success" size="lg">
        QC przechodzi
      </Badge>
    );
  }
  if (data.override) {
    return (
      <Badge variant="warning" size="lg">
        Przepuszczone mimo QC
      </Badge>
    );
  }
  return (
    <Badge variant="danger" size="lg">
      Do poprawy: {thingsLabel(data.blocking_failed)}
    </Badge>
  );
}

export function CvQcBody({
  data,
  stageId,
  onChanged,
  onOpenEditor,
}: {
  data: QcResult;
  stageId: number;
  onChanged?: () => void;
  /** Otwiera edytor sprawdzanego CV — brak, gdy CV nie da się edytować w NEXUSIE. */
  onOpenEditor?: () => void;
}) {
  const { showSuccess, showError } = useToast();
  const apply = useQcApply(stageId, onChanged);
  const confirm = useQcConfirm(stageId, onChanged);
  const dismiss = useQcDismiss(stageId, onChanged);
  const restore = useQcRestore(stageId, onChanged);
  // Jak „Przepuść mimo QC”: w podglądzie jako inny użytkownik — nikomu.
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const [notEditable, setNotEditable] = useState(false);
  const editable = !notEditable && data.cv?.editable !== false && data.cv != null;

  const ctx: ActionContext = {
    data,
    editable,
    busy: apply.isPending,
    apply: (body, success, onApplied) =>
      apply.mutate(body, {
        onSuccess: () => {
          showSuccess(success);
          onApplied?.();
        },
        onError: (error) => {
          if (apiErrorCode(error) === CV_NOT_EDITABLE_CODE) {
            setNotEditable(true);
            showError(CV_NOT_EDITABLE_MESSAGE);
          } else {
            showError(apiErrorMessage(error, "Nie udało się zastosować poprawki. Spróbuj ponownie."));
          }
        },
      }),
    confirm: (body, onSaved) =>
      confirm.mutate(body, {
        onSuccess: () => {
          showSuccess("Potwierdzenie zapisane w notatkach kandydata — QC przeliczone.");
          onSaved?.();
        },
        onError: (error) =>
          showError(apiErrorMessage(error, "Nie udało się zapisać potwierdzenia. Spróbuj ponownie.")),
      }),
    confirming: confirm.isPending,
    requestAiFixes: () => {
      if (typeof document !== "undefined") {
        document.getElementById(`qc-ai-${stageId}`)?.scrollIntoView?.({ block: "nearest" });
      }
    },
    copyQuestion: (item) => {
      const question = candidateQuestion(item);
      void copyTextToClipboard(question).then((ok) =>
        ok
          ? showSuccess("Pytanie skopiowane — wyślij je kandydatowi.")
          : showError(`Przeglądarka nie pozwoliła skopiować. Pytanie: ${question}`),
      );
    },
    openEditor: editable && onOpenEditor ? onOpenEditor : null,
    dismiss: (body, onSaved) =>
      dismiss.mutate(body, {
        onSuccess: () => {
          showSuccess(qcDismissedMessage(body.reason));
          onSaved?.();
        },
        onError: (error) =>
          showError(apiErrorMessage(error, "Nie udało się zapisać pominięcia. Spróbuj ponownie.")),
      }),
    dismissing: dismiss.isPending,
    canDismissBlocking: !impersonating && data.can_override === true,
    restore: (dismissalId) =>
      restore.mutate(dismissalId, {
        onSuccess: () => showSuccess("Uwaga przywrócona — QC przeliczone."),
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się przywrócić uwagi. Spróbuj ponownie.")),
      }),
    restoring: restore.isPending,
  };

  const { tasks, notes, muted, passed, skipped } = useMemo(() => splitChecks(data.checks), [data.checks]);
  // Zdania AI dopisuje do ról — także wtedy, gdy QC już przechodzi, a brak
  // opisu jest tylko uwagą.
  const hasAiGaps = data.checks.some((c) => c.status === "fail" && c.items.some((i) => i.fix === "ai"));
  const tasksTitle = data.advisory ? "Zalecane poprawki przed wysłaniem" : "Do poprawy przed wysłaniem";

  return (
    // `min-h-0` tylko od `lg`: w jednej kolumnie (telefon) wiersze siatki
    // z zerową wysokością minimalną dzieliły okno po połowie i panele
    // nachodziły na siebie — tam przewija się całe okno.
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:overflow-hidden">
      <div className="border-b border-border bg-muted/30 p-4 lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
        {!editable && data.cv ? (
          <p role="status" className="mb-3 rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            {CV_NOT_EDITABLE_MESSAGE}
          </p>
        ) : null}
        {data.cv?.bold_known === false ? (
          <p className="mb-3 text-xs text-muted-foreground">
            CV w PDF — pogrubień nie da się odczytać, sprawdzenia pogrubienia są do zrobienia ręcznie.
          </p>
        ) : null}
        <CvPaper data={data} />
      </div>
      <div className="space-y-3 p-4 lg:min-h-0 lg:overflow-y-auto">
        <Explainer data={data} />
        <Confirmations items={data.confirmations ?? []} />
        {data.override && !data.passed ? (
          <p role="status" className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            Przepuszczone mimo QC{data.override.by_name ? ` przez ${data.override.by_name}` : ""}
            {data.override.at ? ` (${formatDate(data.override.at)})` : ""}: {data.override.reason}
          </p>
        ) : null}
        {tasks.length > 0 ? (
          <section aria-label={tasksTitle} className="space-y-2">
            <h3 className={SECTION_TITLE}>
              {tasksTitle} ({tasks.length})
            </h3>
            <ul className="space-y-2">
              {tasks.map((task) => (
                <TaskCard key={task.id} task={task} ctx={ctx} />
              ))}
            </ul>
          </section>
        ) : (
          <p role="status" className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            Nic nie blokuje wysyłki tego CV.
          </p>
        )}
        {data.cv && hasAiGaps ? (
          <AiFixes stageId={stageId} ctx={ctx} />
        ) : null}
        {notes.length > 0 ? (
          <section aria-label="Warto poprawić — nie blokuje" className="space-y-2">
            <h3 className={SECTION_TITLE}>Warto poprawić — nie blokuje ({notes.length})</h3>
            <ul className="space-y-2">
              {notes.map((check) => (
                <CheckRow key={check.key} check={check} ctx={ctx} />
              ))}
            </ul>
          </section>
        ) : null}
        <MutedChecks checks={muted} ctx={ctx} />
        <DismissedSection entries={qcDismissedEntries(data.checks, ctx)} restoring={ctx.restoring} />
        <PassedChecks passed={passed} skipped={skipped} ctx={ctx} />
      </div>
    </div>
  );
}

export interface CvQcDialogViewProps extends CvQcDialogProps {
  /** Wynik QC — ostatni znany (także gdy ponowne przeliczenie padło). */
  data: QcResult | undefined;
  loading: boolean;
  fetching: boolean;
  /** Stan awarii pierwszego odczytu (`resolveViewState`). */
  state: ReturnType<typeof resolveViewState>;
  /** Ponowne przeliczenie padło, ale jest poprzedni wynik. */
  refreshFailed: boolean;
  onRecheck: () => void;
}

const MOVE_BLOCKED_HINT = "Najpierw popraw rzeczy z listy „Do poprawy przed wysłaniem”.";
const MOVE_ADVISORY_HINT = "Popraw rzeczy z listy albo użyj „Przesuń mimo uwag…”.";

/** Okno bez zapytania o wynik — `CvQcDialog` i harness `/preview/cv-qc`. */
export function CvQcDialogView({
  stageId,
  open,
  onClose,
  onChanged,
  onMoveNext,
  data,
  loading,
  fetching,
  state,
  refreshFailed,
  onRecheck,
}: CvQcDialogViewProps) {
  const me = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  // Obejście QC to decyzja osoby prowadzącej rekrutację (serwer: uprawnienie
  // `recruitment_manage`), a w trybie doradczym każdego, kto przesuwa karty —
  // kto może, mówi serwer (`can_override`); starsza odpowiedź bez tego pola
  // spada na uprawnienie. W podglądzie jako inny użytkownik — nikomu.
  const advisory = data?.advisory === true;
  const canOverride = !impersonating && (data?.can_override ?? hasPermission(me, "recruitment_manage"));
  const [editorOpen, setEditorOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const editorTarget = qcEditorTarget(data?.cv);
  const pending = useMemo(() => (data ? splitChecks(data.checks).tasks.map(taskTitle) : []), [data]);
  const pendingItems = useMemo(() => (data ? splitChecks(data.checks).tasks.map(taskPendingItem) : []), [data]);
  const cleared = Boolean(data && (data.passed || data.override));

  return (
    <>
    <Dialog open={open && stageId != null} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent size="full" className="flex h-[92dvh] max-h-[92dvh] flex-col p-0" aria-describedby="cv-qc-desc">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3 pr-16">
          <div className="min-w-0 space-y-0.5">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">QC CV</p>
            <DialogTitle className="truncate text-base font-semibold">
              {data ? (
                <>
                  {data.candidate_name}
                  <span className="font-normal text-muted-foreground">
                    {" → "}
                    {data.job_title}
                    {data.client_name ? ` (${data.client_name})` : ""}
                  </span>
                </>
              ) : (
                "Kontrola CV przed wysłaniem"
              )}
            </DialogTitle>
            <DialogDescription id="cv-qc-desc" className="text-xs text-muted-foreground">
              {data?.cv
                ? `${QC_CV_SOURCE_LABEL[data.cv.source] ?? "CV"}${data.cv.filename ? ` · ${data.cv.filename}` : ""}${
                    data.cv.updated_at ? ` · ${formatDate(data.cv.updated_at)}` : ""
                  }`
                : data
                  ? "Brak CV firmowego"
                  : "Sprawdzenia CV firmowego przed „CV wysłane” i Cpro."}
            </DialogDescription>
            <QcWordFileNote cv={data?.cv} />
          </div>
          {data ? (
            <div className="flex items-center gap-2">
              <Verdict data={data} />
              <Button size="sm" variant="outline" onClick={onRecheck} disabled={fetching}>
                {fetching ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <RefreshCw className="size-3.5" aria-hidden />}
                Sprawdź ponownie
              </Button>
            </div>
          ) : null}
        </div>

        {data && refreshFailed ? (
          <p role="alert" className="border-b border-border bg-destructive-muted px-5 py-2 text-xs text-destructive-muted-foreground">
            Nie udało się przeliczyć QC ponownie — widzisz poprzedni wynik.
          </p>
        ) : null}

        {data && stageId != null ? (
          <CvQcBody
            key={stageId}
            data={data}
            stageId={stageId}
            onChanged={onChanged}
            onOpenEditor={editorTarget ? () => setEditorOpen(true) : undefined}
          />
        ) : loading ? (
          <p className="flex items-center gap-2 px-5 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Sprawdzam CV firmowe…
          </p>
        ) : (
          <div role="alert" className="space-y-2 px-5 py-6 text-sm text-muted-foreground">
            <p>{LOAD_ERROR[state] ?? LOAD_ERROR.error}</p>
            {state !== "forbidden" && state !== "not_found" ? (
              <Button size="sm" variant="outline" onClick={onRecheck}>
                Ponów
              </Button>
            ) : null}
          </div>
        )}

        {data ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
            <p className="min-w-0 flex-1 basis-40 text-xs text-muted-foreground">
              Po każdej poprawce QC przelicza się samo.
            </p>
            {canOverride && !cleared && stageId != null ? (
              <Button size="sm" variant="ghost" onClick={() => setOverrideOpen(true)}>
                {advisory ? "Przesuń mimo uwag…" : "Przepuść mimo QC…"}
              </Button>
            ) : null}
            {editorTarget ? (
              <Button size="sm" variant="outline" onClick={() => setEditorOpen(true)}>
                Otwórz w edytorze CV
              </Button>
            ) : (
              <Button asChild size="sm" variant="outline">
                <Link href={`/jobs/${data.job_id}?candidate=${data.candidate_id}&panel=cv`} onClick={onClose}>
                  Otwórz panel osoby
                  <ExternalLink className="size-3.5" aria-hidden />
                </Link>
              </Button>
            )}
            {onMoveNext ? (
              <Button
                size="sm"
                disabled={!cleared}
                title={cleared ? undefined : advisory ? MOVE_ADVISORY_HINT : MOVE_BLOCKED_HINT}
                onClick={() => onMoveNext(data)}
              >
                Przesuń dalej
                <ArrowRight className="size-3.5" aria-hidden />
              </Button>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
    {overrideOpen && stageId != null ? (
      <QcOverrideDialog
        stageId={stageId}
        open
        onOpenChange={setOverrideOpen}
        pending={pending}
        pendingItems={pendingItems}
        onChanged={onChanged}
        advisory={advisory}
        // Tryb doradczy: zapisany powód od razu przesuwa kartę — jedno przejście.
        onDone={advisory ? onMoveNext : undefined}
      />
    ) : null}
    {editorOpen && editorTarget && data ? (
      <CVBrandedEditModal
        open
        onOpenChange={(next) => {
          setEditorOpen(next);
          if (!next) {
            // Po poprawce QC liczy się od nowa — bez ponownej generacji.
            onRecheck();
            onChanged?.();
          }
        }}
        jobTitle={data.job_title}
        candidateName={data.candidate_name}
        {...editorTarget}
      />
    ) : null}
    </>
  );
}

export function CvQcDialog({ stageId, open, onClose, onChanged, onMoveNext }: CvQcDialogProps) {
  const query = useCvQc(stageId, open);
  const queryClient = useQueryClient();
  // Otwarcie okna przelicza i zapisuje QC (CV mogło się zmienić poza oknem) —
  // przy wyjściu chip na Tablicy i kolejki pulpitu czytają już ten wynik.
  const refreshBoard = () => {
    if (query.data) invalidateAfterQcChange(queryClient, query.data.job_id);
  };
  return (
    <CvQcDialogView
      stageId={stageId}
      open={open}
      onClose={() => {
        refreshBoard();
        onClose();
      }}
      onChanged={onChanged}
      onMoveNext={
        onMoveNext
          ? (result) => {
              refreshBoard();
              onMoveNext(result);
            }
          : undefined
      }
      data={query.data}
      loading={query.isLoading}
      fetching={query.isFetching}
      state={resolveViewState({ isLoading: query.isLoading, error: query.error })}
      refreshFailed={query.isError && query.data != null}
      onRecheck={() => void query.refetch()}
    />
  );
}
