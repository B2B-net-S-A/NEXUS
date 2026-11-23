"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { safeHref } from "@/components/sales/format";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { useCompanyPeople } from "@/lib/api/sales";
import { useCompanyDecisionMap } from "@/lib/api/sales-bot-people";
import {
  type Potential,
  type PotentialResult,
  useCompanyPotential,
  useStartPotential,
} from "@/lib/api/sales-potential";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  KIND_LABEL,
  VERDICT_VARIANT,
  eventDate,
  failureText,
  potentialView,
  wordCount,
} from "./potential-format";

// Karta firmy → „Potencjał” (decyzja Artura 23.11.2026, docs/claude/sprzedaz/ocena-potencjalu.md):
// jedna strona dla handlowca przed spotkaniem. Fakty z NEXUSA i research są zawsze,
// ocena modelu to dodatek.

function Section({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("space-y-2 p-4", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {aside && <span className="text-xs text-muted-foreground">{aside}</span>}
      </div>
      {children}
    </Card>
  );
}

function Source({ url }: { url?: string | null }) {
  const href = safeHref(url ?? null);
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
    >
      źródło <ExternalLink className="h-3 w-3" aria-hidden />
    </a>
  );
}

function Score({ value }: { value: number }) {
  return (
    <span className="flex items-center gap-0.5" role="img" aria-label={`${value} z 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={cn("h-2 w-3 rounded-sm", n <= value ? "bg-primary" : "bg-border")} />
      ))}
    </span>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 text-xs">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-foreground">{children}</dd>
    </div>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-xs leading-snug text-muted-foreground">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function NexusFacts({ companyId, result, canEdit }: { companyId: number; result: PotentialResult | null; canEdit: boolean }) {
  const people = useCompanyPeople(companyId);
  const map = useCompanyDecisionMap(companyId, canEdit);
  const counts = people.data?.counts;
  const research = result?.research ?? {};
  const decision = (map.data?.people ?? []).filter((p) => p.active).map((p) => p.title).filter(Boolean);
  return (
    <Section title="Z NEXUSA" aside="liczone z naszych danych">
      <dl className="space-y-1.5">
        {result?.ksc && (
          <Fact label="KSC / NIS2">
            <span className="font-medium">
              {result.ksc.result}
              {result.ksc.entity ? `: podmiot ${result.ksc.entity}` : ""}
            </span>
            <span className="block text-muted-foreground">{result.ksc.why}</span>
          </Fact>
        )}
        {(research.pkd || research.employees) && (
          <Fact label="PKD i wielkość">
            {[research.pkd ? `PKD ${research.pkd}` : null, research.employees || null].filter(Boolean).join(" · ")}
            <Source url={research.facts_url} />
          </Fact>
        )}
        {research.revenue && <Fact label="Przychód">{research.revenue}</Fact>}
        {research.group && <Fact label="Grupa">{research.group}</Fact>}
        <Fact label="Kogo znamy">
          {people.isLoading
            ? "Wczytywanie…"
            : people.isError
              ? "Nie udało się wczytać."
              : counts
                ? `teraz ${counts.current ?? 0} · przez nas ${counts.via_us ?? 0} · kiedyś ${counts.past ?? 0}`
                : "—"}
        </Fact>
        {canEdit && decision.length > 0 && (
          <Fact label="Decydenci">
            {decision.length} na mapie: {decision.slice(0, 4).join(", ")}
          </Fact>
        )}
      </dl>
    </Section>
  );
}

function Research({ data }: { data: Potential }) {
  const research = data.result?.research ?? {};
  const events = research.events ?? [];
  const jobs = research.jobs ?? [];
  const stack = research.stack ?? [];
  return (
    <>
      <Section title="Co się dzieje w firmie" aside="ostatnie 18 miesięcy">
        {events.length === 0 ? (
          <p className="text-xs text-muted-foreground">Bot nie znalazł zdarzeń z ostatnich 18 miesięcy.</p>
        ) : (
          <ul className="space-y-1.5">
            {events.map((event) => (
              <li key={`${event.date}-${event.text}`} className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2 text-xs leading-snug">
                <span className="tabular-nums text-muted-foreground">{eventDate(event.date)}</span>
                <span className="text-foreground">
                  {event.text}
                  <Source url={event.url} />
                  {event.line && data.lines[event.line] && (
                    <span className="block text-muted-foreground">→ {data.lines[event.line]}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      {(jobs.length > 0 || stack.length > 0) && (
        <Section title="IT w firmie" aside={jobs.length ? `ogłoszenia IT: ${jobs.length}` : undefined}>
          {jobs.length > 0 && (
            <ul className="space-y-1">
              {jobs.map((job) => (
                <li key={`${job.url}-${job.title}`} className="text-xs leading-snug text-foreground">
                  {job.title}
                  {job.tech && <span className="text-muted-foreground"> · {job.tech}</span>}
                  {job.contract && <span className="text-muted-foreground"> · {job.contract}</span>}
                  {job.published && (
                    <span className="tabular-nums text-muted-foreground"> · {formatIsoDatePl(job.published)}</span>
                  )}
                  {job.active === false && <span className="text-muted-foreground"> · wygasłe</span>}
                  <Source url={job.url} />
                </li>
              ))}
            </ul>
          )}
          {stack.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-xs leading-snug text-muted-foreground">
              {stack.map((item) => (
                <li key={item.text}>
                  {item.text}
                  <Source url={item.url} />
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </>
  );
}

function Assessed({ data }: { data: Potential }) {
  const { showError, showSuccess } = useToast();
  const result = data.result as PotentialResult;
  const assessment = result.assessment;
  if (!assessment) return null;
  const copy = () => {
    void navigator.clipboard
      ?.writeText(assessment.opening)
      .then(() => showSuccess("Skopiowano wiadomość."))
      .catch(() => showError("Nie udało się skopiować. Zaznacz tekst i skopiuj ręcznie."));
  };
  const groups = Array.from(new Set(assessment.questions.map((q) => q.group)));
  return (
    <>
      <Section title="Dopasowanie do oferty" aside="0–5">
        <ul className="divide-y divide-border">
          {assessment.fit.map((fit) => (
            <li key={fit.line} className="grid grid-cols-[9.5rem_4.5rem_minmax(0,1fr)] items-start gap-2 py-1.5 text-xs leading-snug">
              <span className="font-medium text-foreground">{data.lines[fit.line] ?? fit.line}</span>
              <Score value={fit.score} />
              <span className="text-muted-foreground">
                <span className="text-foreground">{fit.service}</span>
                {fit.horizon && ` · ${fit.horizon}`}
                {fit.need && <span className="block">{fit.need}</span>}
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Referencje do pokazania" aside="z bazy wiedzy">
        {result.references.length === 0 ? (
          <p className="text-xs text-muted-foreground">W bazie wiedzy nie ma referencji, która pasuje do tej firmy.</p>
        ) : (
          <ul className="space-y-2">
            {result.references.map(({ reference, why }) => (
              <li key={reference.id} className="text-xs leading-snug">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-foreground">{reference.client}</span>
                  <Badge variant={reference.kind === "list" ? "success" : reference.kind === "realizacja" ? "info" : "neutral"} size="sm">
                    {KIND_LABEL[reference.kind]}
                  </Badge>
                  {reference.fresh === false && <span className="text-muted-foreground">list starszy niż rok</span>}
                </div>
                {reference.scope && <p className="text-muted-foreground">{reference.scope}</p>}
                {why && <p className="text-foreground">{why}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Pytania na spotkanie">
        <div className="space-y-2">
          {groups.map((group) => (
            <div key={group}>
              <p className="text-xs font-medium text-foreground">{group}</p>
              <Bullets items={assessment.questions.filter((q) => q.group === group).map((q) => q.text)} />
            </div>
          ))}
        </div>
      </Section>
      {assessment.verify.length > 0 && (
        <Section title="Do sprawdzenia na spotkaniu">
          <Bullets items={assessment.verify} />
        </Section>
      )}
      {assessment.risks.length > 0 && (
        <Section title="Ryzyka">
          <Bullets items={assessment.risks} />
        </Section>
      )}
      {assessment.opening && (
        <Section title="Wiadomość otwierająca" aside={`${wordCount(assessment.opening)} słów`}>
          <p className="whitespace-pre-line rounded-md border border-border bg-muted/40 p-2 text-xs leading-snug text-foreground">
            {assessment.opening}
          </p>
          <Button size="sm" variant="outline" className="w-fit" onClick={copy}>
            Kopiuj
          </Button>
        </Section>
      )}
    </>
  );
}

interface PotentialTabProps {
  companyId: number;
  canEdit: boolean;
  archived: boolean;
}

/** Zakładka „Potencjał”: ocena, research i fakty z NEXUSA. */
export function PotentialTab({ companyId, canEdit, archived }: PotentialTabProps) {
  const query = useCompanyPotential(companyId);
  const start = useStartPotential(companyId);
  const { showError } = useToast();
  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });
  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie oceny…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) return null;
  const data = query.data;
  const view = potentialView(data);
  const order = () =>
    start.mutate(undefined, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zamówić oceny.")),
    });
  const orderButton = canEdit && !archived && (
    <Button
      size="sm"
      variant={view === "empty" ? "primary" : "outline"}
      onClick={order}
      disabled={start.isPending || view === "running" || view === "assessing"}
    >
      {view === "empty" ? "Oceń potencjał" : "Odśwież"}
    </Button>
  );

  if (view === "off") {
    return <p className="py-6 text-sm text-muted-foreground">Ocena potencjału jest wyłączona.</p>;
  }
  if (view === "empty") {
    return (
      <Card className="space-y-2 p-4">
        <p className="text-sm text-foreground">Ta firma nie ma jeszcze oceny potencjału.</p>
        <p className="text-xs text-muted-foreground">
          Ocena powstaje sama przed pierwszym spotkaniem. Możesz ją zamówić teraz: bot zbiera dane o firmie,
          potem powstaje ocena, zwykle w kilka minut.
        </p>
        {orderButton}
      </Card>
    );
  }
  const result = data.result;
  const assessment = result?.assessment ?? null;
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">Potencjał współpracy</h2>
              {assessment && (
                <Badge variant={VERDICT_VARIANT[assessment.verdict]} size="md">
                  {assessment.verdict}
                </Badge>
              )}
              {result && (
                <span className="text-xs text-muted-foreground">{formatIsoDatePl(result.assessed_at ?? result.created_at)}</span>
              )}
            </div>
            {view === "running" && (
              <p className="text-sm text-muted-foreground">Bot zbiera dane o firmie, zwykle kilka minut.</p>
            )}
            {view === "assessing" && (
              <p className="text-sm text-muted-foreground">Research jest gotowy, piszę ocenę.</p>
            )}
            {view === "failed" && <p className="text-sm text-muted-foreground">{failureText(data)}</p>}
            {assessment && <p className="max-w-3xl text-sm leading-snug text-foreground">{assessment.summary}</p>}
          </div>
          <div className="flex shrink-0 gap-2">
            {orderButton}
            <Button asChild size="sm" variant="quiet">
              <Link href="/sales/bots/wiedza">Baza wiedzy</Link>
            </Button>
          </div>
        </div>
        {assessment && (
          <div className="grid gap-3 border-t border-border pt-3 md:grid-cols-2">
            <div>
              <p className="text-xs text-muted-foreground">Punkt wejścia</p>
              <p className="text-sm font-semibold text-foreground">{assessment.land.title}</p>
              <p className="text-xs leading-snug text-muted-foreground">{assessment.land.why}</p>
            </div>
            {assessment.expand.length > 0 && (
              <div>
                <p className="text-xs text-muted-foreground">Potem</p>
                <ul className="list-disc space-y-0.5 pl-4 text-xs leading-snug text-foreground">
                  {assessment.expand.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <NexusFacts companyId={companyId} result={result} canEdit={canEdit} />
          {result && <Research data={data} />}
        </div>
        <div className="space-y-4">{assessment && <Assessed data={data} />}</div>
      </div>
    </div>
  );
}
