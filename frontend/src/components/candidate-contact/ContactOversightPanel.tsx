"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  ClockAlert,
  PhoneOff,
  RefreshCw,
  UserRoundX,
  UsersRound,
} from "lucide-react";

import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  candidateContactApi,
  candidateContactFullName,
  candidateContactQueryKeys,
  isCandidateContactVersionConflict,
  type CandidateContactCase,
} from "@/lib/candidate-contact";
import { extractErrorMsg } from "@/lib/api";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";

const OVERSIGHT_REASSIGN_REASON =
  "Automatyczne przepisanie z panelu nadzoru Head of Recruitment";
const REASSIGNABLE_STATUSES = new Set([
  "unassigned",
  "awaiting_capacity",
  "queued",
  "callback_due",
  "blocked_no_phone",
  "handoff_pending",
]);

function formatLag(seconds: number | null | undefined): string {
  if (seconds == null) return "Brak danych";
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export interface ContactOversightPanelProps {
  featureEnabledOverride?: boolean;
}

export function ContactOversightPanel({
  featureEnabledOverride,
}: ContactOversightPanelProps = {}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const contactFeature = useCandidateContactFeature({
    enabledOverride: featureEnabledOverride,
  });
  const query = useQuery({
    queryKey: candidateContactQueryKeys.oversight(),
    queryFn: () => candidateContactApi.oversight({ limit: 8 }),
    enabled: contactFeature.enabled,
    staleTime: 30_000,
  });
  const reassignMutation = useMutation({
    mutationFn: (contactCase: CandidateContactCase) =>
      candidateContactApi.reassign(contactCase.id, {
        expected_version: contactCase.version,
        target_user_id: null,
        reason: OVERSIGHT_REASSIGN_REASON,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: candidateContactQueryKeys.oversight(),
        }),
        queryClient.invalidateQueries({
          queryKey: candidateContactQueryKeys.queue(),
        }),
      ]);
      showSuccess("Kontakt został automatycznie przepisany.");
    },
    onError: (error) => {
      if (isCandidateContactVersionConflict(error)) {
        showError("Kontakt zmienił się w międzyczasie. Dane zostały odświeżone.");
        void query.refetch();
        return;
      }
      showError(
        extractErrorMsg(error) || "Nie udało się przepisać kontaktu.",
      );
    },
  });

  if (!contactFeature.enabled) return null;

  if (query.isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Nadzór kontaktu</CardTitle>
          <CardDescription>
            Nie udało się pobrać danych albo funkcja nie została jeszcze
            aktywowana.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void query.refetch()}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            Spróbuj ponownie
          </Button>
        </CardContent>
      </Card>
    );
  }

  const counters = query.data?.counters;
  const rows = query.data?.items ?? [];
  return (
    // `id` jest LOAD-BEARING: alerty SLA Head of Recruitment
    // (`dashboard_v2.py`) linkują kotwicą wprost tutaj, bo trasa
    // `/candidates/contact-queue` jest dla tej roli zamknięta.
    <Card id="nadzor-kontaktu" className="scroll-mt-24">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UsersRound aria-hidden className="h-4 w-4 text-primary" />
          Nadzór kolejki kontaktu
        </CardTitle>
        <CardDescription>
          Wyjątki wymagające reakcji zespołu. Lag Traffit:{" "}
          {formatLag(counters?.traffit_lag_seconds)}. Status:{" "}
          {counters?.traffit_status ?? "Brak danych"}; wyjątki:{" "}
          {counters?.traffit_exception_count ?? 0}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {counters?.traffit_last_error ? (
          <div
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            Ostatni błąd intake Traffit: {counters.traffit_last_error}
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {[
            {
              label: "Zaległe",
              value: counters?.overdue ?? 0,
              icon: ClockAlert,
            },
            {
              label: "Nieprzydzielone",
              value: counters?.unassigned ?? 0,
              icon: AlertTriangle,
            },
            {
              label: "Brak pojemności",
              value: counters?.awaiting_capacity ?? 0,
              icon: UsersRound,
            },
            {
              label: "Brak numeru",
              value: counters?.blocked_no_phone ?? 0,
              icon: PhoneOff,
            },
            {
              label: "Handoff bez opiekuna",
              value: counters?.ownerless_handoff ?? 0,
              icon: UserRoundX,
            },
            {
              label: "Przepisane dziś",
              value: counters?.reassigned_today ?? 0,
              icon: RefreshCw,
            },
          ].map((counter) => (
            <div key={counter.label} className="rounded-lg bg-muted/60 p-3">
              <counter.icon
                aria-hidden
                className="mb-2 h-4 w-4 text-muted-foreground"
              />
              <p className="text-xl font-semibold tabular-nums text-foreground">
                {counter.value}
              </p>
              <p className="text-xs text-muted-foreground">{counter.label}</p>
            </div>
          ))}
        </div>

        {rows.length > 0 ? (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {rows.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-3 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <Link
                    href={`/candidates/${item.candidate.id}`}
                    className="truncate text-sm font-medium text-foreground hover:text-primary"
                  >
                    {candidateContactFullName(item.candidate)}
                  </Link>
                  <p className="truncate text-xs text-muted-foreground">
                    {item.owner?.name ?? "Brak właściciela"} ·{" "}
                    {item.opportunities.length} rekrutacji
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <ContactStatusBadge contactCase={item} />
                  {REASSIGNABLE_STATUSES.has(item.status) ? (
                    <Button
                      size="sm"
                      variant="outline"
                      loading={
                        reassignMutation.isPending &&
                        reassignMutation.variables?.id === item.id
                      }
                      disabled={reassignMutation.isPending}
                      onClick={() => reassignMutation.mutate(item)}
                    >
                      Przepisz automatycznie
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-lg border border-dashed border-border py-5 text-center text-sm text-muted-foreground">
            Brak wyjątków.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
