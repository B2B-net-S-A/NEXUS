import { Skeleton } from "@/components/ui/skeleton";

/**
 * Szkielet strony `/jobs/new` (krok 1: klient + request) — na czas, zanim
 * znamy tożsamość (store auth czyta localStorage dopiero po montażu shella)
 * i zanim dotrze kod strony. Do 23.09.2026 w tym oknie strona zwracała `null`
 * i przez ~4 s na produkcji był pusty obszar treści pod samym shellem.
 *
 * Bez hooków i bez „use client” — renderuje się też w `loading.tsx` i w HTML-u
 * z serwera, czyli widać go od pierwszego malowania.
 */
export function NewJobPageSkeleton() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Ładowanie formularza nowej rekrutacji"
      data-testid="new-job-skeleton"
      className="mx-auto flex w-full max-w-[1400px] flex-col gap-6 px-4 pt-6 md:px-8"
    >
      <span className="sr-only">Ładowanie formularza nowej rekrutacji…</span>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-[28rem] max-w-full" />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-6 w-36 rounded-full" />
        </div>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-5 rounded-xl border border-border bg-card p-6">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-56 w-full" />
          </div>
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-10 w-44" />
            <Skeleton className="h-10 w-40" />
          </div>
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6">
          <Skeleton className="h-4 w-44" />
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-3/4" />
          ))}
        </div>
      </div>
    </div>
  );
}
