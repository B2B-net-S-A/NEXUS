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
 * edytuje albo odrzuca. Każda zmiana zwraca świeży wynik QC.
 *
 * Treść CV i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 * „Przepuść mimo QC” widzą tylko admin i Delivery Lead (serwer i tak odmawia
 * reszcie).
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Copy,
  ExternalLink,
  HelpCircle,
  Loader2,
  MinusCircle,
  RefreshCw,
  Sparkles,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/Toast";
import { QcOverrideDialog } from "@/components/v2/recruitment/QcOverrideDialog";
import { apiErrorMessage } from "@/lib/api-error";
import {
  invalidateAfterQcChange,
  useCvQc,
  useCvQcFixes,
  useQcApply,
  cvQcFixesQueryKey,
  type QcApplyBody,
  type QcCheck,
  type QcCvRun,
  type QcFix,
  type QcFixesResponse,
  type QcItem,
  type QcResult,
} from "@/lib/api/cvQc";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  CV_NOT_EDITABLE_CODE,
  CV_NOT_EDITABLE_MESSAGE,
  QC_CV_SOURCE_LABEL,
  QC_TASK_TAG,
  RODO_SECTION,
  apiErrorCode,
  candidateQuestion,
  checkLevelFixes,
  highlightTerms,
  notePreview,
  parseBoldMarkup,
  roleGaps,
  segmentCv,
  splitChecks,
  taskTitle,
  thingsLabel,
  unboldedTerms,
  type QcTask,
  type RoleGap,
} from "@/lib/cv-qc";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

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

// ── Sprawdzenia po prawej ────────────────────────────────────────────────────

function StatusIcon({ status }: { status: QcCheck["status"] }) {
  if (status === "pass") return <CheckCircle2 className="size-4 text-success" aria-label="Przechodzi" />;
  if (status === "fail") return <AlertTriangle className="size-4 text-warning" aria-label="Warto poprawić" />;
  if (status === "manual")
    return <HelpCircle className="size-4 text-info" aria-label="Do sprawdzenia ręcznie" />;
  return <MinusCircle className="size-4 text-muted-foreground" aria-label="Nie dotyczy" />;
}

function statusBadge(check: QcCheck) {
  if (check.status === "pass") return <Badge variant="success" size="sm">{check.summary || "OK"}</Badge>;
  if (check.status === "manual") return <Badge variant="info" size="sm">sprawdź ręcznie</Badge>;
  if (check.status === "skip") return <Badge variant="outline" size="sm">nie dotyczy</Badge>;
  const n = check.items.length;
  return (
    <Badge variant="warning" size="sm">
      {check.summary || (n === 1 ? "1 pozycja" : `${n} pozycje`)}
    </Badge>
  );
}

interface ActionContext {
  data: QcResult;
  editable: boolean;
  busy: boolean;
  apply: (body: QcApplyBody, success: string, onApplied?: () => void) => void;
  requestAiFixes: () => void;
  copyQuestion: (item: QcItem) => void;
  /** Edytor sprawdzanego CV — `null`, gdy tego CV nie da się edytować w NEXUSIE. */
  openEditor: (() => void) | null;
}

const generatorHref = (data: QcResult) =>
  `/cv-generator?candidate_id=${data.candidate_id}&job_id=${data.job_id}`;

const championHref = (data: QcResult) => `/jobs/${data.job_id}?tab=champion`;

function CheckActions({ check, ctx }: { check: QcCheck; ctx: ActionContext }) {
  const kinds = checkLevelFixes(check);
  if (kinds.length === 0 || check.status === "pass") return null;
  return (
    <div className="flex flex-wrap gap-2">
      {kinds.map((kind) => {
        if (kind === "bold_all") {
          const scope = check.key === "nice_bolded" ? "nice" : "must";
          return (
            <Button
              key={kind}
              size="sm"
              disabled={!ctx.editable || ctx.busy}
              onClick={() => ctx.apply({ action: "bold_all", scope }, "Pogrubiono wszystkie wystąpienia.")}
            >
              Pogrub wszystkie
            </Button>
          );
        }
        if (kind === "spelling") {
          return (
            <Button
              key={kind}
              size="sm"
              variant="outline"
              disabled={!ctx.editable || ctx.busy}
              onClick={() => ctx.apply({ action: "spelling" }, "Poprawiono pisownię technologii.")}
            >
              Popraw pisownię
            </Button>
          );
        }
        return (
          <Button key={kind} size="sm" variant="outline" disabled={!ctx.editable} onClick={ctx.requestAiFixes}>
            <Sparkles className="size-3.5" aria-hidden />
            Zaproponuj poprawki (AI)
          </Button>
        );
      })}
    </div>
  );
}

function RemoveTermButton({ term, ctx }: { term: string; ctx: ActionContext }) {
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={!ctx.editable || ctx.busy}
      onClick={() => ctx.apply({ action: "remove_term", term }, `Usunięto „${term}” z CV.`)}
    >
      Usuń „{term}” z CV
    </Button>
  );
}

function AskCandidateButtons({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => ctx.copyQuestion(item)}>
        <Copy className="size-3.5" aria-hidden />
        Skopiuj pytanie do kandydata
      </Button>
      <Button asChild size="sm" variant="ghost">
        <Link href={`/candidates/${ctx.data.candidate_id}`}>Profil kandydata</Link>
      </Button>
    </>
  );
}

function ItemAction({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  const term = (item.term ?? item.requirement ?? "").trim();
  switch (item.fix) {
    case "remove_term":
      return term ? <RemoveTermButton term={term} ctx={ctx} /> : null;
    case "ask_candidate":
      return (
        <span className="flex flex-wrap gap-2">
          <AskCandidateButtons item={item} ctx={ctx} />
        </span>
      );
    case "upload_consent":
      return (
        <span className="text-xs text-muted-foreground">
          Zrzut zgody RODO wgrywa się w generatorze CV —{" "}
          <Link href={generatorHref(ctx.data)} className="font-medium text-primary hover:underline">
            otwórz generator
          </Link>
          , wgraj zrzut i wygeneruj CV ponownie.
        </span>
      );
    case "generate_cv":
      return (
        <Button asChild size="sm">
          <Link href={generatorHref(ctx.data)}>Wygeneruj CV</Link>
        </Button>
      );
    default:
      return null;
  }
}

/** Jedna rzecz do poprawy przed wysłaniem: co jest nie tak, gdzie i przycisk naprawy. */
function TaskCard({ task, ctx }: { task: QcTask; ctx: ActionContext }) {
  const { check, name, items } = task;
  const title = taskTitle(task);
  const roleItems = items.filter((i) => i.role);
  const first = items[0];
  const editorButton = ctx.openEditor ? (
    <Button size="sm" variant="outline" onClick={ctx.openEditor}>
      Poprawię w edytorze
    </Button>
  ) : null;

  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;
  if (check.key === "critical_skills" && roleItems.length > 0) {
    body = (
      <>
        <p className="text-xs text-muted-foreground">
          W oryginalnym CV kandydat ma tę umiejętność w {roleItems.length === 1 ? "tej roli" : "tych rolach"}. W CV
          firmowym brakuje tam zdania o tym, co z nią robił — wystarczy jedno w każdej roli.
        </p>
        <ul className="flex flex-wrap gap-1.5" aria-label={`Role bez opisu: ${name}`}>
          {roleItems.map((item, i) => (
            <li key={i}>
              <Badge variant="outline" size="sm" title={item.detail ? item.detail : undefined}>
                {item.role}
              </Badge>
            </li>
          ))}
        </ul>
      </>
    );
    actions = (
      <>
        <Button size="sm" disabled={!ctx.editable} onClick={ctx.requestAiFixes}>
          <Sparkles className="size-3.5" aria-hidden />
          Dopisz zdania z oryginału (AI)
        </Button>
        {editorButton}
      </>
    );
  } else if (check.key === "no_unsupported" && first) {
    const term = (first.term ?? name ?? "").trim();
    // Tytuł mówi już, co jest nie tak — niżej tylko, co z tym zrobić.
    body = (
      <p className="text-xs text-muted-foreground">
        Oryginalne CV i notatki z rozmów o tym nie wspominają. Usuń to z CV albo potwierdź u kandydata.
      </p>
    );
    actions = (
      <>
        {term ? <RemoveTermButton term={term} ctx={ctx} /> : null}
        <AskCandidateButtons item={first} ctx={ctx} />
      </>
    );
  } else if (first) {
    // Bez nazwy tytułem jest samo zdanie pozycji — nie powtarzamy go niżej.
    body = name && first.detail ? <p className="text-xs text-muted-foreground">{first.detail}</p> : null;
    actions = first.fix ? <ItemAction item={first} ctx={ctx} /> : editorButton;
  }

  return (
    <li className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
      <p className="flex flex-wrap items-center gap-1.5">
        <XCircle className="size-4 shrink-0 text-destructive" aria-hidden />
        <span className="min-w-0 text-sm font-semibold">{title}</span>
        {QC_TASK_TAG[check.key] ? (
          <Badge variant="danger" size="sm">
            {QC_TASK_TAG[check.key]}
          </Badge>
        ) : null}
      </p>
      {body}
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </li>
  );
}

function CheckRow({ check, ctx }: { check: QcCheck; ctx: ActionContext }) {
  const [open, setOpen] = useState(false);
  const hasBody = check.items.length > 0 || checkLevelFixes(check).length > 0;
  const bodyId = `qc-check-${check.key}`;
  const preview = check.status === "fail" || check.status === "manual" ? notePreview(check) ?? check.summary : null;
  return (
    <li className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={() => hasBody && setOpen((v) => !v)}
        aria-expanded={hasBody ? open : undefined}
        aria-controls={hasBody ? bodyId : undefined}
        className={cn(
          "grid w-full grid-cols-[20px_1fr_auto] items-center gap-3 px-3 py-2 text-left",
          open && hasBody && "border-b border-border bg-muted/40",
          !hasBody && "cursor-default",
        )}
      >
        <StatusIcon status={check.status} />
        <span className="min-w-0">
          <span className="block text-sm font-medium">{check.label}</span>
          {preview && !open ? (
            <span className="block truncate text-xs text-muted-foreground">{preview}</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5">
          {statusBadge(check)}
          {hasBody ? (
            <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
          ) : null}
        </span>
      </button>
      {open && hasBody ? (
        <div id={bodyId} className="space-y-2 px-3 py-2.5">
          {check.items.map((item, i) => (
            <div key={i} className="space-y-1.5 rounded-md border border-border/70 px-2.5 py-2 text-sm">
              <p className="flex flex-wrap items-center gap-1.5">
                {item.role ? (
                  <Badge variant="outline" size="sm">
                    {item.role}
                  </Badge>
                ) : null}
                {item.requirement || item.term ? (
                  <span className="font-medium">{item.requirement ?? item.term}</span>
                ) : null}
              </p>
              {item.detail ? <p className="text-xs text-muted-foreground">{item.detail}</p> : null}
              <ItemAction item={item} ctx={ctx} />
            </div>
          ))}
          <CheckActions check={check} ctx={ctx} />
        </div>
      ) : null}
    </li>
  );
}

/** Zaliczone i niedotyczące — jedna linia, szczegóły po rozwinięciu. */
function PassedChecks({ passed, skipped, ctx }: { passed: QcCheck[]; skipped: QcCheck[]; ctx: ActionContext }) {
  const [open, setOpen] = useState(false);
  if (passed.length + skipped.length === 0) return null;
  const listId = "qc-passed-checks";
  // Bez CV nic nie jest „w porządku” — reszty po prostu nie sprawdzono.
  const title = passed.length > 0 ? "W porządku" : "Nie sprawdzono";
  return (
    <section aria-label={title} className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={listId}
        className="flex w-full items-start gap-2 rounded-lg border border-border px-3 py-2 text-left text-xs text-muted-foreground"
      >
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="font-semibold text-foreground">
            {title} ({passed.length > 0 ? passed.length : skipped.length})
          </span>
          {passed.length > 0 ? <span>: {passed.map((c) => c.label).join(" · ")}</span> : null}
        </span>
        <ChevronDown className={cn("mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <ul id={listId} className="space-y-2">
          {[...passed, ...skipped].map((check) => (
            <CheckRow key={check.key} check={check} ctx={ctx} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

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
      {critical.length > 0 ? (
        <p>
          Umiejętności krytyczne: <strong className="font-semibold">{critical.join(", ")}</strong>
          {source === "dl" ? (
            " — wybór Delivery Leada."
          ) : (
            <> — podpowiedź z historii rekrutacji. Delivery Lead może je zmienić w {champion}.</>
          )}
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

// ── Propozycje AI ────────────────────────────────────────────────────────────

function Proposal({
  fix,
  ctx,
  onApply,
  onDismiss,
}: {
  fix: QcFix;
  ctx: ActionContext;
  onApply: (fix: QcFix, text?: string) => void;
  onDismiss: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fix.proposed_text);
  return (
    <li className="space-y-2 rounded-lg border border-border px-3 py-2.5" aria-label={`Propozycja: ${fix.requirement ?? fix.role ?? fix.id}`}>
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {fix.cv_role_label || fix.role ? (
          <Badge variant="outline" size="sm">
            {fix.cv_role_label || fix.role}
          </Badge>
        ) : null}
        {fix.requirement ? <span>{fix.requirement}</span> : null}
        {fix.check_key === "critical_skills" ? (
          <Badge variant="danger" size="sm">
            {QC_TASK_TAG.critical_skills}
          </Badge>
        ) : null}
      </p>
      {fix.current_text ? (
        <p className="text-xs text-muted-foreground">
          Teraz: <span className="line-through">{fix.current_text}</span>
        </p>
      ) : null}
      {editing ? (
        <textarea
          aria-label="Treść poprawki"
          className="min-h-20 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : (
        <p className="rounded-md bg-success-muted px-2.5 py-1.5 text-sm text-foreground">
          {parseBoldMarkup(fix.proposed_text).map((run, i) =>
            run.b ? (
              <strong key={i} className="font-semibold">
                {run.t}
              </strong>
            ) : (
              <span key={i}>{run.t}</span>
            ),
          )}
        </p>
      )}
      <p className="border-l-2 border-border pl-2 text-xs text-muted-foreground">
        Źródło: {fix.source === "notes" ? "notatka rekrutera" : "oryginalne CV"}
        {fix.source_quote ? (
          <>
            {" — "}
            <q className="italic">{fix.source_quote}</q>
          </>
        ) : null}
      </p>
      <div className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button
              size="sm"
              disabled={!ctx.editable || ctx.busy || !text.trim()}
              onClick={() => onApply(fix, text.trim())}
            >
              Zastosuj edycję
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setText(fix.proposed_text);
              }}
            >
              Anuluj
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" disabled={!ctx.editable || ctx.busy} onClick={() => onApply(fix)}>
              Zastosuj
            </Button>
            <Button size="sm" variant="outline" disabled={!ctx.editable} onClick={() => setEditing(true)}>
              Edytuj
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onDismiss(fix.id)}>
              Odrzuć
            </Button>
          </>
        )}
      </div>
    </li>
  );
}

function AiFixes({
  stageId,
  ctx,
  requested,
  onRequest,
}: {
  stageId: number;
  ctx: ActionContext;
  requested: boolean;
  onRequest: () => void;
}) {
  const queryClient = useQueryClient();
  const fixes = useCvQcFixes(stageId, requested && ctx.editable);
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

  let body: React.ReactNode;
  if (!ctx.editable) {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else if (fixes.isFetching && !data) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        Luna porównuje CV z oryginałem i notatkami…
      </p>
    );
  } else if (fixes.isError || data?.status === "unavailable") {
    body = (
      <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <AlertTriangle className="size-4 text-warning" aria-hidden />
        Propozycje AI są chwilowo niedostępne — poprawki zrób w edytorze CV.
        <Button size="sm" variant="outline" onClick={() => void fixes.refetch()}>
          <RefreshCw className="size-3.5" aria-hidden />
          Ponów
        </Button>
      </div>
    );
  } else if (data?.status === "no_cv") {
    body = <p className="text-sm text-muted-foreground">Najpierw wygeneruj CV — AI poprawia istniejące CV.</p>;
  } else if (data?.status === "not_editable") {
    body = <p className="text-sm text-muted-foreground">{CV_NOT_EDITABLE_MESSAGE}</p>;
  } else if (data) {
    body =
      visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          AI nie ma (więcej) propozycji z pokryciem w oryginale ani w notatkach — resztę popraw w edytorze CV.
        </p>
      ) : (
        <ul className="space-y-2">
          {visible.map((fix) => (
            <Proposal
              key={fix.id}
              fix={fix}
              ctx={ctx}
              onApply={applyFix}
              onDismiss={(id) => setDismissed((prev) => new Set(prev).add(id))}
            />
          ))}
        </ul>
      );
  } else {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          AI zaproponuje zdania z pokryciem w oryginalnym CV albo notatkach — bez źródła nie ma poprawki.
        </p>
        <Button size="sm" variant="outline" onClick={onRequest}>
          <Sparkles className="size-3.5" aria-hidden />
          Zaproponuj poprawki (AI)
        </Button>
      </div>
    );
  }

  return (
    <section id={`qc-ai-${stageId}`} aria-label="Propozycje AI" className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Sparkles className="size-4 text-primary" aria-hidden />
        Propozycje AI
      </h3>
      {body}
    </section>
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

const SECTION_TITLE = "text-xs font-semibold uppercase tracking-wider text-muted-foreground";

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
  const [notEditable, setNotEditable] = useState(false);
  const [aiRequested, setAiRequested] = useState(false);
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
    requestAiFixes: () => {
      setAiRequested(true);
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
  };

  const { tasks, notes, passed, skipped } = useMemo(() => splitChecks(data.checks), [data.checks]);
  // Zdania AI dopisuje do ról — także wtedy, gdy QC już przechodzi, a brak
  // opisu jest tylko uwagą.
  const hasAiGaps = data.checks.some((c) => c.status === "fail" && c.items.some((i) => i.fix === "ai"));

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
        {data.override && !data.passed ? (
          <p role="status" className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            Przepuszczone mimo QC{data.override.by_name ? ` przez ${data.override.by_name}` : ""}
            {data.override.at ? ` (${formatDate(data.override.at)})` : ""}: {data.override.reason}
          </p>
        ) : null}
        {tasks.length > 0 ? (
          <section aria-label="Do poprawy przed wysłaniem" className="space-y-2">
            <h3 className={SECTION_TITLE}>Do poprawy przed wysłaniem ({tasks.length})</h3>
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
          <AiFixes stageId={stageId} ctx={ctx} requested={aiRequested} onRequest={() => setAiRequested(true)} />
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
  const canOverride = hasRole(me, "admin", "delivery_lead");
  const [editorOpen, setEditorOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const editorTarget = qcEditorTarget(data?.cv);
  const pending = useMemo(() => (data ? splitChecks(data.checks).tasks.map(taskTitle) : []), [data]);
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
                Przepuść mimo QC…
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
                title={cleared ? undefined : MOVE_BLOCKED_HINT}
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
        onChanged={onChanged}
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
