"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { useStartBotPeople, type useCompanyDecisionMap } from "@/lib/api/sales-bot-people";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { safeHref } from "../format";

interface CompanyDecisionMapProps {
  companyId: number;
  query: ReturnType<typeof useCompanyDecisionMap>;
}

export function CompanyDecisionMap({ companyId, query }: CompanyDecisionMapProps) {
  const start = useStartBotPeople("cognism");
  const { showError, showSuccess } = useToast();
  const state = resolveViewState({
    isLoading: query.isLoading,
    isSuccess: query.isSuccess,
    error: query.error,
  });

  if (state === "loading") {
    return <p role="status" className="text-sm text-muted-foreground">Wczytywanie mapy decydentów…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data?.enabled) {
    return <p className="text-sm text-muted-foreground">Mapa decydentów jest wyłączona.</p>;
  }
  return (
    <Card className="space-y-3 p-4" data-tour="sales.company.decision-map">
      {(query.data.can_start || query.data.running) && (
        <div className="flex flex-wrap items-center gap-3">
          {query.data.can_start && (
            <Button
              size="sm"
              variant="outline"
              loading={start.isPending}
              disabled={query.data.running}
              onClick={() => start.mutate(companyId, {
                onSuccess: () => showSuccess("Grok uzupełnia mapę decydentów z Cognism."),
                onError: (error) => showError(apiErrorMessage(error, "Nie udało się zlecić uzupełnienia mapy.")),
              })}
            >
              Uzupełnij z Cognism
            </Button>
          )}
          {query.data.running && (
            <p role="status" className="text-sm text-muted-foreground">Trwa bieg Cognism. Kolejny można zlecić po jego zakończeniu.</p>
          )}
        </div>
      )}
      {query.data.people.length === 0 ? (
        <p className="text-sm text-muted-foreground">Na mapie tej firmy nie ma jeszcze decydentów.</p>
      ) : <ul aria-label="Mapa decydentów" className="divide-y divide-border">
        {query.data.people.map((person) => {
          const source = safeHref(person.source_url);
          return (
            <li key={`${person.source_url}:${person.full_name}`} className="grid gap-3 py-4 lg:grid-cols-3">
              <div className="min-w-0">
                <p className="break-words text-sm font-medium text-foreground">{person.full_name}</p>
                <p className="break-words text-sm text-muted-foreground">{person.title}</p>
                <StatusDot tone={person.active ? "success" : "neutral"}>
                  {person.active ? "Aktywna rola" : "Nieaktywna rola"}
                </StatusDot>
              </div>
              <dl className="space-y-2 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">E-mail służbowy</dt>
                  <dd className="break-words">{person.email ?? "—"}</dd>
                  {person.email && person.email_observed_at && (
                    <dd className="text-xs text-muted-foreground">
                      Sprawdzono <time dateTime={person.email_observed_at}>{formatIsoDatePl(person.email_observed_at)}</time>
                    </dd>
                  )}
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Telefon służbowy</dt>
                  <dd className="break-words tabular-nums">{person.phone ?? "—"}</dd>
                  {person.phone && person.phone_type === "direct" && (
                    <dd className="text-xs text-muted-foreground">Bezpośredni</dd>
                  )}
                  {person.phone && person.phone_type === "mobile" && (
                    <dd className="text-xs text-muted-foreground">
                      {person.verified_mobile ? "Komórkowy · zweryfikowany" : "Komórkowy"}
                    </dd>
                  )}
                  {person.phone && person.phone_observed_at && (
                    <dd className="text-xs text-muted-foreground">
                      Sprawdzono <time dateTime={person.phone_observed_at}>{formatIsoDatePl(person.phone_observed_at)}</time>
                    </dd>
                  )}
                </div>
              </dl>
              <dl className="space-y-2 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">Źródło</dt>
                  <dd>
                    {source ? (
                      <a href={source} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                        Cognism
                      </a>
                    ) : "Cognism"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Stanowisko sprawdzone</dt>
                  <dd><time dateTime={person.observed_at}>{formatIsoDatePl(person.observed_at)}</time></dd>
                </div>
              </dl>
            </li>
          );
        })}
      </ul>}
    </Card>
  );
}
