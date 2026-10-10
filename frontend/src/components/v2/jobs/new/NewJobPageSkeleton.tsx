import { Skeleton } from "@/components/ui/skeleton";

/**
 * Szkielet strony `/jobs/new` — na czas, zanim znamy tożsamość (store auth
 * czyta localStorage dopiero po montażu shella) i zanim dotrze kod strony.
 * Do 23.09.2026 w tym oknie strona zwracała `null` i przez ~4 s na produkcji
 * był pusty obszar treści pod samym shellem.
 *
 * Układ jak na stronie od 10.10.2026: pasek „klient + Wypełnij z:”, pasek
 * sekcji i formularz na całą szerokość (treść requestu dochodzi obok dopiero
 * po odczycie).
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
      className="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-4 pt-6 md:px-8"
    >
      <span className="sr-only">Ładowanie formularza nowej rekrutacji…</span>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-4 w-[28rem] max-w-full" />
      </div>
      {/* Pasek źródeł: klient i trzy akcje w jednym rzędzie. */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:p-4 lg:flex-row lg:items-center lg:gap-6">
        <Skeleton className="h-9 w-full lg:w-80" />
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-8 w-32" />
        </div>
      </div>
      <Skeleton className="h-11 w-full rounded-xl" />
      {Array.from({ length: 2 }).map((_, section) => (
        <div
          key={section}
          className="flex flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6"
        >
          <Skeleton className="h-5 w-40" />
          <div className="grid gap-4 md:grid-cols-2">
            {Array.from({ length: 4 }).map((__, field) => (
              <div key={field} className="flex flex-col gap-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-10 w-full" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
