"use client";

/**
 * „Jak rozpoznać dobrego kandydata” — pytania screeningowe z sekcji 6 profilu
 * z przetłumaczonymi na zwykły język: po co pytasz, co jest dobrą odpowiedzią
 * i kiedy kandydat odpada. Warunki ustala DL w profilu; AI ich nie dopisuje,
 * dlatego pod każdą kartą jest oryginalne brzmienie z profilu.
 */

import type { ReactNode } from "react";

import type { ScreeningPlain } from "@/lib/api/plainKnowledge";
import { cn } from "@/lib/utils";

import { PlainEyebrow } from "./PlainBits";

function Row({
  label,
  tone = "muted",
  children,
}: {
  label: string;
  tone?: "muted" | "good" | "bad";
  children: ReactNode;
}) {
  return (
    <>
      <dt
        className={cn(
          "pt-0.5 text-[11px] font-semibold uppercase tracking-wide",
          tone === "good"
            ? "text-success"
            : tone === "bad"
              ? "text-destructive"
              : "text-muted-foreground",
        )}
      >
        {label}
      </dt>
      <dd className="mb-1.5 min-w-0 break-words text-[13px] leading-snug text-foreground sm:mb-0">
        {children}
      </dd>
    </>
  );
}

function ScreeningCard({ item, index }: { item: ScreeningPlain; index: number }) {
  const ideal = item.original?.ideal_answer?.trim() || null;
  const breaker = item.original?.deal_breaker?.trim() || null;
  return (
    <li className="rounded-lg border border-border bg-card p-3.5" data-testid="plain-screening-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 flex-1 break-words text-sm font-medium text-foreground">
          {item.question}
        </p>
        <span className="shrink-0 rounded-full border border-border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
          sekcja 6 · pytanie {index + 1}
        </span>
      </div>
      <dl className="mt-2.5 grid grid-cols-1 gap-x-3 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-y-1.5">
        {item.why?.trim() ? <Row label="Po co pytasz">{item.why}</Row> : null}
        {item.good?.trim() ? (
          <Row label="Dobra odpowiedź" tone="good">
            {item.good}
          </Row>
        ) : null}
        {item.reject?.trim() ? (
          <Row label="Odpada, gdy" tone="bad">
            {item.reject}
          </Row>
        ) : null}
      </dl>
      {ideal || breaker ? (
        <details className="mt-2 text-[13px]">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
            Tak brzmi w profilu
          </summary>
          <div className="mt-1.5 space-y-1 rounded-md bg-muted/40 px-3 py-2 text-muted-foreground">
            {ideal ? <p>Idealnie: {ideal}</p> : null}
            {breaker ? <p>Odpada, gdy: {breaker}</p> : null}
          </div>
        </details>
      ) : null}
    </li>
  );
}

export function PlainScreeningCards({ items }: { items: readonly ScreeningPlain[] }) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-2" aria-label="Jak rozpoznać dobrego kandydata" data-testid="plain-screening">
      <div className="space-y-0.5">
        <PlainEyebrow>Jak rozpoznać dobrego kandydata</PlainEyebrow>
        <p className="text-xs text-muted-foreground">
          Pytania, dobre odpowiedzi i powody odrzucenia ustalił DL w profilu. AI tylko zamienia
          trudne słowa na zrozumiałe i nie dopisuje nowych warunków.
        </p>
      </div>
      <ol className="list-none space-y-2">
        {items.map((item, index) => (
          <ScreeningCard key={item.question_id || `${index}`} item={item} index={index} />
        ))}
      </ol>
    </section>
  );
}
