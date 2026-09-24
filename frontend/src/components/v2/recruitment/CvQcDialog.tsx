"use client";

/**
 * QC CV (Rekrutacja v5, decyzje Artura 23.09.2026) — kontrola CV firmowego
 * przed „CV wysłane” / Cpro. Zastępuje przegląd DZ (0353).
 *
 * Po lewej CV z bloków tekstu (pogrubienia jak w dokumencie; żółte = termin,
 * który powinien być pogrubiony, czerwona krawędź = stanowisko z brakiem
 * must-have). Po prawej sprawdzenia z serwera w dwóch grupach: blokujące
 * i uwagi. Każde sprawdzenie ma naprawę wg `fix`; poprawki AI (GPT-6 Luna)
 * pokazują źródło — rekruter je akceptuje, edytuje albo odrzuca. Każda zmiana
 * zwraca świeży wynik QC, który zastępuje cache.
 *
 * Treść CV i propozycji to TEKST — nic nie trafia na stronę jako HTML.
 * QC jest twardą bramką; „Przepuść mimo QC” widzą tylko admin i Delivery Lead
 * (serwer i tak odmawia reszcie).
 */

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
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
import { apiErrorMessage } from "@/lib/api-error";
import {
  QC_OVERRIDE_MIN_REASON,
  useCvQc,
  useCvQcFixes,
  useQcApply,
  useQcOverride,
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
  apiErrorCode,
  candidateQuestion,
  checkLevelFixes,
  highlightTerms,
  parseBoldMarkup,
  roleGaps,
  segmentCv,
  unboldedTerms,
} from "@/lib/cv-qc";
import { resolveViewState } from "@/lib/view-state";
import { cn, formatDate } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

export interface CvQcDialogProps {
  stageId: number | null;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
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
      {segments.map((segment, s) => (
        <div
          key={s}
          data-qc-gap={segment.gap ? "true" : undefined}
          className={cn(segment.gap && "-ml-3 border-l-[3px] border-destructive pl-2.5")}
        >
          {segment.blocks.map((block, i) => {
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
          {segment.gap ? (
            <p className="mt-0.5 text-[11px] font-semibold text-destructive">
              {segment.gap.requirements.length > 0
                ? `${segment.gap.requirements.join(", ")} — używane tu wg oryginału, brak w opisie`
                : "Brak must-have w opisie tego stanowiska"}
            </p>
          ) : null}
        </div>
      ))}
    </article>
  );
}

// ── Sprawdzenia po prawej ────────────────────────────────────────────────────

function StatusIcon({ status }: { status: QcCheck["status"] }) {
  if (status === "pass") return <CheckCircle2 className="size-4 text-success" aria-label="Przechodzi" />;
  if (status === "fail") return <XCircle className="size-4 text-destructive" aria-label="Nie przechodzi" />;
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
    <Badge variant={check.severity === "blocking" ? "danger" : "warning"} size="sm">
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
}

const generatorHref = (data: QcResult) =>
  `/cv-generator?candidate_id=${data.candidate_id}&job_id=${data.job_id}`;

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

function ItemAction({ item, ctx }: { item: QcItem; ctx: ActionContext }) {
  const term = (item.term ?? item.requirement ?? "").trim();
  switch (item.fix) {
    case "remove_term":
      return term ? (
        <Button
          size="sm"
          variant="outline"
          disabled={!ctx.editable || ctx.busy}
          onClick={() => ctx.apply({ action: "remove_term", term }, `Usunięto „${term}” z CV.`)}
        >
          Usuń „{term}” z CV
        </Button>
      ) : null;
    case "ask_candidate":
      return (
        <span className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => ctx.copyQuestion(item)}>
            <Copy className="size-3.5" aria-hidden />
            Skopiuj pytanie do kandydata
          </Button>
          <Button asChild size="sm" variant="ghost">
            <Link href={`/candidates/${ctx.data.candidate_id}`}>Profil kandydata</Link>
          </Button>
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

function CheckRow({ check, ctx, defaultOpen }: { check: QcCheck; ctx: ActionContext; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = check.items.length > 0 || checkLevelFixes(check).length > 0;
  const bodyId = `qc-check-${check.key}`;
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

// ── Obejście ─────────────────────────────────────────────────────────────────

function OverrideForm({ stageId, onChanged }: { stageId: number; onChanged?: () => void }) {
  const [reason, setReason] = useState("");
  const { showSuccess, showError } = useToast();
  const override = useQcOverride(stageId, onChanged);
  const ready = reason.trim().length >= QC_OVERRIDE_MIN_REASON;
  return (
    <section aria-label="Przepuść mimo QC" className="space-y-2 rounded-lg border border-dashed border-border p-3 text-sm">
      <h3 className="font-semibold">Przepuść mimo QC</h3>
      <p className="text-xs text-muted-foreground">
        Tylko Delivery Lead i admin. Powód zostaje w historii kandydata i w raporcie QC.
      </p>
      <label className="block text-xs font-medium">
        Powód (min. {QC_OVERRIDE_MIN_REASON} znaków)
        <textarea
          className="mt-1 min-h-14 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          value={reason}
          placeholder="Np. klient sam prosił o skrócone CV bez opisów stanowisk"
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <Button
        size="sm"
        variant="outline"
        disabled={!ready || override.isPending}
        onClick={() =>
          override.mutate(
            { reason: reason.trim() },
            {
              onSuccess: () => {
                showSuccess("Przepuszczono mimo QC — powód zapisany w historii.");
                setReason("");
              },
              onError: (error) => showError(apiErrorMessage(error, "Nie udało się przepuścić. Spróbuj ponownie.")),
            },
          )
        }
      >
        {override.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
        Przepuść z powodem
      </Button>
    </section>
  );
}

// ── Okno ─────────────────────────────────────────────────────────────────────

const LOAD_ERROR: Record<string, string> = {
  forbidden: "Nie masz dostępu do tej rekrutacji.",
  not_found: "Ten etap kandydata już nie istnieje — odśwież Tablicę.",
  error: "Nie udało się policzyć QC. Spróbuj ponownie.",
};

function Verdict({ data }: { data: QcResult }) {
  if (data.override) {
    return (
      <Badge variant="warning" size="lg">
        Przepuszczone mimo QC
      </Badge>
    );
  }
  if (data.passed) {
    return (
      <Badge variant="success" size="lg">
        QC przechodzi
      </Badge>
    );
  }
  return (
    <Badge variant="danger" size="lg">
      Nie przechodzi · {data.blocking_failed} blokujące
    </Badge>
  );
}

export function CvQcBody({
  data,
  stageId,
  onChanged,
  canOverride,
}: {
  data: QcResult;
  stageId: number;
  onChanged?: () => void;
  canOverride: boolean;
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
  };

  const blocking = data.checks.filter((c) => c.severity === "blocking");
  const warnings = data.checks.filter((c) => c.severity !== "blocking");
  const failingBlocking = blocking.filter((c) => c.status === "fail").length;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:overflow-hidden">
      <div className="min-h-0 border-b border-border bg-muted/30 p-4 lg:overflow-y-auto lg:border-b-0 lg:border-r">
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
      <div className="min-h-0 space-y-3 p-4 lg:overflow-y-auto">
        {data.override ? (
          <p role="status" className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            Przepuszczone mimo QC{data.override.by_name ? ` przez ${data.override.by_name}` : ""}
            {data.override.at ? ` (${formatDate(data.override.at)})` : ""}: {data.override.reason}
          </p>
        ) : null}
        <section aria-label="Blokujące — bez nich CV nie wyjdzie" className="space-y-2">
          <header className="flex items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Blokujące — bez nich CV nie wyjdzie
            </h3>
            <span className="text-xs tabular-nums text-muted-foreground">
              {failingBlocking} z {blocking.length} nie przechodzi
            </span>
          </header>
          <ul className="space-y-2">
            {blocking.map((check) => (
              <CheckRow key={check.key} check={check} ctx={ctx} defaultOpen={check.status === "fail"} />
            ))}
          </ul>
        </section>
        {warnings.length > 0 ? (
          <section aria-label="Uwagi — nie blokują" className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Uwagi — nie blokują</h3>
            <ul className="space-y-2">
              {warnings.map((check) => (
                <CheckRow key={check.key} check={check} ctx={ctx} defaultOpen={false} />
              ))}
            </ul>
          </section>
        ) : null}
        {data.cv && !data.passed ? (
          <AiFixes stageId={stageId} ctx={ctx} requested={aiRequested} onRequest={() => setAiRequested(true)} />
        ) : null}
        {canOverride && !data.passed && !data.override ? <OverrideForm stageId={stageId} onChanged={onChanged} /> : null}
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

/** Okno bez zapytania o wynik — `CvQcDialog` i harness `/preview/cv-qc`. */
export function CvQcDialogView({
  stageId,
  open,
  onClose,
  onChanged,
  data,
  loading,
  fetching,
  state,
  refreshFailed,
  onRecheck,
}: CvQcDialogViewProps) {
  const me = useAuthStore((s) => s.user);
  const canOverride = hasRole(me, "admin", "delivery_lead");

  return (
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
          <CvQcBody key={stageId} data={data} stageId={stageId} onChanged={onChanged} canOverride={canOverride} />
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
          <div className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-3">
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              {data.passed || data.override
                ? "QC zaliczone — przesuń kartę dalej strzałką „→” na Tablicy."
                : "Po każdej poprawce QC liczy się od nowa. Dalej przesuwasz kartę strzałką „→” na Tablicy, gdy blokujące będą zielone."}
            </p>
            <Button asChild size="sm" variant="outline">
              <Link href={`/jobs/${data.job_id}?candidate=${data.candidate_id}&panel=cv`} onClick={onClose}>
                Otwórz w edytorze CV
                <ExternalLink className="size-3.5" aria-hidden />
              </Link>
            </Button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function CvQcDialog({ stageId, open, onClose, onChanged }: CvQcDialogProps) {
  const query = useCvQc(stageId, open);
  return (
    <CvQcDialogView
      stageId={stageId}
      open={open}
      onClose={onClose}
      onChanged={onChanged}
      data={query.data}
      loading={query.isLoading}
      fetching={query.isFetching}
      state={resolveViewState({ isLoading: query.isLoading, error: query.error })}
      refreshFailed={query.isError && query.data != null}
      onRecheck={() => void query.refetch()}
    />
  );
}
