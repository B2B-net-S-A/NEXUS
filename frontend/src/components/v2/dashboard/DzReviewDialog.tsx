"use client";

/**
 * Przegląd DZ (0353) — Dominik porównuje, zanim zatwierdzi „DZ ✓".
 *
 * Trzy kolumny obok siebie: CV przygotowane dla klienta, oryginalne CV
 * kandydata i zapytanie klienta. Nad nimi sprawdzenia, które robi ręcznie
 * (decyzja Artura 23.09.2026): must-have w CV, pogrubienie, obecność
 * w każdej roli, w której występuje w oryginale — liczy je serwer — oraz
 * podpowiedzi GPT-6 Luny. Podpowiedzi są doradcze: awaria nie blokuje „DZ".
 *
 * Treść CV przychodzi jako bloki tekstu z oznaczonymi pogrubieniami, nie jako
 * HTML — nic z edytora CV nie trafia na stronę przez `innerHTML`.
 */

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, ExternalLink, FileText, Loader2, RefreshCw, Sparkles, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";
import {
  useDzHints,
  useDzReview,
  type DzCheck,
  type DzCvBlock,
  type DzHints,
  type DzReview,
} from "@/lib/api/boardTasks";
import { DZ_CV_SOURCE_LABEL, DZ_HINT_KIND_LABEL, highlightTerms } from "@/lib/dz-review";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";

interface Props {
  stageId: number | null;
  onOpenChange: (open: boolean) => void;
  /** „✓ DZ" z tego okna — ten sam ruch co w kolejce. `undefined` = bez prawa DZ. */
  onApprove?: () => void;
  approving?: boolean;
}

function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  return (
    <>
      {highlightTerms(text, terms).map((part, i) =>
        part.match ? (
          <mark key={i} className="rounded-sm bg-warning-muted px-0.5 text-warning-muted-foreground">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        )
      )}
    </>
  );
}

function CvBlocks({ blocks, terms }: { blocks: DzCvBlock[]; terms: string[] }) {
  return (
    <div className="space-y-1.5 text-sm leading-relaxed">
      {blocks.map((block, i) => {
        const content = block.runs.map((run, j) =>
          run.b ? (
            <strong key={j} className="font-semibold">
              <Highlighted text={run.t} terms={terms} />
            </strong>
          ) : (
            <Highlighted key={j} text={run.t} terms={terms} />
          )
        );
        if (block.kind === "h") {
          return (
            <h4 key={i} className="pt-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground first:pt-0">
              {content}
            </h4>
          );
        }
        if (block.kind === "li") {
          return (
            <p key={i} className="flex gap-2 pl-1">
              <span aria-hidden className="text-muted-foreground">•</span>
              <span className="min-w-0">{content}</span>
            </p>
          );
        }
        return (
          <p key={i} className={cn(block.section === "role" && "pt-2 font-medium")}>
            {content}
          </p>
        );
      })}
    </div>
  );
}

function Mark({ ok, label }: { ok: boolean; label: string }) {
  return ok ? (
    <span className="inline-flex items-center gap-1 text-success">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
      {label}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-destructive">
      <XCircle className="h-3.5 w-3.5" aria-hidden />
      {label}
    </span>
  );
}

function RolesCell({ check, rolesChecked }: { check: DzCheck; rolesChecked: boolean }) {
  if (check.original_roles.length === 0) {
    return <span className="text-muted-foreground">Brak w rolach oryginału</span>;
  }
  if (!rolesChecked) {
    return (
      <span className="text-muted-foreground">
        W oryginale: {check.original_roles.join(", ")} — sprawdź ręcznie
      </span>
    );
  }
  const problems = [...check.missing_in_roles, ...check.roles_absent];
  if (problems.length === 0) {
    const n = check.original_roles.length;
    return <Mark ok label={n === 1 ? "Jest w tej roli" : `We wszystkich rolach (${n})`} />;
  }
  return (
    <div className="space-y-0.5">
      {check.missing_in_roles.length > 0 && (
        <p className="text-destructive">Brak w: {check.missing_in_roles.join(", ")}</p>
      )}
      {check.roles_absent.length > 0 && (
        <p className="text-warning-muted-foreground">Rola pominięta w CV: {check.roles_absent.join(", ")}</p>
      )}
    </div>
  );
}

function ChecksTable({ review }: { review: DzReview }) {
  if (!review.generated_cv) {
    return (
      <p className="text-sm text-muted-foreground">
        Nie ma CV dla klienta ani w NEXUSIE, ani w plikach kandydata („…B2B…”) — nie ma czego porównać.
      </p>
    );
  }
  const rolesChecked = review.summary.roles_checked !== false;
  if (review.checks.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Rekrutacja nie ma wpisanych must-have — nie ma czego sprawdzić automatycznie.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-1.5 pr-3 font-medium">Must-have</th>
            <th className="py-1.5 pr-3 font-medium">W CV dla klienta</th>
            <th className="py-1.5 pr-3 font-medium">Pogrubione</th>
            <th className="py-1.5 font-medium">W rolach z oryginału</th>
          </tr>
        </thead>
        <tbody>
          {review.checks.map((check) => (
            <tr key={check.label} className="border-b border-border/60 align-top last:border-0">
              <td className="py-1.5 pr-3 font-medium">{check.label}</td>
              <td className="py-1.5 pr-3">
                <Mark ok={check.in_cv} label={check.in_cv ? "Jest" : check.in_original ? "Brak (jest w oryginale)" : "Brak"} />
              </td>
              <td className="py-1.5 pr-3">
                {!check.in_cv ? (
                  <span className="text-muted-foreground">—</span>
                ) : check.bolded === null ? (
                  <span className="text-muted-foreground" title="CV dla klienta jest w PDF — pogrubień nie da się odczytać.">
                    nie do sprawdzenia (PDF)
                  </span>
                ) : (
                  <Mark ok={check.bolded} label={check.bolded ? "Tak" : "Nie"} />
                )}
              </td>
              <td className="py-1.5">
                <RolesCell check={check} rolesChecked={rolesChecked} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HintsPanel({ hints, loading, failed, onRetry }: { hints: DzHints | undefined; loading: boolean; failed: boolean; onRetry: () => void }) {
  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Luna porównuje CV z oryginałem i zapytaniem…
      </p>
    );
  }
  if (failed || hints?.status === "unavailable") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" role="status">
        <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />
        Podpowiedzi AI są chwilowo niedostępne — sprawdzenie must-have działa bez nich.
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" />
          Ponów
        </Button>
      </div>
    );
  }
  if (!hints || hints.status === "no_cv") {
    return <p className="text-sm text-muted-foreground">Podpowiedzi pojawią się, gdy będzie CV dla klienta.</p>;
  }
  if (hints.hints.length === 0) {
    return <Mark ok label="Luna nie widzi nic do poprawy." />;
  }
  return (
    <ul className="space-y-2">
      {hints.hints.map((hint, i) => (
        <li key={i} className="flex gap-2 text-sm">
          <span
            aria-hidden
            className={cn(
              "mt-1.5 h-2 w-2 shrink-0 rounded-full",
              hint.severity === "high" ? "bg-destructive" : hint.severity === "medium" ? "bg-warning" : "bg-muted-foreground"
            )}
          />
          <div className="min-w-0 space-y-0.5">
            <p>
              <span className="mr-1.5 text-xs font-medium text-muted-foreground">
                {DZ_HINT_KIND_LABEL[hint.kind] ?? "Uwaga"}
                {hint.must_have ? ` · ${hint.must_have}` : ""}
              </span>
              {hint.message}
            </p>
            {hint.quote && <p className="text-xs italic text-muted-foreground">„{hint.quote}”</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Column({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="flex min-h-0 min-w-0 flex-col rounded-lg border border-border">
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {aside}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 lg:max-h-[60vh]">{children}</div>
    </section>
  );
}

export function DzReviewBody({
  review,
  hints,
  hintsLoading,
  hintsFailed,
  onRetryHints,
  onOpenOriginal,
}: {
  review: DzReview;
  hints: DzHints | undefined;
  hintsLoading: boolean;
  hintsFailed: boolean;
  onRetryHints: () => void;
  onOpenOriginal?: () => void;
}) {
  const terms = review.client_request.must;
  const { summary } = review;
  const boardHref = `/jobs/${review.job_id}?candidate=${review.candidate_id}`;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-label="Sprawdzenie must-have" className="min-w-0 rounded-lg border border-border p-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Must-have</h3>
            {summary.must_total > 0 && (
              <p className="text-xs tabular-nums text-muted-foreground">
                w CV {summary.must_in_cv}/{summary.must_total}
                {summary.bold_known === false ? "" : ` · pogrubione ${summary.must_bolded}/${summary.must_total}`}
                {summary.roles_missing > 0 ? ` · braki w rolach: ${summary.roles_missing}` : ""}
              </p>
            )}
          </div>
          <ChecksTable review={review} />
          {review.extra_bold.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Pogrubione spoza wymagań: {review.extra_bold.join(", ")}
            </p>
          )}
        </section>
        <section aria-label="Podpowiedzi AI" className="min-w-0 rounded-lg border border-primary/30 bg-primary/5 p-3">
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            Podpowiedzi (Luna)
          </h3>
          <HintsPanel hints={hints} loading={hintsLoading} failed={hintsFailed} onRetry={onRetryHints} />
        </section>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Column
          title="CV dla klienta"
          aside={
            review.generated_cv ? (
              <Badge variant={review.generated_cv.source === "branded_finalized" ? "success" : "soft"} size="sm">
                {DZ_CV_SOURCE_LABEL[review.generated_cv.source]}
              </Badge>
            ) : null
          }
        >
          {review.generated_cv ? (
            <>
              {review.generated_cv.source === "document" && review.generated_cv.filename && (
                <p className="mb-2 text-xs text-muted-foreground">
                  CV zrobione poza generatorem — plik {review.generated_cv.filename}
                  {review.generated_cv.bold_known === false ? " (PDF: bez pogrubień)" : ""}.
                </p>
              )}
              <CvBlocks blocks={review.generated_cv.blocks} terms={terms} />
              <Link href={boardHref} className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                Popraw CV na Tablicy
                <ExternalLink className="h-3 w-3" aria-hidden />
              </Link>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Rekruter nie przygotował jeszcze CV dla klienta.{" "}
              <Link href={boardHref} className="font-medium text-primary hover:underline">
                Otwórz osobę na Tablicy
              </Link>
            </p>
          )}
        </Column>
        <Column
          title="CV oryginalne"
          aside={
            onOpenOriginal ? (
              <Button size="sm" variant="ghost" className="h-7" onClick={onOpenOriginal}>
                <FileText className="h-3.5 w-3.5" />
                Plik
              </Button>
            ) : null
          }
        >
          {review.original_cv.text ? (
            <>
              {review.original_cv.source === "profile_text" && (
                <p className="mb-2 text-xs text-muted-foreground">Tekst CV z profilu — brak snapshotu z tej rekrutacji.</p>
              )}
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                <Highlighted text={review.original_cv.text} terms={terms} />
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {review.original_cv.source === "snapshot"
                ? "Nie udało się odczytać tekstu z pliku CV — otwórz plik."
                : "Kandydat nie ma CV w NEXUSIE."}
            </p>
          )}
        </Column>
        <Column title="Zapytanie klienta">
          <div className="space-y-3 text-sm">
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Must-have</p>
              {terms.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {terms.map((t) => (
                    <Badge key={t} variant="warning" size="md">
                      {t}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">Nie wpisano.</p>
              )}
            </div>
            {review.client_request.nice.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Nice-to-have</p>
                <div className="flex flex-wrap gap-1">
                  {review.client_request.nice.map((t) => (
                    <Badge key={t} variant="outline" size="md">
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {review.client_request.description && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Opis rekrutacji</p>
                <p className="whitespace-pre-wrap leading-relaxed">
                  <Highlighted text={review.client_request.description} terms={terms} />
                </p>
              </div>
            )}
            {review.client_request.project_about && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">O projekcie (Champion)</p>
                <p className="whitespace-pre-wrap leading-relaxed">{review.client_request.project_about}</p>
              </div>
            )}
          </div>
        </Column>
      </div>
    </div>
  );
}

const LOAD_ERROR: Record<string, string> = {
  forbidden: "Przegląd DZ jest dla Delivery Leada i Head of Recruitment z dostępem do tej rekrutacji.",
  not_found: "Ten etap kandydata już nie istnieje — odśwież kolejkę.",
  error: "Nie udało się wczytać przeglądu. Spróbuj ponownie.",
};

export function DzReviewDialog({ stageId, onOpenChange, onApprove, approving = false }: Props) {
  const open = stageId != null;
  const review = useDzReview(stageId);
  // Podpowiedzi dopiero do ŚWIEŻEGO przeglądu (po powrocie z Tablicy CV mogło
  // się zmienić) — `isFetching` wstrzymuje je na czas ponownego odczytu.
  const hints = useDzHints(stageId, review.data, review.isSuccess && !review.isFetching);
  const [originalOpen, setOriginalOpen] = useState(false);
  const state = resolveViewState({ isLoading: review.isLoading, error: review.error });
  const data = review.data;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="full" className="flex max-h-[94vh] flex-col p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Przegląd przed DZ</p>
            <DialogTitle className="truncate text-base font-semibold">
              {data ? data.candidate_name : "Wczytywanie…"}
              {data && (
                <span className="font-normal text-muted-foreground">
                  {" "}
                  — {data.job_title}
                  {data.client_name ? ` · ${data.client_name}` : ""}
                </span>
              )}
            </DialogTitle>
          </div>
          {data && (
            <div className="flex items-center gap-2">
              <Button asChild size="sm" variant="outline">
                <Link href={`/jobs/${data.job_id}?candidate=${data.candidate_id}`}>Otwórz na Tablicy</Link>
              </Button>
              {onApprove && (
                <Button size="sm" onClick={onApprove} disabled={approving}>
                  {approving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  Zatwierdź DZ
                </Button>
              )}
            </div>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {review.isLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Zbieram CV dla klienta, oryginał i zapytanie…
            </p>
          ) : state === "forbidden" || state === "not_found" || state === "error" ? (
            <div role="alert" className="space-y-2 text-sm text-muted-foreground">
              <p>{LOAD_ERROR[state]}</p>
              {state === "error" && (
                <Button size="sm" variant="outline" onClick={() => void review.refetch()}>
                  Ponów
                </Button>
              )}
            </div>
          ) : data ? (
            <DzReviewBody
              review={data}
              hints={hints.data}
              hintsLoading={(hints.isFetching || hints.isPending) && !hints.data && !hints.isError}
              hintsFailed={hints.isError}
              onRetryHints={() => void hints.refetch()}
              onOpenOriginal={
                data.original_cv.source === "snapshot" && data.original_cv.stage_id
                  ? () => setOriginalOpen(true)
                  : undefined
              }
            />
          ) : null}
        </div>
        {data?.original_cv.stage_id ? (
          <CVOriginalPreviewModal
            open={originalOpen}
            onOpenChange={setOriginalOpen}
            stageId={data.original_cv.stage_id}
            jobTitle={data.job_title}
            candidateName={data.candidate_name}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
