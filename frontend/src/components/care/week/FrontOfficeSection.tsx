"use client";

import { useState } from "react";
import Link from "next/link";

import { DetailSection } from "@/components/ds/DetailPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { apiErrorMessage } from "@/lib/api-error";
import { useFrontOffice, useHandOffToFrontOffice, type HandoffResult } from "@/lib/api/care";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { formatDayMonthPl } from "@/lib/date-pl";

import { frontOfficeText } from "./week-format";

/** Zdanie po przekazaniu: kto naprawdę dostał powiadomienie. */
export function handoffToast(result: HandoffResult): { text: string; tone: "success" | "info" } {
  if (!result.notified.length) {
    return {
      text: "Przekazano do front office, ale nikt nie dostał powiadomienia — daj znać osobiście.",
      tone: "info",
    };
  }
  return {
    text: `Przekazano do front office. Powiadomieni: ${result.notified.map((p) => p.name).join(", ")}.`,
    tone: "success",
  };
}

/**
 * „Przekaż do front office” — konsultant kończy projekt w ciągu 60 dni albo
 * chce zmiany. Pasujące rekrutacje liczy silnik „Pasuje też do” (serwer);
 * przycisk zostawia ślad i powiadamia front office, bez osobnego maila.
 */
export function FrontOfficeSection({ contractId }: { contractId: number }) {
  const { showToast } = useToast();
  const query = useFrontOffice(contractId);
  const handOff = useHandOffToFrontOffice(contractId);
  const [unchecked, setUnchecked] = useState<Set<number>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const data = query.data;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: !data?.eligible,
  });
  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Szukanie pasujących rekrutacji…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description="Nie udało się sprawdzić pasujących rekrutacji."
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!data.eligible) return null;
  const chosen = data.jobs.filter((job) => !unchecked.has(job.job_id)).map((job) => job.job_id);
  const last = data.handoffs[data.handoffs.length - 1];

  const submit = () => {
    setError(null);
    handOff.mutate(chosen, {
      onSuccess: (result) => {
        const message = handoffToast(result);
        showToast(message.text, message.tone);
      },
      onError: (err) =>
        setError(apiErrorMessage(err, "Nie udało się przekazać do front office.")),
    });
  };

  return (
    <DetailSection title="Front office">
      <p className="text-sm">
        {frontOfficeText(data.reasons)}
        {data.end_date ? ` · koniec ${formatDayMonthPl(data.end_date)}` : ""}
      </p>
      {data.status === "unavailable" ? (
        <p className="text-sm text-muted-foreground">
          Nie udało się sprawdzić pasujących rekrutacji (wyszukiwanie chwilowo nie działa).
          Przekazanie i tak dojdzie do front office.
        </p>
      ) : data.jobs.length ? (
        <ul className="space-y-1.5" aria-label="Pasujące otwarte rekrutacje">
          {data.jobs.map((job) => {
            const id = `care-fo-job-${job.job_id}`;
            return (
              <li key={job.job_id} className="flex items-start gap-2">
                {data.can_edit ? (
                  <Checkbox
                    id={id}
                    className="mt-0.5"
                    checked={!unchecked.has(job.job_id)}
                    onCheckedChange={(value) =>
                      setUnchecked((prev) => {
                        const next = new Set(prev);
                        if (value === true) next.delete(job.job_id);
                        else next.add(job.job_id);
                        return next;
                      })
                    }
                    aria-label={`Dołącz rekrutację ${job.title}`}
                  />
                ) : null}
                <div className="min-w-0 text-sm">
                  <Link href={`/jobs/${job.job_id}`} className="font-medium hover:underline">
                    {job.client_reference ? `${job.client_reference} · ` : ""}
                    {job.title}
                  </Link>
                  <span className={CALM_SUBLINE}>
                    {[job.client_name, `dopasowanie ${job.score}`].filter(Boolean).join(" · ")}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Żadna otwarta rekrutacja nie pasuje teraz na tyle, żeby ją podpowiedzieć.
        </p>
      )}
      {last ? (
        <p className="text-xs text-muted-foreground">
          Przekazano {formatDayMonthPl(last.on)}
          {last.by ? ` · ${last.by.name}` : ""}
          {` · powiadomieni: ${last.notified_count}`}
        </p>
      ) : null}
      {data.can_edit ? (
        <div>
          <Button size="sm" onClick={submit} disabled={handOff.isPending}>
            {handOff.isPending
              ? "Przekazywanie…"
              : last
                ? "Przekaż ponownie"
                : "Przekaż do front office"}
          </Button>
          <p className="mt-1 text-xs text-muted-foreground">
            Powiadomienie dostaną Delivery Leadzi zaznaczonych rekrutacji i klienta oraz Head of
            Recruitment z dostępem do opieki. Wpis „Do przepięcia” przejdzie na „W toku”.
          </p>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </DetailSection>
  );
}
