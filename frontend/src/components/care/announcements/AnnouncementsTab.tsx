"use client";

// Opieka → Komunikaty (etap 3, O12, makiety M7–M8). Zakładkę wpina `CareScreen`
// (wartość `?tab=announcements`); wybrany komunikat to `?announcement=<id>`,
// nowy — `?announcement=new` (link z powiadomienia „do zatwierdzenia”).

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Megaphone } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice, type BlockingViewState } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAnnouncement,
  useAnnouncementSettings,
  useAnnouncements,
  type AnnouncementList,
  type AnnouncementRow,
} from "@/lib/api/care-announcements";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";

import { AnnouncementEditor } from "./AnnouncementEditor";
import { AnnouncementReport } from "./AnnouncementReport";
import { KIND_LABELS, plural, statusView } from "./announcement-format";

const PARAM = "announcement";

function blockingState(error: unknown): BlockingViewState {
  const status = httpStatusFromError(error);
  return status === 403 ? "forbidden" : status === 404 ? "not_found" : "error";
}

function SendingNotice({ list }: { list: AnnouncementList }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const switchSending = useAnnouncementSettings();
  const { settings, me } = list;

  const toggle = async () => {
    const enable = !settings.sending_enabled;
    const confirmed = await askConfirm(
      enable
        ? {
            title: "Włączyć wysyłkę komunikatów do konsultantów?",
            description:
              "To maile do ludzi spoza firmy. Zatwierdzone komunikaty zaczną wychodzić z administracja@ w kolejce.",
            confirmLabel: "Włącz wysyłkę",
          }
        : {
            title: "Wyłączyć wysyłkę komunikatów?",
            description: "Kolejka zatrzyma się w miejscu. Szkice, podgląd i próba do siebie dalej działają.",
            confirmLabel: "Wyłącz wysyłkę",
            variant: "destructive",
          },
    );
    if (!confirmed) return;
    switchSending.mutate(enable, {
      onSuccess: () => showToast(enable ? "Wysyłka włączona" : "Wysyłka wyłączona", "success"),
      onError: (error) =>
        showToast(apiErrorMessage(error, "Nie udało się zmienić ustawienia wysyłki."), "error"),
    });
  };

  const lines: string[] = [];
  if (!settings.sending_enabled) {
    lines.push(
      "Wysyłka do konsultantów jest wyłączona. Szkice, podgląd odbiorców i próba do siebie działają.",
    );
  }
  if (settings.transport === "simulate") lines.push("Tryb symulacji — maile nie wychodzą z NEXUSA.");
  if (settings.transport === "off" || settings.transport === "unconfigured") {
    lines.push("Wysyłka maili z administracja@ nie jest jeszcze skonfigurowana.");
  }
  if (!lines.length && !me.is_admin) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm"
    >
      <div className="space-y-0.5">
        {lines.length ? lines.map((line) => <p key={line}>{line}</p>) : <p>Wysyłka do konsultantów jest włączona.</p>}
      </div>
      {me.is_admin ? (
        <Button
          size="sm"
          variant={settings.sending_enabled ? "quiet" : "outline"}
          loading={switchSending.isPending}
          onClick={() => void toggle()}
        >
          {settings.sending_enabled ? "Wyłącz wysyłkę" : "Włącz wysyłkę"}
        </Button>
      ) : null}
      {confirmDialog}
    </div>
  );
}

function AnnouncementsTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: AnnouncementRow[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[620px] text-sm">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "sticky left-0 bg-card px-3 py-2 text-left")}>Komunikat</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Do kogo</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Stan</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Odpowiedzi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const view = statusView(row);
            const selected = row.id === selectedId;
            return (
              <tr
                key={row.id}
                className={cn(CALM_ROW, selected && "bg-primary/5")}
                aria-selected={selected}
              >
                <td className={cn("sticky left-0 px-3 py-1.5", selected ? "bg-primary/5" : "bg-card")}>
                  <button
                    type="button"
                    onClick={() => onSelect(row.id)}
                    className="text-left font-medium hover:underline"
                  >
                    {row.subject}
                  </button>
                  <span className={CALM_SUBLINE}>
                    {KIND_LABELS[row.kind].toLowerCase()} · {row.author?.name ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-1.5">
                  {row.audience_label}
                  {row.recipient_count ? ` · ${row.recipient_count}` : ""}
                </td>
                <td className="px-3 py-1.5">
                  <StatusDot tone={view.tone} note={view.note ?? undefined}>
                    {view.label}
                  </StatusDot>
                </td>
                <td className="px-3 py-1.5">
                  {row.replies.reply ? (
                    `${row.replies.reply} w Sprawach`
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AnnouncementsTab() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const raw = searchParams?.get(PARAM) ?? null;
  const creating = raw === "new";
  const selectedId = raw && /^\d+$/.test(raw) ? Number(raw) : null;
  const list = useAnnouncements();
  const detail = useAnnouncement(selectedId);
  // Nowa sesja edytora przy wejściu z listy; pierwszy zapis szkicu jej nie zmienia.
  const [session, setSession] = useState(0);

  const writeParam = (value: string | null) => {
    const params = new URLSearchParams(window.location.search);
    if (value === null) params.delete(PARAM);
    else params.set(PARAM, value);
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };
  const open = (value: string | null) => {
    setSession((current) => current + 1);
    writeParam(value);
  };

  const rows = list.data?.items ?? [];
  const view = resolveViewState({
    isLoading: list.isLoading,
    isError: list.isError,
    error: list.error,
    isSuccess: list.isSuccess,
    isEmpty: rows.length === 0,
  });
  if (view === "forbidden" || view === "not_found" || view === "error") {
    return <QueryStateNotice state={view} onRetry={() => list.refetch()} />;
  }
  if (view === "loading" || !list.data) {
    return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  const data = list.data;
  const editing =
    creating || (detail.data !== undefined && detail.data.can_edit && detail.data.status === "draft");

  if (editing) {
    if (selectedId !== null && !detail.data) {
      return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
    }
    return (
      <AnnouncementEditor
        key={session}
        announcement={creating ? null : (detail.data ?? null)}
        settings={data.settings}
        onBack={() => open(null)}
        onCreated={(id) => writeParam(String(id))}
        onSubmitted={(id) => open(String(id))}
      />
    );
  }

  const pendingForMe = rows.filter((row) => row.can_approve).length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Maile z administracja@ do grup konsultantów — osobny do każdego, odpowiedzi trafiają do Spraw.
          {pendingForMe
            ? ` Czeka na Ciebie: ${plural(pendingForMe, "komunikat", "komunikaty", "komunikatów")}.`
            : ""}
        </p>
        {data.me.can_author ? (
          <Button size="sm" onClick={() => open("new")}>
            Nowy komunikat
          </Button>
        ) : null}
      </div>
      <SendingNotice list={data} />
      {view === "empty" ? (
        <EmptyState
          icon={Megaphone}
          title="Nie ma jeszcze komunikatów"
          description="Komunikat idzie mailem do wybranej grupy konsultantów: wszystkich, klienta, opiekuna, formy współpracy albo kończących zamówienie."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <AnnouncementsTable rows={rows} selectedId={selectedId} onSelect={(id) => open(String(id))} />
          <div>
            {selectedId === null ? (
              <p className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
                Wybierz komunikat, żeby zobaczyć stan wysyłki i raport.
              </p>
            ) : detail.isError ? (
              <QueryStateNotice state={blockingState(detail.error)} onRetry={() => detail.refetch()} />
            ) : detail.data ? (
              <AnnouncementReport
                announcement={detail.data}
                settings={data.settings}
                onEdit={() => open(String(detail.data?.id))}
              />
            ) : (
              <p className="text-sm text-muted-foreground">Wczytywanie…</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
