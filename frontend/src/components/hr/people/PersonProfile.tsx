"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Pencil } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  EMPLOYMENT_STATUS_LABELS,
  EMPLOYMENT_TYPE_LABELS,
  LOCATION_LABELS,
  isFullPerson,
  usePeople,
  usePerson,
  type HrConfig,
  type PersonFull,
} from "@/lib/api/hr";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { resolveViewState } from "@/lib/view-state";
import { ROLE_LABELS } from "@/store/auth";
import { PersonEquipmentPanel } from "@/components/equipment/PersonEquipmentPanel";
import { LifecycleProfileSection } from "@/components/hr/lifecycle/LifecycleProfileSection";
import { PayrollProfileSection } from "@/components/hr/payroll/PayrollProfileSection";
import { formatIsoDatePl } from "@/lib/date-pl";

import { EditProfileDialog } from "./EditProfileDialog";
import { EntitlementDialog } from "./EntitlementDialog";
import { poolAllowed } from "./form-rules";
import { STATUS_TONE, formatDays, personInitials } from "./hr-format";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
      {children}
    </h3>
  );
}

function LeavePoolCard({
  person,
  year,
  canEdit,
}: {
  person: PersonFull;
  year: number;
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const current = person.entitlements?.find((row) => row.year === year);
  // D6: pula płatnych dni na umowie o pracę i na B2B z pulą w umowie; zlecenie bez puli.
  const form = person.employment_type;
  if (!poolAllowed(form)) {
    return (
      <Card className="p-4">
        <CardTitle>Nieobecności {year}</CardTitle>
        <p className="text-sm text-muted-foreground">
          Na umowie zlecenie nie ma puli płatnych dni — nieobecność jest bez wynagrodzenia.
        </p>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <CardTitle>{form === "uop" ? `Urlop ${year}` : `Płatne dni przerwy ${year}`}</CardTitle>
        {canEdit ? (
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Zmień pulę
          </Button>
        ) : null}
      </div>
      {current ? (
        <>
          <Fact label="Pula na rok">
            {current.entitlement_days == null
              ? "bez puli"
              : `${formatDays(current.entitlement_days)} dni`}
          </Fact>
          <Fact label="Zaległy z poprzedniego roku">
            {formatDays(current.carried_over_days)} dni
          </Fact>
          <Fact label="Wykorzystane przed NEXUSEM">
            {formatDays(current.used_initial_days)} dni
          </Fact>
          <p className="mt-2 text-xs text-muted-foreground">
            Saldo po wnioskach policzy moduł urlopów.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Pula na {year} nie jest ustawiona.
        </p>
      )}
      {form === "uop" && person.suggested_entitlement_days ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Wymiar według stażu ({person.leave_seniority_years} lat):{" "}
          {person.suggested_entitlement_days} dni.
        </p>
      ) : null}
      {canEdit && editing ? (
        <EntitlementDialog
          userId={person.user_id}
          name={person.name}
          year={year}
          current={current}
          employmentType={form}
          suggestedDays={person.suggested_entitlement_days ?? null}
          open={editing}
          onOpenChange={setEditing}
        />
      ) : null}
    </Card>
  );
}

/** Kartoteka osoby — zakres (wizytówka / pełna) wyznacza serwer. */
export function PersonProfile({ userId, config }: { userId: number; config: HrConfig }) {
  const person = usePerson(userId);
  const canEdit = config.me.people_admin;
  const directory = usePeople();
  const [editing, setEditing] = useState(false);
  // Pula liczona na rok kalendarzowy osoby czytającej (Europe/Warsaw jak serwer).
  const year = useMemo(
    () =>
      Number(
        new Intl.DateTimeFormat("en-CA", {
          timeZone: "Europe/Warsaw",
          year: "numeric",
        }).format(new Date()),
      ),
    [],
  );

  const state = resolveViewState({
    isLoading: person.isLoading,
    isError: person.isError,
    error: person.error,
    isSuccess: person.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie kartoteki…</p>;
  }
  if (state !== "ready" || !person.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Nie ma takiej kartoteki albo moduł „Ludzie” jest wyłączony."
            : undefined
        }
        onRetry={() => person.refetch()}
      />
    );
  }

  const data = person.data;
  const full = isFullPerson(data) ? data : null;
  // Słowa formy (D4); wizytówka nie zna formy umowy, więc mówi oba słowa.
  const words = full ? employmentTerms(full.employment_type) : null;
  const managers = (directory.data?.items ?? []).map((row) => ({
    user_id: row.user_id,
    name: row.name,
  }));

  return (
    <div className="space-y-4">
      <Link
        href="/people"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Ludzie
      </Link>
      <header className="flex flex-wrap items-start gap-4">
        <span
          aria-hidden
          className="grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-base font-semibold text-primary"
        >
          {personInitials(data.name)}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold text-foreground">
            {data.name}
            <StatusDot tone={STATUS_TONE[data.employment_status]}>
              {EMPLOYMENT_STATUS_LABELS[data.employment_status]}
            </StatusDot>
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {[data.job_title, data.department].filter(Boolean).join(" · ") ||
              "Stanowisko nieuzupełnione"}
            {data.manager_name ? (
              <>
                {` · ${words ? words.coordinator : "przełożony / koordynator"}: `}
                <Link
                  className="hover:text-foreground hover:underline"
                  href={`/people/${data.manager_user_id}`}
                >
                  {data.manager_name}
                </Link>
              </>
            ) : null}
          </p>
        </div>
        {canEdit && full ? (
          <Button variant="outline" onClick={() => setEditing(true)}>
            <Pencil className="h-4 w-4" aria-hidden />
            Edytuj kartotekę
          </Button>
        ) : null}
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-4">
          <CardTitle>Kontakt i miejsce pracy</CardTitle>
          <Fact label="E-mail">{data.email}</Fact>
          <Fact label="Telefon służbowy">{data.phone ?? "—"}</Fact>
          <Fact label="Domyślnie pracuje">
            {LOCATION_LABELS[data.default_location]}
          </Fact>
        </Card>
        {full ? (
          <>
            <Card className="p-4">
              <CardTitle>Zatrudnienie</CardTitle>
              <Fact label="Forma">{EMPLOYMENT_TYPE_LABELS[full.employment_type]}</Fact>
              <Fact label="Start pracy">{formatIsoDatePl(full.work_start_date)}</Fact>
              <Fact label="Ostatni dzień pracy">
                {full.last_working_day ? formatIsoDatePl(full.last_working_day) : "—"}
              </Fact>
              <Fact label={words?.timesheet ?? "Timesheet"}>
                {full.timesheet_required ? "tak" : "nie"}
              </Fact>
              <Fact label="Nadgodziny">{full.can_log_overtime ? "tak" : "nie"}</Fact>
              {full.employment_type === "zlecenie" ? (
                <Fact label="Uczeń lub student">
                  {full.student_contribution_exempt
                    ? full.contribution_exempt_until
                      ? `bez składek do ${formatIsoDatePl(full.contribution_exempt_until)}`
                      : "tak — brak daty końca zwolnienia"
                    : "nie"}
                </Fact>
              ) : null}
              {full.employment_type === "zlecenie" && full.contributions_from ? (
                <Fact label="Składki od">{formatIsoDatePl(full.contributions_from)}</Fact>
              ) : null}
              {full.employment_type === "uop" ? (
                <>
                  <Fact label="Staż do urlopu">
                    {full.leave_seniority_years == null
                      ? "—"
                      : `${full.leave_seniority_years} lat`}
                  </Fact>
                  <Fact label="Zaświadczenie z ZUS">
                    {full.zus_certificate_received_on
                      ? formatIsoDatePl(full.zus_certificate_received_on)
                      : "—"}
                  </Fact>
                </>
              ) : null}
            </Card>
            <LeavePoolCard person={full} year={year} canEdit={canEdit} />
            <Card className="p-4 lg:col-span-3">
              <CardTitle>W NEXUSIE</CardTitle>
              <p className="text-sm text-foreground">
                {full.roles
                  .map((role) => ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? role)
                  .join(", ")}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Role i uprawnienia zmienia się w Ustawieniach → Osoby i role.
              </p>
            </Card>
          </>
        ) : (
          <Card className="p-4 lg:col-span-2">
            <p className="text-sm text-muted-foreground">
              Pełną kartotekę widzą ta osoba, jej przełożony i Kadry.
            </p>
          </Card>
        )}
      </div>

      {/* Moduły „Ludzi w NEXUSIE” — każda sekcja sama chowa się przy braku
          dostępu (403/404) albo wyłączonym module. */}
      <LifecycleProfileSection userId={userId} config={config} />
      {config.open_modules.payroll ? (
        <PayrollProfileSection userId={userId} name={data.name} />
      ) : null}
      {config.open_modules.equipment &&
      (config.me.equipment || config.me.people_admin || config.me.is_admin) ? (
        <PersonEquipmentPanel userId={userId} />
      ) : null}

      {canEdit && full && editing ? (
        <EditProfileDialog
          person={full}
          open={editing}
          onOpenChange={setEditing}
          managers={managers}
        />
      ) : null}
    </div>
  );
}
