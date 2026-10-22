"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { MoreHorizontal, Pencil } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { assignmentLabel } from "@/components/equipment/equipment-format";
import { lifecycleSummaryLine } from "@/components/hr/lifecycle/LifecycleProfileSection";
import { CASE_STATUS_TONE } from "@/components/hr/lifecycle/lifecycle-format";
import { usePersonEquipment } from "@/lib/api/equipment";
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
import { usePersonAgreements } from "@/lib/api/hr-agreements";
import { usePersonDocuments } from "@/lib/api/hr-documents";
import { CASE_STATUS_LABELS, usePersonLifecycleSummary } from "@/lib/api/hr-lifecycle";
import { usePersonPayroll } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";
import { isForbiddenError, isNotFoundError, resolveViewState } from "@/lib/view-state";
import { ROLE_LABELS, useAuthStore } from "@/store/auth";
import { PersonEquipmentPanel } from "@/components/equipment/PersonEquipmentPanel";
import { PayrollProfileSection } from "@/components/hr/payroll/PayrollProfileSection";
import { PersonAgreementsSection } from "@/components/hr/people/agreements/PersonAgreementsSection";
import { PersonDocumentsSection } from "@/components/hr/people/documents/PersonDocumentsSection";
import { formatIsoDatePl } from "@/lib/date-pl";

import { BillingDetailsSection } from "./BillingDetailsSection";
import { EditProfileDialog } from "./EditProfileDialog";
import { EmploymentTypeDialog } from "./EmploymentTypeDialog";
import { EntitlementDialog } from "./EntitlementDialog";
import { poolAllowed } from "./form-rules";
import { formLabel, tenureLabel, todayChips, todayKnown } from "./directory-view";
import { STATUS_TONE, formatDays } from "./hr-format";
import { PeopleBackLink } from "./PeopleBackLink";
import { PersonAbsencesHours } from "./PersonAbsencesHours";
import { PersonAvatar } from "./PersonAvatar";
import { TonePill } from "./people-ui";
import {
  TAB_HASH,
  bonusTotals,
  buildTimeline,
  previousRate,
  ringParts,
  tabFromHash,
  type ProfileTab,
  type TimelineTone,
} from "./person-view";

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

/** Fakt w rzędzie pod wizytówką („W firmie · 1 r. 7 mies. · od 03.03.2025”). */
function HeaderFact({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 border-l border-border/60 px-4 py-3 first:border-l-0">
      <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {label}
      </span>
      <span className="truncate text-base font-semibold text-foreground">{value}</span>
      {hint ? <span className="truncate text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

/** Pusta albo zwinięta sekcja jako jedna linia z akcją (zamiast pustej ramki). */
function SectionLine({
  title,
  detail,
  action,
}: {
  title: string;
  detail: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border bg-card px-3 py-2.5">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="truncate text-xs text-muted-foreground">{detail}</div>
      </div>
      {action}
    </div>
  );
}

const TIMELINE_DOT: Record<TimelineTone, string> = {
  success: "bg-success",
  primary: "bg-primary",
  warning: "bg-warning",
  neutral: "bg-muted-foreground/50",
};

/** Pierścień „wykorzystane / zostało” z salda serwera (`leave_balance`). */
function LeaveRingCard({
  person,
  year,
  canEdit,
  onEdit,
}: {
  person: PersonFull;
  year: number;
  canEdit: boolean;
  onEdit: () => void;
}) {
  const ring = ringParts(person.leave_balance);
  const form = person.employment_type;
  // Bez widocznej formy (Kadry bez Płac) tytuł jej nie zdradza.
  const title =
    form === "uop"
      ? `Urlop ${year}`
      : form
        ? `Płatne dni przerwy ${year}`
        : `Pula płatnych dni ${year}`;
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-foreground">{title}</span>
        {canEdit ? (
          <Button size="sm" variant="ghost" onClick={onEdit}>
            Zmień pulę
          </Button>
        ) : null}
      </div>
      {ring ? (
        <div className="flex items-center gap-4">
          <div
            role="img"
            aria-label={`Wykorzystane ${formatDays(ring.used)} z ${formatDays(ring.pool)} dni, zaplanowane ${formatDays(ring.planned)}, zostało ${formatDays(ring.remaining)}`}
            className="grid h-24 w-24 shrink-0 place-items-center rounded-full"
            style={{
              background: `conic-gradient(hsl(var(--primary)) 0 ${ring.usedPct}%, hsl(var(--primary) / 0.35) ${ring.usedPct}% ${ring.usedPct + ring.plannedPct}%, hsl(var(--muted)) ${ring.usedPct + ring.plannedPct}% 100%)`,
            }}
          >
            <div className="grid h-[70px] w-[70px] place-items-center rounded-full bg-card text-center">
              <span className="leading-tight">
                <span className="block text-lg font-bold text-foreground">
                  {formatDays(ring.remaining)}
                </span>
                <span className="block text-[11px] text-muted-foreground">zostało</span>
              </span>
            </div>
          </div>
          <ul className="space-y-1.5 text-[13px]">
            <li className="flex items-center gap-2">
              <span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-primary" />
              wykorzystane {formatDays(ring.used)}
            </li>
            {ring.planned > 0 ? (
              <li className="flex items-center gap-2">
                <span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-primary/35" />
                zaplanowane {formatDays(ring.planned)}
              </li>
            ) : null}
            <li className="flex items-center gap-2">
              <span aria-hidden className="h-2.5 w-2.5 rounded-sm border border-border bg-muted" />
              zostało {formatDays(ring.remaining)}
            </li>
            <li className="text-xs text-muted-foreground">
              pula {formatDays(person.leave_balance?.entitlement_days)}
              {Number(person.leave_balance?.carried_over_days ?? 0) > 0
                ? ` + ${formatDays(person.leave_balance?.carried_over_days)} zaległe`
                : ""}
            </li>
          </ul>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {form && !poolAllowed(form)
            ? "Na umowie zlecenie nie ma puli płatnych dni."
            : person.leave_balance === null
              ? "Pula na ten rok nie jest ustawiona."
              : "Saldo dni pokazuje moduł urlopów."}
        </p>
      )}
    </Card>
  );
}

/** Kartoteka osoby — zakres (wizytówka / pełna) wyznacza serwer. */
export function PersonProfile({ userId, config }: { userId: number; config: HrConfig }) {
  const person = usePerson(userId);
  const canEdit = config.me.people_admin;
  // Formę zmieniają też Finanse (19.10.2026) — osobnym oknem, bo kartotekę edytują Kadry.
  const canChangeForm = !canEdit && (config.me.payroll || config.me.is_admin);
  const viewerId = useAuthStore((state) => state.user?.id);
  // Dane do rozliczeń (M7): osoba, Kadry, Płace, admin — przełożony nie pyta serwera.
  const billingVisible =
    config.open_modules.settlements &&
    (config.me.people_admin || config.me.payroll || config.me.is_admin || viewerId === userId);
  // E-teczka (E4): osoba, Kadry, Płace, recepcja — przełożony nie pyta serwera.
  const documentsVisible =
    config.open_modules.people &&
    (config.me.people_admin ||
      config.me.payroll ||
      config.me.equipment ||
      config.me.is_admin ||
      viewerId === userId);
  // Umowy z ludźmi (E5): Kadry (zapis) i Płace (odczyt).
  const agreementsVisible = config.me.people_admin || config.me.payroll || config.me.is_admin;
  const equipmentVisible =
    config.open_modules.equipment &&
    (config.me.equipment || config.me.people_admin || config.me.is_admin);
  const directory = usePeople();
  const isFull = person.data ? isFullPerson(person.data) : false;
  // Te same klucze zapytań co sekcje w zakładkach — jedno pobranie na ekran.
  const payroll = usePersonPayroll(userId, config.open_modules.payroll);
  const equipment = usePersonEquipment(userId, equipmentVisible);
  const documents = usePersonDocuments(userId, documentsVisible);
  const agreements = usePersonAgreements(userId, agreementsVisible && isFull);
  const lifecycle = usePersonLifecycleSummary(userId, config.open_modules.lifecycle);
  const [editing, setEditing] = useState(false);
  const [changingForm, setChangingForm] = useState(false);
  const [editingPool, setEditingPool] = useState(false);
  const [tab, setTab] = useState<ProfileTab>("overview");
  // `#place` z dzwonka Płac (i reszta kotwic) otwiera właściwą zakładkę.
  useEffect(() => {
    const sync = () => setTab(tabFromHash(window.location.hash));
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const chooseTab = (next: ProfileTab) => {
    setTab(next);
    const hash = TAB_HASH[next];
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}${hash ? `#${hash}` : ""}`,
    );
  };
  // Pula liczona na rok kalendarzowy osoby czytającej (Europe/Warsaw jak serwer).
  const today = warsawToday();
  const year = useMemo(() => Number(today.slice(0, 4)), [today]);

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
  // Słowa formy (D4); wizytówka i forma ukryta (Kadry bez Płac) mówią „koordynator” (PIP, 21.10.2026).
  const words = full?.employment_type ? employmentTerms(full.employment_type) : null;
  // Nadgodziny i premie: słowo z formy osoby, bez formy neutralnie jak B2B
  // („godziny ponad 8 h”, „wynagrodzenie dodatkowe” — decyzja Artura 21.10.2026).
  const payWords = words ?? employmentTerms("b2b");
  const directoryRows = directory.data?.items ?? [];
  const managers = directoryRows.map((row) => ({ user_id: row.user_id, name: row.name }));
  // „Dziś” z katalogu (ta sama reguła co kolumna) — kartoteka sama go nie niesie.
  const fromDirectory = directoryRows.find((row) => row.user_id === userId);
  const todayChip = fromDirectory
    ? todayChips(
        { ...data, today: fromDirectory.today ?? null },
        today,
        todayKnown(config.open_modules),
      )
    : [];

  const pay = payroll.isSuccess ? payroll.data : undefined;
  const rate = pay?.scope === "full" ? pay.current_rate ?? null : null;
  const earlierRate = pay?.scope === "full" ? previousRate(pay.rates ?? [], rate) : null;
  const bonuses = pay ? bonusTotals(pay.bonuses, year) : null;
  const gear = equipment.isSuccess ? equipment.data : undefined;
  const pendingProtocols = (gear?.protocols ?? []).filter((p) => p.status !== "potwierdzony");
  const ring = full ? ringParts(full.leave_balance) : null;
  const docs = documents.isSuccess
    ? documents.data.documents.filter((doc) => !doc.deleted)
    : null;
  const agreementCount = agreements.isSuccess ? agreements.data.agreements.length : null;
  const life = lifecycle.isSuccess ? lifecycle.data : undefined;
  // Odmowa serwera (403/404) chowa linię jak dawniej sekcję; awaria ją zostawia.
  const refused = (error: unknown) => isForbiddenError(error) || isNotFoundError(error);
  const lifeLine = life ? lifecycleSummaryLine(life) : null;
  const lifeCase = life?.case ?? null;
  const canStartExit =
    Boolean(life?.can_manage) &&
    (!lifeCase ||
      lifeCase.status === "cancelled" ||
      (lifeCase.kind === "onboarding" && lifeCase.status === "done"));
  const timeline = buildTimeline({
    workStart: full?.work_start_date ?? full?.hired_on ?? null,
    lastWorkingDay: full?.last_working_day ?? null,
    rates: pay?.scope === "full" ? pay.rates : [],
    bonuses: pay?.bonuses ?? [],
    equipment: gear ? [...gear.active, ...gear.history] : [],
    today,
  });
  const tenure = full ? tenureLabel(full.work_start_date ?? full.hired_on, today) : null;
  const form = formLabel(data);

  const facts: { key: string; label: string; value: ReactNode; hint?: ReactNode }[] = [];
  if (full && (tenure || full.work_start_date)) {
    facts.push({
      key: "tenure",
      label: "W firmie",
      value: tenure ?? "przed startem",
      hint: full.work_start_date ? `od ${formatIsoDatePl(full.work_start_date)}` : undefined,
    });
  }
  if (form) {
    facts.push({
      key: "form",
      label: "Forma",
      value: form,
      hint: full
        ? [
            full.timesheet_required ? (words?.timesheet ?? "raport godzin").toLowerCase() : "bez raportu godzin",
            full.can_log_overtime
              ? `z ${payWords.overtime_instrumental}`
              : `bez ${payWords.overtime_genitive}`,
          ].join(" · ")
        : undefined,
    });
  }
  if (rate) {
    facts.push({
      key: "rate",
      label: "Stawka",
      value: `${formatMoney(rate.hourly_rate, rate.currency)}/h`,
      hint: `od ${formatIsoDatePl(rate.effective_from)}${
        earlierRate ? ` · było ${formatMoney(earlierRate.hourly_rate, earlierRate.currency)}` : ""
      }`,
    });
  }
  if (ring) {
    facts.push({
      key: "leave",
      label: full?.employment_type === "uop" ? "Urlop" : "Dni przerwy",
      value: `${formatDays(ring.remaining)} dnia`,
      hint: `zostało z ${formatDays(ring.pool)}`,
    });
  }
  if (bonuses && (bonuses.granted > 0 || bonuses.waiting > 0)) {
    facts.push({
      key: "bonus",
      label: `${capitalize(payWords.bonuses)} ${year}`,
      value: formatMoney(bonuses.granted, bonuses.currency),
      hint:
        bonuses.waiting > 0 ? `+ ${formatMoney(bonuses.waiting, bonuses.currency)} czeka` : undefined,
    });
  }
  if (gear) {
    facts.push({
      key: "gear",
      label: "Sprzęt",
      value: `${gear.active.length} szt.`,
      hint:
        gear.active.length === 0
          ? "nic nie wydano"
          : pendingProtocols.length > 0
            ? "protokół czeka na potwierdzenie"
            : "protokół potwierdzony",
    });
  }

  // Odmowa płac (403/404) chowa ich część; awaria (np. 500) to nie brak dostępu.
  const payrollRefused = payroll.isError && refused(payroll.error);
  const payrollShown = config.open_modules.payroll && !payrollRefused;
  // Dane do rozliczeń stoją w tej zakładce — Kadry bez Płac i wyłączony moduł
  // płac też muszą do nich dojść (audyt 21.10.2026).
  const tabs: { value: ProfileTab; label: string; count?: number }[] = [
    { value: "overview", label: "Przegląd" },
    // „Nieobecności i godziny” (22.10.2026, dawniej „Czas i przerwy”; kotwica `#czas` bez zmian).
    ...(full ? [{ value: "time" as const, label: "Nieobecności i godziny" }] : []),
    ...(payrollShown || (full && billingVisible)
      ? [
          {
            value: "payroll" as const,
            label: `Płace i ${payWords.bonuses}`,
            count: bonuses?.waitingCount ? bonuses.waitingCount : undefined,
          },
        ]
      : []),
    ...(documentsVisible ? [{ value: "documents" as const, label: "Dokumenty" }] : []),
    ...(full && agreementsVisible ? [{ value: "agreements" as const, label: "Umowy" }] : []),
    ...(equipmentVisible
      ? [{ value: "equipment" as const, label: "Sprzęt", count: gear?.active.length || undefined }]
      : []),
    { value: "history", label: "Historia" },
  ];
  const activeTab = tabs.some((item) => item.value === tab) ? tab : "overview";

  return (
    <div className="space-y-4">
      <PeopleBackLink />

      <Card className="overflow-hidden p-0">
        <header className="flex flex-wrap items-center gap-4 px-5 py-4">
          <PersonAvatar name={data.name} size="lg" />
          <div className="min-w-[260px] flex-1 space-y-1">
            <h1 className="flex flex-wrap items-center gap-2.5 text-xl font-semibold text-foreground">
              {data.name}
              {todayChip.length > 0 ? (
                todayChip.map((chip) => (
                  <TonePill key={chip.label} tone={chip.tone}>
                    {chip.label}
                  </TonePill>
                ))
              ) : (
                <StatusDot tone={STATUS_TONE[data.employment_status]}>
                  {EMPLOYMENT_STATUS_LABELS[data.employment_status]}
                </StatusDot>
              )}
            </h1>
            <p className="text-sm text-muted-foreground">
              {[data.job_title, data.department].filter(Boolean).join(" · ") ||
                "Stanowisko nieuzupełnione"}
              {data.manager_name ? (
                <>
                  {` · ${words ? words.coordinator : "koordynator"} `}
                  <Link
                    className="inline-flex items-center gap-1 align-middle text-foreground hover:underline"
                    href={`/people/${data.manager_user_id}`}
                  >
                    <PersonAvatar name={data.manager_name} size="xs" />
                    {data.manager_name}
                  </Link>
                </>
              ) : null}
            </p>
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
              <a className="text-primary hover:underline" href={`mailto:${data.email}`}>
                {data.email}
              </a>
              {data.phone ? <span className="text-foreground">{data.phone}</span> : null}
              <span className="text-muted-foreground">
                domyślnie: {LOCATION_LABELS[data.default_location].toLowerCase()}
              </span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {canEdit && full ? (
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="h-4 w-4" aria-hidden />
                Edytuj kartotekę
              </Button>
            ) : null}
            {canChangeForm && full ? (
              <Button variant="outline" onClick={() => setChangingForm(true)}>
                <Pencil className="h-4 w-4" aria-hidden />
                Zmień formę
              </Button>
            ) : null}
            {canStartExit || (lifeCase && lifeCase.status !== "cancelled") ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label="Więcej akcji">
                    <MoreHorizontal className="h-4 w-4" aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {lifeCase && lifeCase.status !== "cancelled" ? (
                    <DropdownMenuItem asChild>
                      <Link href={lifeCase.link}>
                        Otwórz sprawę {lifeCase.kind === "onboarding" ? "wejścia" : "odejścia"}
                      </Link>
                    </DropdownMenuItem>
                  ) : null}
                  {canStartExit ? (
                    <DropdownMenuItem asChild>
                      <Link href={`/people/${userId}/offboarding`}>Rozpocznij odejście</Link>
                    </DropdownMenuItem>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </header>
        {facts.length > 0 ? (
          <div
            className="grid border-t border-border/60 bg-muted/20"
            style={{ gridTemplateColumns: `repeat(${facts.length}, minmax(0, 1fr))` }}
          >
            {facts.map((fact) => (
              <HeaderFact key={fact.key} label={fact.label} value={fact.value} hint={fact.hint} />
            ))}
          </div>
        ) : null}
      </Card>

      <TabbedNav
        ariaLabel="Kartoteka"
        overflow="scroll"
        tabs={tabs}
        value={activeTab}
        onValueChange={(value) => chooseTab(value as ProfileTab)}
      />

      {activeTab === "overview" ? (
        <div className="space-y-4">
          {full ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <LeaveRingCard
                person={full}
                year={year}
                canEdit={canEdit}
                onEdit={() => setEditingPool(true)}
              />
              <Card className="flex flex-col gap-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-foreground">
                    {pay?.scope === "full"
                      ? `Stawka i ${payWords.bonuses}`
                      : capitalize(payWords.bonuses)}
                  </span>
                  {pay ? (
                    <Button size="sm" variant="ghost" onClick={() => chooseTab("payroll")}>
                      {pay.can_edit_rates ? "Nowa stawka od…" : "Szczegóły"}
                    </Button>
                  ) : null}
                </div>
                {!config.open_modules.payroll || payrollRefused ? (
                  <p className="text-sm text-muted-foreground">
                    {payrollRefused ? "Płace niedostępne dla Ciebie." : "Moduł płac jest wyłączony."}
                  </p>
                ) : payroll.isError ? (
                  <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    Nie udało się wczytać płac.
                    <Button size="sm" variant="ghost" onClick={() => payroll.refetch()}>
                      Spróbuj ponownie
                    </Button>
                  </div>
                ) : !pay ? (
                  <p className="text-sm text-muted-foreground">Wczytywanie płac…</p>
                ) : (
                  <>
                    {pay.scope === "full" ? (
                      <p className="text-sm text-foreground">
                        {rate ? (
                          <>
                            <strong>{formatMoney(rate.hourly_rate, rate.currency)}/h</strong>{" "}
                            <span className="text-muted-foreground">
                              od {formatIsoDatePl(rate.effective_from)}
                            </span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">Stawka nie ustawiona.</span>
                        )}
                      </p>
                    ) : null}
                    <ul className="space-y-1.5 border-t border-border/60 pt-2 text-[13px]">
                      {pay.bonuses
                        .filter((bonus) => bonus.status !== "cancelled")
                        .slice(0, 3)
                        .map((bonus) => (
                          <li key={bonus.id} className="flex items-center justify-between gap-2">
                            <span className="truncate">{bonus.category_label}</span>
                            <span className="flex shrink-0 items-center gap-1.5">
                              <strong>{formatMoney(bonus.amount, bonus.currency)}</strong>
                              <TonePill tone={bonus.status === "assigned" ? "success" : "info"}>
                                {bonus.status === "assigned" ? "przyznana" : "czeka"}
                              </TonePill>
                            </span>
                          </li>
                        ))}
                      {pay.bonuses.every((bonus) => bonus.status === "cancelled") ? (
                        <li className="text-muted-foreground">
                          Brak {payWords.bonuses_genitive}.
                        </li>
                      ) : null}
                    </ul>
                  </>
                )}
              </Card>
              <Card className="flex flex-col gap-2.5 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-foreground">Sprzęt</span>
                  {gear?.protocols[0] ? (
                    <span className="text-xs text-muted-foreground">{gear.protocols[0].number}</span>
                  ) : null}
                </div>
                {!equipmentVisible ? (
                  <p className="text-sm text-muted-foreground">Sprzęt widzi recepcja i Kadry.</p>
                ) : !gear ? (
                  <p className="text-sm text-muted-foreground">
                    {equipment.isError ? "Nie udało się wczytać sprzętu." : "Wczytywanie sprzętu…"}
                  </p>
                ) : gear.active.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Brak wydanego sprzętu.</p>
                ) : (
                  <ul className="space-y-2 text-[13px]">
                    {gear.active.slice(0, 4).map((row) => (
                      <li key={row.assignment_id} className="truncate">
                        {assignmentLabel(row)}
                      </li>
                    ))}
                    {gear.active.length > 4 ? (
                      <li>
                        <button
                          type="button"
                          className="text-primary hover:underline"
                          onClick={() => chooseTab("equipment")}
                        >
                          + {gear.active.length - 4} więcej
                        </button>
                      </li>
                    ) : null}
                  </ul>
                )}
              </Card>
            </div>
          ) : (
            <Card className="p-4">
              <p className="text-sm text-muted-foreground">
                Pełną kartotekę widzą ta osoba, jej przełożony, Kadry i Finanse.
              </p>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Card className="space-y-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-foreground">Ostatnio</span>
                {timeline.length > 4 ? (
                  <button
                    type="button"
                    className="text-[13px] text-primary hover:underline"
                    onClick={() => chooseTab("history")}
                  >
                    Cała historia →
                  </button>
                ) : null}
              </div>
              <Timeline entries={timeline.slice(0, 4)} />
            </Card>
            <div className="flex flex-col gap-2.5">
              {documentsVisible && !(documents.isError && refused(documents.error)) ? (
                <SectionLine
                  title="Dokumenty"
                  detail={
                    docs == null
                      ? documents.isError
                        ? "nie udało się wczytać"
                        : "wczytywanie…"
                      : docs.length === 0
                        ? "brak w NEXUSIE"
                        : `${docs.length} w e-teczce`
                  }
                  action={
                    <Button size="sm" variant="outline" onClick={() => chooseTab("documents")}>
                      {docs?.length === 0 && documents.data?.can_manage ? "Wgraj" : "Otwórz"}
                    </Button>
                  }
                />
              ) : null}
              {full && agreementsVisible && !(agreements.isError && refused(agreements.error)) ? (
                <SectionLine
                  title="Umowy"
                  detail={
                    agreementCount == null
                      ? agreements.isError
                        ? "niedostępne"
                        : "wczytywanie…"
                      : agreementCount === 0
                        ? "brak przygotowanych w NEXUSIE"
                        : `${agreementCount} w NEXUSIE`
                  }
                  action={
                    <Button size="sm" variant="outline" onClick={() => chooseTab("agreements")}>
                      {agreementCount === 0 && canEdit ? "Nowa umowa" : "Otwórz"}
                    </Button>
                  }
                />
              ) : null}
              {full ? (
                <SectionLine
                  title="Rola w NEXUSIE"
                  detail={`${
                    full.roles
                      .map((role) => ROLE_LABELS[role as keyof typeof ROLE_LABELS] ?? role)
                      .join(", ") || "—"
                  } · zmiana w Ustawieniach → Osoby i role`}
                />
              ) : null}
              {config.open_modules.lifecycle && life ? (
                <SectionLine
                  title="Wejście i odejście"
                  detail={
                    lifeCase ? (
                      <span className="inline-flex items-center gap-2">
                        {lifeLine}
                        <StatusDot tone={CASE_STATUS_TONE[lifeCase.status]}>
                          {CASE_STATUS_LABELS[lifeCase.status]}
                        </StatusDot>
                      </span>
                    ) : (
                      "bez sprawy"
                    )
                  }
                  action={
                    lifeCase && lifeCase.status !== "cancelled" ? (
                      <Button asChild size="sm" variant="outline">
                        <Link href={lifeCase.link}>Otwórz sprawę</Link>
                      </Button>
                    ) : undefined
                  }
                />
              ) : null}
              {lifecycle.isError && config.open_modules.lifecycle && !refused(lifecycle.error) ? (
                <SectionLine
                  title="Wejście i odejście"
                  detail="nie udało się wczytać"
                  action={
                    <Button size="sm" variant="ghost" onClick={() => lifecycle.refetch()}>
                      Spróbuj ponownie
                    </Button>
                  }
                />
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === "time" && full ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4">
            <CardTitle>Zatrudnienie</CardTitle>
            {/* Forma: osoba, przełożony, admin, Finanse; Kadry bez Płac — bez wiersza
                (19.10.2026). „Do uzupełnienia” nie zdradza formy, widzą go wszyscy. */}
            {full.employment_type_pending ? (
              <Fact label="Forma">
                <span className="text-warning-muted-foreground">do uzupełnienia</span>
              </Fact>
            ) : full.employment_type ? (
              <Fact label="Forma">{EMPLOYMENT_TYPE_LABELS[full.employment_type]}</Fact>
            ) : null}
            {full.manager_pending ? (
              <Fact label="Koordynator">
                <span className="text-warning-muted-foreground">do uzupełnienia</span>
              </Fact>
            ) : null}
            <Fact label="Start pracy">{formatIsoDatePl(full.work_start_date)}</Fact>
            <Fact label="Ostatni dzień pracy">
              {full.last_working_day ? formatIsoDatePl(full.last_working_day) : "—"}
            </Fact>
            <Fact label="Domyślnie pracuje">{LOCATION_LABELS[full.default_location]}</Fact>
            <Fact label={words?.timesheet ?? "Timesheet"}>
              {full.timesheet_required ? "tak" : "nie"}
            </Fact>
            <Fact label={capitalize(payWords.overtime)}>{full.can_log_overtime ? "tak" : "nie"}</Fact>
            {/* Daty Kadr (koniec zwolnienia, „składki od”, staż, ZUS) przełożony
                dostaje bez kluczy (przegląd 17.10.2026): brak pola w odpowiedzi
                = brak wiersza, `null` = „brak”. */}
            {full.employment_type === "zlecenie" ? (
              <Fact label="Uczeń lub student">
                {!full.student_contribution_exempt
                  ? "nie"
                  : !("contribution_exempt_until" in full)
                    ? "tak"
                    : full.contribution_exempt_until
                      ? `bez składek do ${formatIsoDatePl(full.contribution_exempt_until)}`
                      : "tak — brak daty końca zwolnienia"}
              </Fact>
            ) : null}
            {full.employment_type === "zlecenie" && full.contributions_from ? (
              <Fact label="Składki od">{formatIsoDatePl(full.contributions_from)}</Fact>
            ) : null}
            {full.employment_type === "uop" && "leave_seniority_years" in full ? (
              <Fact label="Staż do urlopu">
                {full.leave_seniority_years == null ? "—" : `${full.leave_seniority_years} lat`}
              </Fact>
            ) : null}
            {full.employment_type === "uop" && "zus_certificate_received_on" in full ? (
              <Fact label="Zaświadczenie z ZUS">
                {full.zus_certificate_received_on
                  ? formatIsoDatePl(full.zus_certificate_received_on)
                  : "—"}
              </Fact>
            ) : null}
          </Card>
          <PersonAbsencesHours
            person={full}
            year={year}
            // Zlecenie nie ma puli płatnych dni (D6) — bez „Zmień pulę”.
            canEditPool={canEdit && poolAllowed(full.employment_type)}
            onEditPool={() => setEditingPool(true)}
          />
        </div>
      ) : null}

      {activeTab === "payroll" ? (
        <div className="space-y-4">
          {config.open_modules.payroll ? (
            <PayrollProfileSection userId={userId} name={data.name} />
          ) : null}
          {full ? <BillingDetailsSection userId={userId} enabled={billingVisible} /> : null}
        </div>
      ) : null}

      {activeTab === "documents" ? (
        <PersonDocumentsSection userId={userId} name={data.name} enabled={documentsVisible} />
      ) : null}

      {activeTab === "agreements" && full ? (
        <PersonAgreementsSection userId={userId} enabled={agreementsVisible} />
      ) : null}

      {activeTab === "equipment" && equipmentVisible ? (
        <Card className="p-4">
          <PersonEquipmentPanel userId={userId} />
        </Card>
      ) : null}

      {activeTab === "history" ? (
        <Card className="space-y-3 p-4">
          <span className="font-semibold text-foreground">Historia</span>
          {timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">Brak zdarzeń do pokazania.</p>
          ) : (
            <Timeline entries={timeline} />
          )}
        </Card>
      ) : null}

      {canChangeForm && full && changingForm ? (
        <EmploymentTypeDialog person={full} open={changingForm} onOpenChange={setChangingForm} />
      ) : null}
      {canEdit && full && editing ? (
        <EditProfileDialog
          person={full}
          open={editing}
          onOpenChange={setEditing}
          managers={managers}
        />
      ) : null}
      {canEdit && full && editingPool ? (
        <EntitlementDialog
          userId={full.user_id}
          name={full.name}
          year={year}
          current={full.entitlements?.find((row) => row.year === year)}
          employmentType={full.employment_type ?? undefined}
          suggestedDays={full.suggested_entitlement_days ?? null}
          open={editingPool}
          onOpenChange={setEditingPool}
        />
      ) : null}
    </div>
  );
}

function Timeline({ entries }: { entries: ReturnType<typeof buildTimeline> }) {
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">Brak zdarzeń do pokazania.</p>;
  }
  return (
    <ol className="space-y-3">
      {entries.map((entry) => (
        <li key={entry.key} className="grid grid-cols-[88px_14px_minmax(0,1fr)] items-start gap-2.5">
          <span className="text-[13px] text-muted-foreground">{formatIsoDatePl(entry.date)}</span>
          <span aria-hidden className={cn("mt-1 h-2.5 w-2.5 rounded-full", TIMELINE_DOT[entry.tone])} />
          <span className="min-w-0">
            <span className="block font-medium text-foreground">{entry.title}</span>
            {entry.detail ? (
              <span className="block truncate text-[13px] text-muted-foreground">{entry.detail}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
