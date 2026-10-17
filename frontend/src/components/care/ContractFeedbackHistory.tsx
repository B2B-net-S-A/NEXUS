"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EXTENSION_LABELS,
  FEEDBACK_CHANNEL_LABELS,
  SCORE_LABELS,
  formatAverage,
  useContractFeedback,
  type ScoreField,
} from "@/lib/api/client-people";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

const FIELDS: ScoreField[] = ["quality", "communication", "autonomy"];

/**
 * „Opinie klienta” w zakładce „Opieka” kontraktu — krótka historia ocen tego
 * konsultanta od menedżera u klienta (D9–D11). Zapis jest w zakładce klienta
 * „Struktura u klienta”, bo jedna rozmowa obejmuje zwykle kilka osób.
 */
export function ContractFeedbackHistory({
  contractId,
  clientId,
}: {
  contractId: number;
  clientId: number;
}) {
  const query = useContractFeedback(contractId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (query.data?.items.length ?? 0) === 0,
  });
  return (
    <section
      aria-labelledby="contract-feedback-history"
      className="space-y-2 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="contract-feedback-history" className="text-sm font-semibold">
          Opinie klienta
        </h3>
        <Link
          href={`/clients/${clientId}?tab=struktura`}
          className="text-xs text-primary hover:underline"
        >
          Struktura u klienta i zapis opinii
        </Link>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie opinii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={
            state === "error"
              ? undefined
              : apiErrorMessage(query.error, "Nie możesz zobaczyć opinii klienta.")
          }
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          Brak opinii klienta o tym konsultancie.
        </p>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {query.data?.items.map((item) => (
            <li key={item.session_id} className="py-2">
              <p>
                <span className="font-medium tabular-nums">{formatIsoDatePl(item.held_on)}</span>
                <span className="text-muted-foreground">
                  {" · "}
                  {FEEDBACK_CHANNEL_LABELS[item.channel]}
                  {item.contact ? ` · ${item.contact.name}` : ""}
                </span>
              </p>
              <p className="text-xs">
                {FIELDS.filter((field) => item[field] != null)
                  .map((field) => `${SCORE_LABELS[field]} ${item[field]}`)
                  .join(" · ")}
                {" · średnio "}
                {formatAverage(item.average)}
                {item.extension_outlook
                  ? ` · przedłużenie: ${EXTENSION_LABELS[item.extension_outlook]}`
                  : ""}
              </p>
              {item.note ? (
                <p className="mt-0.5 line-clamp-3 whitespace-pre-line text-xs text-muted-foreground">
                  {item.note}
                </p>
              ) : null}
              {item.author ? <span className={CALM_SUBLINE}>zapisał(a): {item.author.name}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
