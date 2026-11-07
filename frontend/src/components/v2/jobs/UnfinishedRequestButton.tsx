"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import {
  fetchIntakeForms,
  jobIntakeFormKeys,
  type IntakeFormListItem,
} from "@/lib/api/jobIntakeForms";
import { Button } from "@/components/ui/button";

const DAY_MONTH = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Warsaw",
});

/** „05.11” — dzień ostatniej zmiany formularza w kalendarzu firmy. */
export function draftDayLabel(updatedAt: string): string | null {
  const date = new Date(updatedAt);
  return Number.isNaN(date.getTime()) ? null : DAY_MONTH.format(date);
}

/** Najświeższy formularz — serwer oddaje je od ostatnio zmienianego, ale nie polegamy na tym. */
export function newestDraft(
  items: readonly IntakeFormListItem[],
): IntakeFormListItem | null {
  let best: IntakeFormListItem | null = null;
  for (const item of items) {
    if (!best || Date.parse(item.updated_at) > Date.parse(best.updated_at)) best = item;
  }
  return best;
}

/**
 * „Dokończ szkic requestu z 05.11 →” w nagłówku listy `/jobs` (07.11.2026,
 * pytanie do Jarvisa z 20.10: „gdzie request, który zacząłem dodawać?”).
 * Niedokończony formularz `/jobs/new` żyje na koncie autora i był widoczny
 * dopiero po kliknięciu „Nowa rekrutacja”. Przycisk otwiera najświeższy
 * (`/jobs/new?form=<id>`); pozostałe są na pustej stronie „Nowa rekrutacja”.
 *
 * Tylko dla osób, które zakładają rekrutacje (`job.create` = to samo
 * uprawnienie co `GET /api/job-intake/forms`). Awaria zapytania nie pokazuje
 * nic — to skrót, a lista formularzy stoi też na „Nowa rekrutacja”.
 */
export function UnfinishedRequestButton({ enabled }: { enabled: boolean }) {
  const { data } = useQuery({
    queryKey: jobIntakeFormKeys.list,
    queryFn: fetchIntakeForms,
    enabled,
    staleTime: 30_000,
    retry: false,
  });
  const draft = enabled && data ? newestDraft(data) : null;
  if (!draft) return null;

  const day = draftDayLabel(draft.updated_at);
  const text = day ? `Dokończ szkic requestu z ${day}` : "Dokończ szkic requestu";
  const others = (data?.length ?? 1) - 1;
  const what = [draft.client_name, draft.label].filter(Boolean).join(" · ");
  const title = [
    what || null,
    others > 0 ? `Pozostałe niedokończone (${others}) są na „Nowa rekrutacja”.` : null,
  ]
    .filter(Boolean)
    .join(" — ");

  return (
    <Button size="sm" variant="outline" asChild>
      <Link
        href={`/jobs/new?form=${draft.id}`}
        title={title || undefined}
        data-testid="jobs-list-unfinished-request"
      >
        {text}
        <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
    </Button>
  );
}
