"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarOff, GraduationCap, Headset } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { apiErrorMessage } from "@/lib/api-error";
import {
  traineeKeys,
  useSaveTraineeCall,
  useSaveTraineeOutcome,
  useTraineeToday,
  type TraineeItem,
  type TraineeItemResponse,
  type TraineeListStatus,
  type TraineeOutcomeBody,
} from "@/lib/api/trainee";
import {
  emptyCallForm,
  handoverNoteFromFacts,
  handoverNoteFromForm,
  isClosed,
  nextOpenItemId,
  splitItems,
  toCallBody,
  validateCallForm,
  type CallFormValidation,
  type TraineeCallForm,
} from "@/lib/trainee-call";
import { useAuthStore } from "@/store/auth";

import { DayCompleteView } from "./DayCompleteView";
import { HandoverDialog } from "./HandoverDialog";
import { LaterDateDialog } from "./LaterDateDialog";
import {
  TraineeCallCard,
  type TraineeNoCallAction,
  type TraineeStatusMessage,
} from "./TraineeCallCard";
import { TraineeCallList, type TraineeListTab } from "./TraineeCallList";
import { TraineeProgress } from "./TraineeProgress";
import { TraineeScript } from "./TraineeScript";

const NOT_READY_COPY: Record<
  Exclude<TraineeListStatus, "ready">,
  { title: string; description: string; icon: typeof CalendarOff }
> = {
  not_workday: {
    icon: CalendarOff,
    title: "Dziś nie ma listy telefonów",
    description: "Listy powstają tylko w dni robocze. Wróć w najbliższy dzień roboczy.",
  },
  no_program: {
    icon: Headset,
    title: "Twój program jeszcze się nie zaczął",
    description:
      "Head of Recruitment ustawi datę startu — od tego dnia co rano zobaczysz tu listę osób do telefonu.",
  },
  program_finished: {
    icon: GraduationCap,
    title: "Program się zakończył",
    description:
      "Dziękujemy za rozmowy. Head of Recruitment zdecyduje o Twojej dalszej roli — nowy widok pojawi się po odświeżeniu aplikacji.",
  },
};

function clock(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

function outcomeMessage(response: TraineeItemResponse, body: TraineeOutcomeBody): string {
  const { item } = response;
  switch (body.outcome) {
    case "noanswer": {
      if (!isClosed(item)) {
        const retry = clock(item.retry_after);
        return `${item.name} — pierwsza próba bez odpowiedzi. Wraca na koniec listy${
          retry ? `, zadzwoń ponownie po ${retry}` : ""
        }.`;
      }
      return `${item.name} — druga próba bez odpowiedzi. Pozycja zamknięta.`;
    }
    case "later": {
      const day = body.later_date?.split("-").reverse().join(".");
      return `${item.name} — telefon przeniesiony${day ? ` na ${day}` : " na inny dzień"}. Pozycja zamknięta.`;
    }
    case "wrong":
      return `${item.name} — oznaczono zły numer. Pozycja zamknięta.`;
    case "declined":
      return `${item.name} — niezainteresowany. Praktykanci nie zadzwonią ponownie.`;
  }
}

export interface TraineeTodayViewProps {
  /** Harness: stan startowy formularza bieżącej osoby. */
  initialForm?: Partial<TraineeCallForm>;
  /** Harness: od razu otwarte okno „Przekaż rekruterowi”. */
  initialHandoverOpen?: boolean;
  /** Stały zegar (harness, testy). */
  now?: Date;
  /** Imię do skryptu rozmowy, gdy nie ma zalogowanej osoby (harness). */
  traineeName?: string;
}

/** „Telefony na dziś” — jedyny ekran praktykanta (0371). */
export function TraineeTodayView({
  initialForm,
  initialHandoverOpen = false,
  now,
  traineeName,
}: TraineeTodayViewProps) {
  const queryClient = useQueryClient();
  const today = useTraineeToday();
  const saveCall = useSaveTraineeCall();
  const saveOutcome = useSaveTraineeOutcome();
  const storeName = useAuthStore((s) => s.user?.name ?? null);
  const userName = traineeName ?? storeName;

  const [tab, setTab] = useState<TraineeListTab>("open");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<TraineeCallForm>(() => ({
    ...emptyCallForm(),
    ...initialForm,
  }));
  const [errors, setErrors] = useState<CallFormValidation["errors"]>({});
  const [status, setStatus] = useState<TraineeStatusMessage | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [handover, setHandover] = useState<{ itemId: number; name: string; note: string } | null>(
    null,
  );
  const [laterOpen, setLaterOpen] = useState(false);
  const [reviewingClosed, setReviewingClosed] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const handoverOpened = useRef(false);

  const items = useMemo(() => today.data?.items ?? [], [today.data]);
  const { open, closed } = useMemo(() => splitItems(items), [items]);
  const rows = tab === "open" ? open : closed;
  const selected: TraineeItem | null =
    rows.find((i) => i.id === selectedId) ?? rows[0] ?? null;

  // Harness: okno przekazania otwarte od startu (raz, gdy lista już jest).
  useEffect(() => {
    if (!initialHandoverOpen || handoverOpened.current || !selected) return;
    handoverOpened.current = true;
    setHandover({
      itemId: selected.id,
      name: selected.name,
      note: handoverNoteFromForm(form),
    });
  }, [initialHandoverOpen, selected, form]);

  const selectItem = (id: number) => {
    if (id !== selected?.id) {
      setForm(emptyCallForm());
      setErrors({});
      setActionError(null);
    }
    setSelectedId(id);
    // Na wąskim ekranie karta jest pod listą — przewiń do niej.
    if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 1023px)").matches) {
      window.requestAnimationFrame(() =>
        cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      );
    }
  };

  const afterSave = (item: TraineeItem, message: string, allowHandover: boolean) => {
    const next = nextOpenItemId(items, item.id, now);
    setSelectedId(next);
    setForm(emptyCallForm());
    setErrors({});
    setActionError(null);
    setStatus({
      text: message,
      ...(allowHandover ? { handoverItemId: item.id, handoverName: item.name } : {}),
    });
  };

  const onMutationError = (err: unknown) => {
    const code = (err as { response?: { status?: number } })?.response?.status;
    if (code === 409) {
      setActionError("Ta pozycja jest już zamknięta — odświeżam listę.");
      void queryClient.invalidateQueries({ queryKey: traineeKeys.today() });
      return;
    }
    setActionError(apiErrorMessage(err, "Nie udało się zapisać. Spróbuj ponownie."));
  };

  const onSave = () => {
    if (!selected) return;
    const validation = validateCallForm(form);
    setErrors(validation.errors);
    if (!validation.ok) return;
    setActionError(null);
    saveCall.mutate(
      { itemId: selected.id, body: toCallBody(form) },
      {
        onSuccess: (response) => {
          const employmentOnly = form.b2b === "employment_only";
          afterSave(
            response.item,
            employmentOnly
              ? `Zapisano: ${response.item.name} — tylko etat. Osoba wypada z list i wyszukiwarki.`
              : `Zapisano w profilu: ${response.item.name}. Rekruterzy widzą już te dane.`,
            !employmentOnly,
          );
        },
        onError: onMutationError,
      },
    );
  };

  const sendOutcome = (body: TraineeOutcomeBody) => {
    if (!selected) return;
    setActionError(null);
    saveOutcome.mutate(
      { itemId: selected.id, body },
      {
        onSuccess: (response) => {
          setLaterOpen(false);
          afterSave(response.item, outcomeMessage(response, body), false);
        },
        onError: onMutationError,
      },
    );
  };

  const onNoCall = (action: TraineeNoCallAction) => {
    if (action === "later") {
      setLaterOpen(true);
      return;
    }
    sendOutcome({ outcome: action });
  };

  const openHandover = (itemId: number) => {
    const item = items.find((i) => i.id === itemId);
    if (!item) return;
    // Bieżąca osoba z wypełnionym formularzem → notatka z rozmowy; zapisana
    // wcześniej → z faktów w profilu.
    const fromForm = item.id === selected?.id && !isClosed(item) && form.b2b != null;
    setHandover({
      itemId,
      name: item.name,
      note: fromForm ? handoverNoteFromForm(form) : handoverNoteFromFacts(item.facts),
    });
  };

  if (today.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać listy telefonów. Lista istnieje — spróbuj ponownie."
        onRetry={() => today.refetch()}
      />
    );
  }
  if (!today.isSuccess) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground" role="status">
        Wczytuję listę na dziś…
      </p>
    );
  }

  const data = today.data;
  if (data.status !== "ready") {
    const copy = NOT_READY_COPY[data.status] ?? NOT_READY_COPY.no_program;
    return (
      <EmptyState
        icon={copy.icon}
        title={copy.title}
        description={copy.description}
        className="rounded-xl border border-border bg-card"
      />
    );
  }

  if (data.day_completed && !reviewingClosed) {
    return (
      <DayCompleteView
        today={data}
        onBackToList={() => {
          setReviewingClosed(true);
          setTab("closed");
          setSelectedId(null);
          setStatus(null);
        }}
      />
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={Headset}
        title="Lista na dziś jest pusta"
        description="Nikt nie spełnia dziś reguł listy. Daj znać Head of Recruitment — sprawdzi reguły."
        className="rounded-xl border border-border bg-card"
      />
    );
  }

  const busy = saveCall.isPending || saveOutcome.isPending;
  const firstName = userName?.split(/\s+/)[0] ?? null;

  return (
    <div className="flex flex-col gap-4">
      <TraineeProgress today={data} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)] 2xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)_300px]">
        <TraineeCallList
          tab={tab}
          onTabChange={(next) => {
            setTab(next);
            setSelectedId(null);
            setForm(emptyCallForm());
            setErrors({});
            setActionError(null);
          }}
          open={open}
          closed={closed}
          selectedId={selected?.id ?? null}
          onSelect={selectItem}
        />
        <div ref={cardRef} className="min-w-0 scroll-mt-4">
          {selected ? (
            <TraineeCallCard
              key={selected.id}
              item={selected}
              form={form}
              onFormChange={setForm}
              errors={errors}
              status={status}
              actionError={actionError}
              busy={busy}
              onSave={onSave}
              onNoCall={onNoCall}
              onHandover={openHandover}
              now={now}
            />
          ) : (
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-5">
              {status ? (
                <p role="status" className="text-sm text-success-muted-foreground">
                  {status.text}
                </p>
              ) : null}
              <p className="text-sm text-muted-foreground">
                {tab === "open"
                  ? "Wszyscy z listy mają wynik."
                  : "Wybierz osobę z listy zamkniętych."}
              </p>
            </div>
          )}
        </div>
        <div className="lg:col-span-2 2xl:col-span-1">
          <TraineeScript firstName={firstName} />
        </div>
      </div>

      <HandoverDialog
        itemId={handover?.itemId ?? null}
        personName={handover?.name ?? ""}
        initialNote={handover?.note ?? ""}
        onClose={() => setHandover(null)}
        onDone={(message) => {
          setHandover(null);
          setStatus({ text: message });
        }}
      />
      {selected ? (
        <LaterDateDialog
          open={laterOpen}
          personName={selected.name}
          listDate={data.list_date}
          busy={saveOutcome.isPending}
          onCancel={() => setLaterOpen(false)}
          onConfirm={(date) => sendOutcome({ outcome: "later", later_date: date })}
        />
      ) : null}
    </div>
  );
}
