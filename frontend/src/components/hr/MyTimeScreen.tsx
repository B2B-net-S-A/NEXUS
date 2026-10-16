"use client";

import Link from "next/link";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Card } from "@/components/ui/card";
import { useMyHrProfile, type HrConfig } from "@/lib/api/hr";
import { resolveViewState } from "@/lib/view-state";

import { formatDays } from "./people/hr-format";

function warsawYear(): number {
  return Number(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric" }).format(
      new Date(),
    ),
  );
}

/** „Mój czas” — własne urlopy, miesiąc pracy i premie (moduły włączane etapami). */
export function MyTimeScreen({ config }: { config: HrConfig }) {
  const me = useMyHrProfile();
  const year = warsawYear();
  const state = resolveViewState({
    isLoading: me.isLoading,
    isError: me.isError,
    error: me.error,
    isSuccess: me.isSuccess,
  });

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <PageHeader
        title="Mój czas"
        description="Urlopy, miesiąc pracy i premie w jednym miejscu."
        density="compact"
      />
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !me.data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => me.refetch()}
        />
      ) : !me.data.has_profile ? (
        <Card className="p-5 text-sm text-muted-foreground">
          Nie masz jeszcze kartoteki pracownika. Poproś Kadry o jej założenie —
          bez niej nie złożysz wniosku urlopowego ani nie wyślesz timesheetu.
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="space-y-1 p-5">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Urlop {year}
            </h2>
            {(() => {
              const pool = me.data.entitlements?.find((row) => row.year === year);
              if (!pool) {
                return (
                  <p className="text-sm text-muted-foreground">
                    Pula na {year} nie jest ustawiona — zrobią to Kadry.
                  </p>
                );
              }
              return (
                <p className="text-sm text-foreground">
                  Pula:{" "}
                  <strong>
                    {pool.entitlement_days == null
                      ? "bez puli"
                      : `${formatDays(pool.entitlement_days)} dni`}
                  </strong>
                  {Number(pool.carried_over_days) > 0
                    ? ` + ${formatDays(pool.carried_over_days)} dni zaległego`
                    : ""}
                </p>
              );
            })()}
            {!config.open_modules.leave ? (
              <p className="text-xs text-muted-foreground">
                Wnioski urlopowe ruszą po włączeniu modułu urlopów.
              </p>
            ) : null}
          </Card>
          <Card className="space-y-1 p-5">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Moja kartoteka
            </h2>
            <p className="text-sm text-foreground">
              {[me.data.job_title, me.data.department].filter(Boolean).join(" · ") ||
                "Stanowisko nieuzupełnione"}
            </p>
            <Link
              href={`/people/${me.data.user_id}`}
              className="text-sm text-primary hover:underline"
            >
              Otwórz kartotekę
            </Link>
          </Card>
        </div>
      )}
    </div>
  );
}
