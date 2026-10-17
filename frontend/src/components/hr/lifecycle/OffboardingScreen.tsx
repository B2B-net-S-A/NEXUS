"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Card } from "@/components/ui/card";
import { usePerson, type HrConfig } from "@/lib/api/hr";
import { usePersonLifecycleSummary } from "@/lib/api/hr-lifecycle";
import { resolveViewState } from "@/lib/view-state";

import { BackLink, OffboardingCase } from "./OffboardingCaseView";
import { OffboardingStartForm } from "./OffboardingStartForm";

/** Ekran odejścia: formularz (gdy nie ma sprawy) albo sprawa z przekazaniem pracy. */
export function OffboardingScreen({ userId, config }: { userId: number; config: HrConfig }) {
  const summary = usePersonLifecycleSummary(userId);
  const person = usePerson(userId);
  const state = resolveViewState({
    isLoading: summary.isLoading || person.isLoading,
    isError: summary.isError || person.isError,
    error: summary.error ?? person.error,
    isSuccess: summary.isSuccess && person.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  if (state !== "ready" || !summary.data || !person.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Nie ma takiej kartoteki albo moduł „Wejście i odejście” jest wyłączony."
            : undefined
        }
        onRetry={() => {
          void summary.refetch();
          void person.refetch();
        }}
      />
    );
  }
  const latest = summary.data.case;
  const showCase = latest && latest.kind === "offboarding" && latest.status !== "cancelled";
  if (showCase) {
    return <OffboardingCase caseId={latest.id} />;
  }
  const canManage = config.me.people_admin || config.me.is_admin;
  return (
    <div className="space-y-4">
      <BackLink userId={userId} name={person.data.name} />
      <h1 className="text-xl font-semibold text-foreground">
        Odejście · {person.data.name}
      </h1>
      {canManage ? (
        <OffboardingStartForm
          userId={userId}
          defaultManagerId={person.data.manager_user_id}
        />
      ) : (
        <Card className="p-4 text-sm text-muted-foreground">
          Ta osoba nie ma sprawy odejścia. Odejście zakładają Kadry.
        </Card>
      )}
    </div>
  );
}
