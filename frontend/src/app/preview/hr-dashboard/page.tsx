"use client";

/**
 * Harness „Pulpit i nieobecni” (makieta 1 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwe kafelki pulpitu „Ludzi” w prawdziwej ramce (`TileFrame` →
 * `TileContent` → `HrTileGate`) i prawdziwy przycisk „Nieobecni dziś”
 * z górnego paska (`AbsentTodayButton`, klik otwiera okienko) — na zasianym
 * cache, ZERO zapytań (`hr-harness.tsx`). Okienko stoi też otwarte obok
 * (`AbsentTodayPanel`), żeby było je widać bez klikania.
 *
 * Persony (`?as=`):
 * - `recruiter` (domyślnie) — Ola w trakcie zastępowania Kamila: „W zastępstwie”
 *   (3 rekrutacje, 2 rozmowy u klienta, 4 osoby w procesie) i „Mój czas”;
 * - `manager` — Marta, przełożona: „Do akceptacji”, ostrzeżenie „zastępca też
 *   nieobecny” w „W zastępstwie”, „Mój czas”;
 * - `reception` — Zofia z uprawnieniem Sprzęt: „Sprzęt do zrobienia” i „Mój czas”;
 * - `care` — Kamil, Delivery Lead: kafelki opieki „Moja opieka” (dwie karty po
 *   terminie, dwie do piątku) i „Zagrożeni konsultanci” (dwie osoby z „Ryzyko”).
 * U rekruterki pod pulpitem „Plakietka i wzmianka”: kropka nieobecności przy
 * Rekruterze/DL w liście rekrutacji i podpowiedź zastępcy po „@Kamil” w notatce
 * (`absence-mentions.tsx`).
 * Rodzaju nieobecności nie ma ani w kafelkach, ani w okienku (D6).
 */

import type { ReactNode } from "react";
import { Search } from "lucide-react";

import { AbsentTodayButton, AbsentTodayPanel } from "@/components/hr/leave/AbsentTodayButton";
import { currentYearMonth } from "@/components/hr/time/time-format";
import { TileFrame, type TileActions } from "@/components/v2/dashboard/custom/TileFrame";
import { careKeys } from "@/lib/api/care";
import { careBoardKeys, type CareBoard } from "@/lib/api/care-board";
import { equipmentKeys, type EquipmentTask } from "@/lib/api/equipment";
import {
  SUBSTITUTION_QUERY_KEY,
  type SubstitutionSummary,
} from "@/lib/api/hr-dashboard";
import { leaveKeys, type AbsentTodayRow } from "@/lib/api/hr-leave";
import { timeKeys } from "@/lib/api/hr-time";
import type { DashboardTile, TileType } from "@/lib/api/userDashboard";
import { ROW_HEIGHT } from "@/lib/dashboard-tiles/layout";
import { cn } from "@/lib/utils";
import { hrKeys } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import {
  HR_CAST,
  HR_CLIENTS,
  hrConfig,
  shiftDay,
  type HarnessPerson,
} from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import { careConsultants } from "../hr-care/rhythm-fixtures";
import { balance, olaRequests, personMonth } from "../hr-my-time/fixtures";
import { AbsenceMentions, seedAbsenceMentions } from "./absence-mentions";

const AS = ["recruiter", "manager", "reception", "care"] as const;
type As = (typeof AS)[number];

const STATES = [
  { key: "recruiter", label: "Rekruterka w zastępstwie" },
  { key: "manager", label: "Przełożona" },
  { key: "reception", label: "Recepcja" },
  { key: "care", label: "Opieka (Delivery Lead)" },
] as const;

const { ola, kamil, ewa, adam, marta, zofia, kacper } = HR_CAST;
const { bank, telecom, clinic, insurance } = HR_CLIENTS;

const NO_ACTIONS: TileActions = { onSettings: () => {}, onDuplicate: () => {}, onRemove: () => {} };

function tile(id: string, type: TileType, w: number, h: number): DashboardTile {
  return { id, type, x: 0, y: 0, w, h, config: {} };
}

const LAYOUT: Record<As, DashboardTile[]> = {
  recruiter: [tile("sub", "hr_substitution", 6, 4), tile("time", "hr_my_time", 6, 3)],
  manager: [
    tile("appr", "hr_approvals", 4, 3),
    tile("sub", "hr_substitution", 4, 3),
    tile("time", "hr_my_time", 4, 3),
  ],
  reception: [tile("eq", "equipment_tasks", 6, 4), tile("time", "hr_my_time", 6, 3)],
  care: [tile("care", "care_mine", 6, 4), tile("risk", "care_at_risk", 6, 4)],
};

const VIEWER: Record<As, HarnessPerson & Pick<HarnessUser, "grants">> = {
  recruiter: ola,
  manager: marta,
  reception: { ...zofia, grants: ["equipment"] },
  care: kamil,
};

/** Tablica opieki Kamila: dwie karty po terminie, dwie do piątku (fikcja). */
function careBoard(today: string): CareBoard {
  const card = (
    key: string,
    kind: CareBoard["cards"][number]["kind"],
    title: string,
    client: { id: number; name: string },
    due: string,
    overdue: number,
    level: "ok" | "watch" | "risk" | null,
    contractId: number | null,
  ): CareBoard["cards"][number] => ({
    key,
    kind,
    column: "new",
    title,
    subtitle: null,
    reason_label: null,
    due_on: due,
    overdue_days: overdue,
    scheduled_at: null,
    retry_on: null,
    note_excerpt: null,
    contract_id: contractId,
    client_id: client.id,
    client_name: client.name,
    owner_user_id: kamil.id,
    owner_name: kamil.name,
    health: level
      ? { level, label: { ok: "Dobrze", watch: "Uwaga", risk: "Ryzyko" }[level], reasons: [] }
      : null,
  });
  return {
    today,
    week_end: shiftDay(today, 4),
    cards: [
      card("contact:plan:1", "contact", "Rozmowa: Paweł Makietowy", bank, shiftDay(today, -6), 6, "risk", 4504),
      card("feedback:8802", "feedback", "Opinia: Piotr Menedżerski", bank, shiftDay(today, -2), 2, null, null),
      card("contact:plan:2", "contact", "Rozmowa: Karolina Przykładowa", telecom, shiftDay(today, 2), 0, "watch", 4502),
      card("demand:7001:301:77", "demand", "Popyt do sprawdzenia: Java", bank, shiftDay(today, 3), 0, null, null),
    ],
    done: { this_week: 3, recent: [] },
  };
}

function absentToday(today: string, viewer: HarnessPerson): { date: string; items: AbsentTodayRow[]; total: number } {
  const row = (
    person: HarnessPerson,
    until: string,
    substitute: HarnessPerson | null,
    substituteAbsent = false,
  ): AbsentTodayRow => ({
    user_id: person.id,
    name: person.name,
    until,
    half_day: null,
    substitute_user_id: substitute?.id ?? null,
    substitute_name: substitute?.name ?? null,
    substitute_absent: substituteAbsent,
    i_substitute: substitute?.id === viewer.id,
    is_me: person.id === viewer.id,
  });
  const items = [
    row(kamil, shiftDay(today, 1), ola),
    row(ewa, today, marta),
    // Zastępca Adama (Kamil) też jest dziś nieobecny — silnik zastępstw to zgłasza.
    row(adam, today, kamil, true),
  ];
  return { date: today, items, total: items.length };
}

function substitution(as: As, today: string): SubstitutionSummary {
  if (as === "recruiter") {
    return {
      enabled: true,
      fresh: true,
      items: [
        {
          owner_user_id: kamil.id,
          owner_name: kamil.name,
          start_date: shiftDay(today, -3),
          end_date: shiftDay(today, 1),
          recruitments: {
            count: 3,
            items: [
              { job_id: 801, title: "Java Developer", client_name: bank.name },
              { job_id: 802, title: "QA Engineer", client_name: telecom.name },
              { job_id: 803, title: "DevOps Engineer", client_name: clinic.name },
            ],
          },
          client_meetings: {
            count: 2,
            items: [
              { event_id: 901, starts_at: `${shiftDay(today, 1)}T08:00:00Z`, client_name: bank.name },
              { event_id: 902, starts_at: `${shiftDay(today, 1)}T12:00:00Z`, client_name: telecom.name },
            ],
          },
          pipeline_cards: 4,
        },
      ],
      warnings: [],
    };
  }
  if (as === "manager") {
    return {
      enabled: true,
      fresh: true,
      items: [],
      warnings: [
        {
          owner_user_id: adam.id,
          owner_name: adam.name,
          substitute_user_id: kamil.id,
          substitute_name: kamil.name,
          you_are_substitute: false,
        },
      ],
    };
  }
  return { enabled: true, fresh: true, items: [], warnings: [] };
}

function equipmentTasks(today: string): EquipmentTask[] {
  const task = (
    id: number,
    kind: EquipmentTask["kind"],
    title: string,
    due: string | null,
    overdue: number,
    holder: string | null,
  ): EquipmentTask => ({
    id,
    kind,
    status: "otwarte",
    title,
    due_on: due,
    overdue_days: overdue,
    holder: { kind: holder ? "user" : null, id: null, name: holder },
    protocol: null,
    details: {},
  });
  return [
    task(1, "zwrot", "Zwrot karty SIM po zakończeniu współpracy", shiftDay(today, -6), 6, "Paweł Makietowy"),
    task(2, "wydanie", "Wydaj zestaw biura — wejście pracownika", shiftDay(today, 5), 0, kacper.name),
    task(3, "wydanie", `Zestaw kontraktora — start u klienta ${insurance.name}`, shiftDay(today, 4), 0, "Anna Kontraktorska"),
    task(4, "podpis", "Protokół PZO/TEST/2026/014 czeka na podpis", shiftDay(today, 1), 0, "Anna Kontraktorska"),
    task(5, "zwrot", "Zwrot sprzętu — odejście", shiftDay(today, 14), 0, HR_CAST.tomasz.name),
  ];
}

function prepare(params: URLSearchParams) {
  const as = pickState(params.get("as"), AS, "recruiter");
  const viewer = VIEWER[as];
  const today = warsawToday();
  const current = currentYearMonth();
  const client = harnessQueryClient();
  client.setQueryData(
    hrKeys.config,
    hrConfig({
      is_manager: as === "manager",
      direct_reports: as === "manager" ? 9 : 0,
      equipment: as === "reception",
    }),
  );
  client.setQueryData(hrKeys.counts, { approvals: as === "manager" ? 4 : null, cases: null });
  client.setQueryData(leaveKeys.absentToday, absentToday(today, viewer));
  client.setQueryData(SUBSTITUTION_QUERY_KEY, substitution(as, today));
  client.setQueryData(leaveKeys.balance(current.year), balance(current.year, "11.5", "16.5"));
  client.setQueryData(leaveKeys.mine, olaRequests(current));
  client.setQueryData(timeKeys.month(current.year, current.month), personMonth(viewer, current, today, "draft"));
  client.setQueryData(equipmentKeys.tasks("otwarte"), equipmentTasks(today));
  client.setQueryData(careBoardKeys.board("mine"), careBoard(today));
  const consultants = careConsultants(today);
  client.setQueryData(careKeys.consultants, {
    ...consultants,
    // Zdrowie „Ryzyko” u dwóch osób — kafelek „Zagrożeni konsultanci”.
    items: consultants.items.map((row, index) =>
      index < 2
        ? {
            ...row,
            health: {
              level: "risk" as const,
              label: "Ryzyko",
              reasons: [index === 0 ? "chce zmiany projektu" : "zamówienie kończy się za 32 dni"],
            },
          }
        : { ...row, health: { level: "ok" as const, label: "Dobrze", reasons: [] } },
    ),
  });
  seedAbsenceMentions(client, today);
  return { user: viewer, client, value: { as, viewer, today } };
}

const SPAN: Record<number, string> = {
  4: "lg:col-span-4",
  6: "lg:col-span-6",
  8: "lg:col-span-8",
};

function Frame({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0", className)}>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

export default function HrDashboardPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { as, viewer, today } = ready.value;
  const absent = ready.client.getQueryData<{ date: string; items: AbsentTodayRow[] }>(leaveKeys.absentToday);
  return (
    <HrHarnessShell
      client={ready.client}
      title="Pulpit i nieobecni"
      note={`${viewer.name} (${viewer.jobTitle}). Dane fikcyjne, bez zapytań. Rodzaj nieobecności widzą tylko osoba, przełożony i Kadry.`}
      states={STATES}
      current={as}
      param="as"
    >
      <div className="space-y-5">
        <Frame title="Górny pasek — „Nieobecni dziś”">
          <div
            data-testid="topbar-replica"
            className="flex h-12 items-center gap-2 rounded-lg border border-border bg-card px-3"
          >
            <div className="flex min-w-0 flex-1 items-center gap-2 text-sm text-muted-foreground">
              <Search className="h-4 w-4 shrink-0" aria-hidden />
              <span className="truncate">Szukaj kandydatów, rekrutacji, klientów…</span>
            </div>
            <AbsentTodayButton />
          </div>
        </Frame>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Frame title={`Pulpit — ${viewer.name}`}>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              {LAYOUT[as].map((item) => (
                <div
                  key={item.id}
                  className={SPAN[item.w]}
                  style={{ minHeight: Math.max(item.h, 3) * ROW_HEIGHT }}
                >
                  <TileFrame tile={item} editing={false} actions={NO_ACTIONS} />
                </div>
              ))}
            </div>
          </Frame>
          {absent ? (
            <Frame title="Okienko „Nieobecni dziś” (otwarte)">
              <div
                role="dialog"
                aria-label="Nieobecni dziś — okienko"
                className="rounded-lg border border-border bg-card p-3 shadow-md"
              >
                <AbsentTodayPanel date={today} items={absent.items} onNavigate={() => {}} />
              </div>
            </Frame>
          ) : null}
        </div>

        {as === "recruiter" ? (
          <Frame title="Plakietka i wzmianka — lista rekrutacji i pole notatki">
            <AbsenceMentions today={today} />
          </Frame>
        ) : null}
      </div>
    </HrHarnessShell>
  );
}
