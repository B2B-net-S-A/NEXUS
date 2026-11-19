"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CalendarPlus, Pencil, Plus, Send, Trash2, X } from "lucide-react";

import { AppModal, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CATEGORY_LABELS,
  MEETING_KIND_LABELS,
  MEETING_STATUS_LABELS,
  useBoardDocuments,
  useBoardMeeting,
  useBoardMeetings,
  useDeleteBoardMeeting,
  useFreezeMeetingPack,
  useSaveBoardMeeting,
  type AgendaItem,
  type BoardDocument,
  type BoardMeeting,
  type BoardObligation,
  type MeetingKind,
  type MeetingPack,
  type MeetingStatus,
  type ObligationStatus,
} from "@/lib/api/supervisory-board";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

// ── Czyste wyliczenia (testy) ────────────────────────────────────────────────

export interface PackFigures {
  salesYtd: number | null;
  salesYtdPrevious: number | null;
  salesMonths: number;
  result: number | null;
  resultPct: number | null;
  resultMonths: number;
  planSales: number | null;
  /** Wykonanie sprzedaży w miesiącach z planem (tylko miesiące wykonane). */
  actualVsPlan: { actual: number; plan: number } | null;
}

/** Liczby z zamrożonego pakietu (pulpit i budżet w mln zł). */
export function packFigures(pack: MeetingPack): PackFigures {
  const ytd = pack.summary.ytd;
  const months = pack.budget.months;
  const planned = months.filter((m) => m.plan_sales !== null);
  const done = planned.filter((m) => m.kind === "actual" && m.sales !== null);
  return {
    salesYtd: ytd.sales ?? null,
    salesYtdPrevious: ytd.sales_previous ?? null,
    salesMonths: ytd.sales_months,
    result: ytd.result ?? null,
    resultPct: ytd.result_pct ?? null,
    resultMonths: ytd.result_months,
    planSales: planned.length ? planned.reduce((a, m) => a + (m.plan_sales as number), 0) : null,
    actualVsPlan: done.length
      ? {
          actual: done.reduce((a, m) => a + (m.sales as number), 0),
          plan: done.reduce((a, m) => a + (m.plan_sales as number), 0),
        }
      : null,
  };
}

/** Najbliższe zaplanowane, a gdy go nie ma — ostatnie (lista idzie od najnowszego). */
export function defaultMeetingId(items: BoardMeeting[], today: string): number | null {
  const upcoming = items
    .filter((m) => m.status === "planned" && m.held_on >= today)
    .sort((a, b) => a.held_on.localeCompare(b.held_on));
  return upcoming[0]?.id ?? items[0]?.id ?? null;
}

const OBLIGATION_BADGE: Record<ObligationStatus, { label: string; variant: "success" | "warning" | "danger" | "neutral" }> = {
  done: { label: "zrobione", variant: "success" },
  soon: { label: "wkrótce", variant: "warning" },
  overdue: { label: "po terminie", variant: "danger" },
  pending: { label: "w terminie", variant: "neutral" },
};

const STATUS_BADGE: Record<MeetingStatus, "info" | "success" | "neutral"> = {
  planned: "info",
  held: "success",
  cancelled: "neutral",
};

function plDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function mlnText(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} mln`;
}

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// ── Widok ────────────────────────────────────────────────────────────────────

export function MeetingsTab() {
  const router = useRouter();
  const params = useSearchParams();
  const isAdmin = hasRole(useAuthStore((s) => s.user), "admin");
  const meetings = useBoardMeetings();
  const [editing, setEditing] = React.useState<BoardMeeting | "new" | null>(null);
  const state = resolveViewState({
    isLoading: meetings.isLoading,
    isError: meetings.isError,
    error: meetings.error,
    isSuccess: meetings.isSuccess,
  });
  const requested = Number(params.get("posiedzenie")) || null;
  const items = meetings.data?.items ?? [];
  const selectedId = items.some((m) => m.id === requested) ? requested : defaultMeetingId(items, todayIso());
  const select = (id: number) => router.replace(`/rada?tab=posiedzenia&posiedzenie=${id}`);

  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => meetings.refetch()} />;
  }
  if (!meetings.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }

  return (
    <div className="space-y-3">
      <Obligations items={meetings.data.obligations} />
      <div className="grid gap-3 lg:grid-cols-[320px_1fr]">
        <section className="min-w-0 rounded-lg border border-border bg-card p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">Posiedzenia</h2>
            {isAdmin ? (
              <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
                <CalendarPlus className="mr-1 h-3.5 w-3.5" />
                Nowe
              </Button>
            ) : null}
          </div>
          {items.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-muted-foreground">
              Nie ma jeszcze posiedzeń.{isAdmin ? " Dodaj najbliższe — porządek obrad i pakiet przygotujesz przy nim." : ""}
            </p>
          ) : (
            <ul className="space-y-1">
              {items.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => select(m.id)}
                    className={cn(
                      "w-full rounded-md px-2.5 py-2 text-left text-[12px] transition-colors",
                      m.id === selectedId ? "bg-primary/10" : "hover:bg-muted",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold tabular-nums text-foreground">{plDate(m.held_on)}</span>
                      <Badge variant={STATUS_BADGE[m.status]} size="sm">
                        {MEETING_STATUS_LABELS[m.status]}
                      </Badge>
                    </div>
                    <div className="mt-0.5 truncate text-foreground">{m.title}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {MEETING_KIND_LABELS[m.kind]}
                      {m.has_pack ? ` · pakiet z ${plDate(m.pack_frozen_at)}` : " · bez pakietu"}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        {selectedId !== null ? (
          <MeetingDetail id={selectedId} isAdmin={isAdmin} onEdit={(m) => setEditing(m)} />
        ) : (
          <section className="rounded-lg border border-dashed border-border p-6 text-center text-[12px] text-muted-foreground">
            Wybierz posiedzenie z listy.
          </section>
        )}
      </div>
      {editing ? (
        <MeetingDialog
          meeting={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(id) => select(id)}
        />
      ) : null}
    </div>
  );
}

function Obligations({ items }: { items: BoardObligation[] }) {
  const year = new Date().getFullYear();
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold text-foreground">Obowiązki korporacyjne {year}</h2>
      <ul className="divide-y divide-border">
        {items.map((o) => (
          <li key={o.key} className="grid grid-cols-[92px_1fr_auto] items-center gap-3 py-1.5 text-[12px]">
            <Badge variant={OBLIGATION_BADGE[o.status].variant} size="sm" className="justify-self-start">
              {OBLIGATION_BADGE[o.status].label}
            </Badge>
            <div className="min-w-0">
              <span className="font-medium text-foreground">{o.label}</span>
              <span className="text-muted-foreground"> · {o.evidence}</span>
            </div>
            <div className="whitespace-nowrap text-right text-muted-foreground">
              <span className="tabular-nums">do {plDate(o.due)}</span>
              <span className="ml-2 text-[11px]">{o.legal}</span>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
        Stan liczony z odpisu KRS, sprawozdań w Analizie, uchwał w Dokumentach i rejestru posiedzeń. Ocena Rady i uchwała WZA
        rozpoznawane po tytule (np. „ocena sprawozdania”, „zatwierdzenie”) — nazwij tak dokument, żeby się zaliczył.
      </p>
    </section>
  );
}

function MeetingDetail({ id, isAdmin, onEdit }: { id: number; isAdmin: boolean; onEdit: (m: BoardMeeting) => void }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const detail = useBoardMeeting(id);
  const documents = useBoardDocuments(null);
  const freeze = useFreezeMeetingPack();
  const remove = useDeleteBoardMeeting();
  const router = useRouter();
  if (detail.isError) {
    return <QueryStateNotice state="error" onRetry={() => detail.refetch()} />;
  }
  const m = detail.data;
  if (!m) return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  const docs = new Map<number, BoardDocument>((documents.data?.items ?? []).map((d) => [d.id, d]));
  const minutes = m.minutes_document_id ? docs.get(m.minutes_document_id) : undefined;

  const onFreeze = async () => {
    const ok = await askConfirm({
      title: m.has_pack ? "Zamrozić pakiet ponownie?" : "Zamrozić pakiet i wysłać Radzie?",
      description:
        "Pakiet zapisze dzisiejsze liczby z pulpitu, budżetu i analizy oraz dokumenty i wpisy KRS od poprzedniego posiedzenia. Rada dostanie dzwonek." +
        (m.has_pack ? " Poprzedni pakiet zostanie zastąpiony." : ""),
      confirmLabel: "Zamroź i wyślij",
    });
    if (!ok) return;
    freeze.mutate(m.id, {
      onSuccess: (r) => {
        showToast(`Pakiet gotowy — powiadomiono ${r.notified} os.`);
        void detail.refetch();
      },
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się przygotować pakietu."), "error"),
    });
  };

  const onDelete = async () => {
    const ok = await askConfirm({
      title: "Usunąć posiedzenie?",
      description: `„${m.title}” zniknie z rejestru.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(m.id, {
      onSuccess: () => {
        showToast("Usunięto posiedzenie.");
        router.replace("/rada?tab=posiedzenia");
      },
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się usunąć."), "error"),
    });
  };

  return (
    <section className="min-w-0 space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] text-muted-foreground">
            {plDate(m.held_on)} · {MEETING_KIND_LABELS[m.kind]}
            {m.place ? ` · ${m.place}` : ""}
          </div>
          <h2 className="text-base font-semibold text-foreground">{m.title}</h2>
        </div>
        {isAdmin ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => onEdit(m)}>
              <Pencil className="mr-1 h-3.5 w-3.5" />
              Edytuj
            </Button>
            {!m.has_pack ? (
              <Button size="sm" variant="ghost" aria-label="Usuń posiedzenie" onClick={onDelete}>
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            ) : null}
            {m.status !== "cancelled" ? (
              <Button size="sm" onClick={onFreeze} disabled={freeze.isPending}>
                <Send className="mr-1 h-3.5 w-3.5" />
                {m.has_pack ? "Odśwież pakiet" : "Zamroź pakiet i wyślij"}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div>
        <h3 className="mb-1 text-[12px] font-semibold text-foreground">Porządek obrad</h3>
        {m.agenda.length ? (
          <ol className="list-decimal space-y-1 pl-5 text-[12px]">
            {m.agenda.map((item, i) => (
              <li key={i}>
                <span className="text-foreground">{item.title}</span>
                {item.document_ids.length ? (
                  <span className="text-muted-foreground">
                    {" — "}
                    {item.document_ids.map((docId, j) => (
                      <React.Fragment key={docId}>
                        {j ? ", " : ""}
                        <Link href="/rada?tab=dokumenty" className="text-primary hover:underline">
                          {docs.get(docId)?.title ?? `dokument ${docId}`}
                        </Link>
                      </React.Fragment>
                    ))}
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[12px] text-muted-foreground">Bez porządku obrad.</p>
        )}
        <p className="mt-1.5 text-[12px] text-muted-foreground">
          Protokół: {minutes ? <Link href="/rada?tab=dokumenty" className="text-primary hover:underline">{minutes.title}</Link> : "jeszcze nie dołączony"}
          {m.note ? ` · ${m.note}` : ""}
        </p>
      </div>

      {m.pack ? (
        <PackView pack={m.pack} frozenAt={m.pack_frozen_at} />
      ) : (
        <div className="rounded-md border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted-foreground">
          Pakiet nie jest jeszcze przygotowany.
          {isAdmin ? " „Zamroź pakiet i wyślij” zapisze dzisiejsze liczby i da znać Radzie." : " Dostaniesz dzwonek, gdy Zarząd go wyśle."}
        </div>
      )}
      {confirmDialog}
    </section>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border px-3 py-2">
      <div className="truncate text-[11px] text-muted-foreground">{label}</div>
      <div className="text-[17px] font-semibold tabular-nums text-foreground">{value}</div>
      {sub ? <div className="text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

function PackView({ pack, frozenAt }: { pack: MeetingPack; frozenAt: string | null }) {
  const f = packFigures(pack);
  const st = pack.statement;
  return (
    <div className="space-y-3 rounded-md bg-muted/40 p-3">
      <div className="text-[12px] text-muted-foreground">
        Pakiet zamrożony {plDate(frozenAt)} · liczby na {plDate(pack.as_of)} · zmiany od {plDate(pack.since)}
        {pack.previous_meeting ? ` (poprzednie posiedzenie ${plDate(pack.previous_meeting.held_on)})` : " (90 dni — brak wcześniejszego posiedzenia)"}
      </div>
      <div className="grid grid-cols-2 gap-2 2xl:grid-cols-4">
        <Tile
          label={`Sprzedaż I–${f.salesMonths || "?"} ${pack.as_of.slice(0, 4)}`}
          value={mlnText(f.salesYtd)}
          sub={f.salesYtdPrevious !== null ? `rok wcześniej ${mlnText(f.salesYtdPrevious)}` : undefined}
        />
        <Tile
          label={`Wynik z faktur I–${f.resultMonths || "?"}`}
          value={mlnText(f.result, 2)}
          sub={f.resultPct !== null ? `${f.resultPct.toLocaleString("pl-PL")}% sprzedaży` : undefined}
        />
        <Tile
          label="Budżet: wykonanie"
          value={f.actualVsPlan ? `${Math.round((100 * f.actualVsPlan.actual) / f.actualVsPlan.plan)}%` : "brak planu"}
          sub={f.planSales !== null ? `plan roku ${mlnText(f.planSales)}` : undefined}
        />
        <Tile
          label={st ? `EBITDA ${st.year}` : "Sprawozdanie roczne"}
          value={st && st.metrics.ebitda !== null ? mlnText(st.metrics.ebitda / 1_000_000, 2) : "—"}
          sub={
            st && st.metrics.net_debt !== null
              ? `${st.metrics.net_debt < 0 ? "gotówka netto" : "dług netto"} ${mlnText(Math.abs(st.metrics.net_debt) / 1_000_000, 2)}`
              : undefined
          }
        />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <h4 className="mb-1 text-[12px] font-semibold text-foreground">Dokumenty od {plDate(pack.since)}</h4>
          {pack.documents.length ? (
            <ul className="space-y-0.5 text-[12px]">
              {pack.documents.slice(0, 12).map((d) => (
                <li key={d.id} className="truncate">
                  {d.doc_date ? <span className="tabular-nums text-muted-foreground">{plDate(d.doc_date)} </span> : null}
                  <span className="text-foreground">{d.title}</span>{" "}
                  <span className="text-muted-foreground">· {CATEGORY_LABELS[d.category]}</span>
                </li>
              ))}
              {pack.documents.length > 12 ? (
                <li className="text-muted-foreground">i {pack.documents.length - 12} więcej w Dokumentach</li>
              ) : null}
            </ul>
          ) : (
            <p className="text-[12px] text-muted-foreground">Brak nowych dokumentów.</p>
          )}
        </div>
        <div>
          <h4 className="mb-1 text-[12px] font-semibold text-foreground">Wpisy w KRS od {plDate(pack.since)}</h4>
          {pack.krs_entries.length ? (
            <ul className="space-y-0.5 text-[12px]">
              {pack.krs_entries.map((e) => (
                <li key={e.number}>
                  <span className="tabular-nums text-muted-foreground">nr {e.number}, {plDate(e.day)}</span>{" "}
                  <span className="text-foreground">{e.description}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-muted-foreground">Bez zmian w KRS.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Edycja (admin) ───────────────────────────────────────────────────────────

const NONE = "none";

function MeetingDialog({
  meeting,
  onClose,
  onSaved,
}: {
  meeting: BoardMeeting | null;
  onClose: () => void;
  onSaved: (id: number) => void;
}) {
  const { showToast } = useToast();
  const save = useSaveBoardMeeting();
  const documents = useBoardDocuments(null);
  const [heldOn, setHeldOn] = React.useState(meeting?.held_on ?? todayIso());
  const [kind, setKind] = React.useState<MeetingKind>(meeting?.kind ?? "meeting");
  const [status, setStatus] = React.useState<MeetingStatus>(meeting?.status ?? "planned");
  const [title, setTitle] = React.useState(meeting?.title ?? "Posiedzenie Rady Nadzorczej");
  const [place, setPlace] = React.useState(meeting?.place ?? "");
  const [note, setNote] = React.useState(meeting?.note ?? "");
  const [minutes, setMinutes] = React.useState<number | null>(meeting?.minutes_document_id ?? null);
  const [agenda, setAgenda] = React.useState<AgendaItem[]>(
    meeting?.agenda.length ? meeting.agenda : [{ title: "Informacja Zarządu o sytuacji spółki", document_ids: [] }],
  );
  const allDocs = documents.data?.items ?? [];
  const minutesOptions = allDocs.filter((d) => d.category === "minutes_supervisory");
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(heldOn) && title.trim() !== "" && agenda.every((a) => a.title.trim() !== "");

  const onSave = () =>
    save.mutate(
      {
        id: meeting?.id ?? null,
        body: {
          held_on: heldOn,
          kind,
          status,
          title: title.trim(),
          place: place.trim() || null,
          agenda: agenda.map((a) => ({ title: a.title.trim(), document_ids: a.document_ids })),
          note: note.trim() || null,
          minutes_document_id: minutes,
        },
      },
      {
        onSuccess: (saved) => {
          showToast("Zapisano posiedzenie.");
          onSaved(saved.id);
          onClose();
        },
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać."), "error"),
      },
    );

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title={meeting ? "Posiedzenie Rady" : "Nowe posiedzenie Rady"}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            Anuluj
          </Button>
          <Button onClick={onSave} disabled={save.isPending || !valid}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="board-meeting-date">Data</Label>
          <Input id="board-meeting-date" type="date" value={heldOn} onChange={(e) => setHeldOn(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-meeting-kind">Tryb</Label>
          <Select value={kind} onValueChange={(v) => setKind(v as MeetingKind)}>
            <SelectTrigger id="board-meeting-kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(MEETING_KIND_LABELS) as MeetingKind[]).map((k) => (
                <SelectItem key={k} value={k}>
                  {MEETING_KIND_LABELS[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-meeting-status">Status</Label>
          <Select value={status} onValueChange={(v) => setStatus(v as MeetingStatus)}>
            <SelectTrigger id="board-meeting-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(MEETING_STATUS_LABELS) as MeetingStatus[]).map((s) => (
                <SelectItem key={s} value={s}>
                  {MEETING_STATUS_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="board-meeting-title">Tytuł</Label>
          <Input id="board-meeting-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-meeting-place">Miejsce / link</Label>
          <Input id="board-meeting-place" value={place} onChange={(e) => setPlace(e.target.value)} placeholder="siedziba spółki, Teams" />
        </div>
      </div>
      <fieldset className="mt-3">
        <legend className="mb-1 text-[12px] font-semibold text-foreground">Porządek obrad</legend>
        <div className="space-y-2">
          {agenda.map((item, i) => (
            <div key={i} className="grid grid-cols-[24px_1fr_220px_32px] items-center gap-2">
              <span className="text-[12px] font-medium text-muted-foreground">{i + 1}.</span>
              <Input
                aria-label={`Punkt ${i + 1}`}
                value={item.title}
                onChange={(e) => setAgenda((prev) => prev.map((a, j) => (j === i ? { ...a, title: e.target.value } : a)))}
                className="h-8"
              />
              <Select
                value={item.document_ids[0] ? String(item.document_ids[0]) : NONE}
                onValueChange={(v) =>
                  setAgenda((prev) => prev.map((a, j) => (j === i ? { ...a, document_ids: v === NONE ? [] : [Number(v)] } : a)))
                }
              >
                <SelectTrigger aria-label={`Dokument do punktu ${i + 1}`} className="h-8 [&>span]:truncate">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>bez dokumentu</SelectItem>
                  {allDocs.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>
                      {d.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Usuń punkt ${i + 1}`}
                onClick={() => setAgenda((prev) => prev.filter((_, j) => j !== i))}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
        <Button size="sm" variant="ghost" className="mt-1" onClick={() => setAgenda((prev) => [...prev, { title: "", document_ids: [] }])}>
          <Plus className="mr-1 h-3.5 w-3.5" />
          Dodaj punkt
        </Button>
      </fieldset>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="board-meeting-minutes">Protokół (z Dokumentów → Protokoły Rady)</Label>
          <Select value={minutes === null ? NONE : String(minutes)} onValueChange={(v) => setMinutes(v === NONE ? null : Number(v))}>
            <SelectTrigger id="board-meeting-minutes">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>—</SelectItem>
              {minutesOptions.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {d.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-meeting-note">Uwagi</Label>
          <Input id="board-meeting-note" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
    </AppModal>
  );
}
