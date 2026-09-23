"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarPlus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";
import WeekCalendar from "@/components/calendar/WeekCalendar";
import { useInterviewCycle } from "@/lib/api/interviewCycle";
import {
  candidateLabel,
  interviewStartFor,
  parseCycleParam,
  parseScope,
  parseView,
  type CycleAction,
  type CycleOverview,
  type CycleScope,
  type CycleView,
  type PairInfo,
  type SlotRequest,
} from "@/lib/interview-cycle";
import { resolveViewState } from "@/lib/view-state";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

import { AgendaView } from "./AgendaView";
import { CycleBoard } from "./CycleBoard";
import { DebriefModal } from "./DebriefModal";
import { SlotDecisionDialog, SlotRequestDialog } from "./SlotDialogs";

const VIEWS: { value: CycleView; label: string }[] = [
  { value: "agenda", label: "Agenda" },
  { value: "week", label: "Tydzień" },
  { value: "board", label: "Tablica" },
];

type Dialog =
  | { kind: "debrief"; pair: PairInfo; eventId: number }
  | { kind: "pick" | "confirm"; pair: PairInfo; request: SlotRequest }
  | { kind: "prep"; pair: PairInfo; second: boolean }
  | { kind: "slots"; pair: PairInfo | null }
  | null;

/**
 * Ekran `/calendar` — „Rozmowy u klienta”.
 *
 * Trzy widoki tych samych danych: Agenda (domyślna, „co mam teraz zrobić”),
 * Tydzień (dawna siatka z Outlookiem) i Tablica (7 kroków, „gdzie utknął
 * który kandydat”). Widok i zakres żyją w adresie (`?view=&scope=`), a link
 * z dzwonka (`?cycle=cand-job`) otwiera kartę konkretnego kandydata.
 */
export function CalendarCycleScreen({
  // Harness `/preview/calendar-cycle` podaje stały zegar i dane bez sieci.
  nowOverride,
  dataOverride,
  roleOverride,
  basePath = "/calendar",
}: {
  nowOverride?: Date;
  dataOverride?: Partial<Record<CycleScope, CycleOverview>>;
  /** Harness: ekran oczami rekrutera albo DL bez logowania. */
  roleOverride?: "recruiter" | "delivery_lead";
  /** Harness zostaje na swojej ścieżce przy zmianie zakładki. */
  basePath?: string;
} = {}) {
  const router = useRouter();
  const params = useSearchParams();
  const storeUser = useAuthStore((s) => s.user);
  const user = roleOverride ? { role: roleOverride, roles: [roleOverride] } : storeUser;
  // Lustro `_SLOT_OWNER_ROLES` (interview_cycle.py) + sufit sekcji Pipeline
  // (router stoi za PIPELINE_SECTION_DEPENDENCIES; zapis terminów, U8).
  const canManageSlots =
    hasRole(user, "admin", "head_of_recruitment", "delivery_lead", "tac") &&
    hasSectionAccess(user, "pipeline", "write");
  const isOversight = hasRole(user, "admin", "head_of_recruitment");
  // Delivery patrzy domyślnie na swoje rekrutacje, rekruter na swoich kandydatów.
  const defaultScope: CycleScope = hasRole(user, "delivery_lead", "tac") ? "jobs" : "mine";

  const view = parseView(params.get("view"), params.get("event") != null);
  const scope = parseScope(params.get("scope"), defaultScope);
  const cycleParam = params.get("cycle");
  // Dzwonek „Zadzwoń do kandydata po rozmowie” niesie `?debrief=<id wydarzenia>`.
  const debriefParam = Number(params.get("debrief")) || null;

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [tick, setTick] = useState(() => Date.now());

  // Link z dzwonka: efekt na WARTOŚCI parametru (miękka nawigacja nie
  // odmontowuje strony, więc sam inicjalizator stanu by go przegapił).
  useEffect(() => {
    const parsed = parseCycleParam(cycleParam);
    if (parsed) setSelectedKey(`${parsed.candidateId}-${parsed.jobId}`);
  }, [cycleParam]);

  // Odliczanie „zostało N min” — przeliczane co 30 s bez nowego zapytania.
  useEffect(() => {
    if (nowOverride) return;
    const id = window.setInterval(() => setTick(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [nowOverride]);
  const now = useMemo(() => nowOverride ?? new Date(tick), [nowOverride, tick]);

  const query = useInterviewCycle(scope, { enabled: !dataOverride && view !== "week" });
  const data = dataOverride?.[scope] ?? query.data;

  // Otwórz debrief z linku, gdy lista już wie, kogo dotyczy rozmowa.
  const openedDebrief = useRef<number | null>(null);
  useEffect(() => {
    if (!debriefParam || !data || openedDebrief.current === debriefParam) return;
    const item = data.items.find((i) => i.interview_event_id === debriefParam);
    if (!item) return;
    openedDebrief.current = debriefParam;
    setDialog({ kind: "debrief", pair: item, eventId: debriefParam });
  }, [debriefParam, data]);

  const setParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v == null) next.delete(k);
      else next.set(k, v);
    }
    // Zmiana widoku zdejmuje link do wydarzenia — inaczej `?event=` trzymałby Tydzień.
    if ("view" in patch) {
      next.delete("event");
      next.delete("action");
    }
    const qs = next.toString();
    router.replace(qs ? `${basePath}?${qs}` : basePath);
  };

  const onAction = (action: CycleAction) => {
    switch (action.type) {
      case "debrief":
        setDialog({ kind: "debrief", pair: action.pair, eventId: action.eventId });
        break;
      case "pick":
      case "confirm":
        setDialog({ kind: action.type, pair: action.pair, request: action.request });
        break;
      case "plan_prep":
        setDialog({ kind: "prep", pair: action.pair, second: action.second });
        break;
      case "add_slots":
        setDialog({ kind: "slots", pair: action.pair });
        break;
      case "open_event":
        router.push(`${basePath}?view=week&event=${action.eventId}`);
        break;
    }
  };

  const state = dataOverride?.[scope]
    ? "ready"
    : resolveViewState({ isLoading: query.isPending, isError: query.isError, error: query.error });
  const todoCount = data?.todos.length ?? 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Rozmowy u klienta</h1>
          <p className="text-sm text-muted-foreground">
            Terminy od klienta, prepy, rozmowy i telefon do kandydata po rozmowie
            {todoCount > 0 ? ` · do zrobienia: ${todoCount}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2" data-help="calendar.views">
          <Segmented
            label="Widok"
            value={view}
            options={VIEWS}
            onChange={(v) => setParams({ view: v === "agenda" ? null : v })}
          />
          {view !== "week" ? (
            <Segmented
              label="Zakres"
              value={scope}
              options={[
                { value: "mine", label: "Moi kandydaci" },
                { value: "jobs", label: "Moje rekrutacje" },
                ...(isOversight ? [{ value: "all" as CycleScope, label: "Cały zespół" }] : []),
              ]}
              onChange={(v) => setParams({ scope: v === defaultScope ? null : v })}
            />
          ) : null}
          {canManageSlots && view !== "week" ? (
            <button
              type="button"
              onClick={() => setDialog({ kind: "slots", pair: null })}
              data-help="calendar.slots"
              className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
            >
              <CalendarPlus className="h-4 w-4" aria-hidden />
              Terminy od klienta
            </button>
          ) : null}
        </div>
      </header>

      {view === "week" ? (
        <WeekCalendar />
      ) : state === "loading" ? (
        <div className="rounded-2xl border border-border bg-card p-8 text-sm text-muted-foreground">
          Ładowanie rozmów u klienta…
        </div>
      ) : state !== "ready" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description="Lista rozmów nie wczytała się — to nie znaczy, że nic nie czeka."
          onRetry={() => query.refetch()}
        />
      ) : view === "board" ? (
        <CycleBoard
          items={data.items}
          canManageSlots={canManageSlots}
          onAction={onAction}
          onSelect={(key) => {
            setSelectedKey(key);
            setParams({ view: null, cycle: key });
          }}
        />
      ) : (
        <AgendaView
          data={data}
          now={now}
          canManageSlots={canManageSlots}
          onAction={onAction}
          selectedKey={selectedKey}
          onSelect={setSelectedKey}
        />
      )}
      {data?.truncated ? (
        <p className="text-xs text-muted-foreground">
          Pokazujemy pierwsze 300 kandydatów w cyklu — zawęź zakres do swoich kandydatów.
        </p>
      ) : null}

      <DebriefModal
        open={dialog?.kind === "debrief"}
        onOpenChange={(o) => {
          if (o) return;
          setDialog(null);
          // F5 nie może otwierać okna z powrotem.
          if (debriefParam) setParams({ debrief: null });
        }}
        eventId={dialog?.kind === "debrief" ? dialog.eventId : null}
        pair={dialog?.kind === "debrief" ? dialog.pair : null}
        interviewStart={
          dialog?.kind === "debrief" ? interviewStartFor(data, dialog.eventId) : undefined
        }
      />
      <SlotRequestDialog
        open={dialog?.kind === "slots"}
        onOpenChange={(o) => !o && setDialog(null)}
        pair={dialog?.kind === "slots" ? dialog.pair : null}
      />
      <SlotDecisionDialog
        open={dialog?.kind === "pick" || dialog?.kind === "confirm"}
        onOpenChange={(o) => !o && setDialog(null)}
        mode={dialog?.kind === "confirm" ? "confirm" : "pick"}
        pair={dialog?.kind === "pick" || dialog?.kind === "confirm" ? dialog.pair : null}
        request={dialog?.kind === "pick" || dialog?.kind === "confirm" ? dialog.request : null}
      />
      {dialog?.kind === "prep" ? (
        <ScheduleInterviewModal
          open
          onOpenChange={(o) => !o && setDialog(null)}
          candidateId={dialog.pair.candidate_id}
          candidateName={candidateLabel(dialog.pair)}
          candidateEmail={dialog.pair.candidate_email}
          defaultJobId={dialog.pair.job_id}
          defaultEventType="prep_call"
          defaultTitle={`${dialog.second ? "Prep 2" : "Prep"}: ${candidateLabel(dialog.pair)}${
            dialog.pair.client_name ? ` — ${dialog.pair.client_name}` : ""
          }`}
        />
      ) : null}
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-lg bg-muted p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-8 rounded-md px-3 text-sm",
            o.value === value
              ? "bg-card font-semibold text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

