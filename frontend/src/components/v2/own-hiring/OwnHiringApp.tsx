"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Lock, Send, Settings } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { AppModal } from "@/components/ds/AppModal";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ownHiringApi,
  ownHiringKeys,
  type OwnHiringBoard,
  type OwnHiringBucket,
  type OwnHiringCard,
  type OwnHiringStage,
} from "@/lib/api/ownHiring";
import { cn } from "@/lib/utils";

import { CallQueue } from "./CallQueue";
import { cardStatus, formatDay, formatDueDay, formatMonths, formatTime } from "./format";
import { PersonPanel } from "./PersonPanel";
import { SettingsView } from "./SettingsView";

const COLUMNS: { stage: OwnHiringStage; title: string }[] = [
  { stage: "new", title: "Nowi" },
  { stage: "invited", title: "Zaproszeni" },
  { stage: "no_response", title: "Bez odpowiedzi" },
  { stage: "assistant", title: "U asystentki" },
  { stage: "teams", title: "Rozmowa Teams" },
  { stage: "office", title: "Rozmowa w biurze" },
  { stage: "contract", title: "Umowa wysłana" },
  { stage: "signed", title: "Podpisani" },
];
const BUCKETS: { key: OwnHiringBucket; label: string; hint: string }[] = [
  { key: "match", label: "Pasuje", hint: "Rola rekrutera albo HR z rekrutacją w opisie" },
  { key: "review", label: "Do sprawdzenia", hint: "Tylko wzmianka o rekrutacji albo nieodczytane CV" },
  { key: "filtered", label: "Odfiltrowani", hint: "Bez śladu rekrutacji w CV" },
];

type View = "board" | "new" | "settings";

function Header({
  title,
  actions,
  sub,
}: {
  title: string;
  sub: string;
  actions: ReactNode;
}) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="truncate text-base font-semibold">{title}</h1>
          <Badge variant="neutral" size="sm" className="gap-1">
            <Lock className="size-2.5" /> Prywatne
          </Badge>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">{actions}</div>
    </header>
  );
}

function BoardView({
  data,
  onOpen,
}: {
  data: OwnHiringBoard;
  onOpen: (id: number) => void;
}) {
  const now = new Date();
  const byStage = useMemo(() => {
    const out = new Map<OwnHiringStage, OwnHiringCard[]>();
    for (const card of data.cards) out.set(card.stage, [...(out.get(card.stage) ?? []), card]);
    return out;
  }, [data.cards]);
  return (
    <div className="flex min-h-0 flex-1 gap-1.5 overflow-x-auto p-3">
      {COLUMNS.map((column) => {
        const cards = byStage.get(column.stage) ?? [];
        const count = column.stage === "new" ? data.new_counts.match : cards.length;
        return (
          <section key={column.stage} className="flex min-w-[108px] flex-1 flex-col rounded-lg bg-muted/40">
            <div className="flex items-center justify-between gap-1 px-2 py-2">
              <h2 className="truncate text-xs font-medium">{column.title}</h2>
              <span className="text-xs tabular-nums text-muted-foreground">{count}</span>
            </div>
            <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-1.5 pb-1.5">
              {cards.map((card) => {
                const status = cardStatus(card, now);
                return (
                  <button
                    key={card.id}
                    type="button"
                    onClick={() => onOpen(card.id)}
                    className="block w-full rounded-md border border-border bg-card p-2 text-left hover:border-primary/40"
                  >
                    <p className="truncate text-xs font-medium">{card.name}</p>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{status.line}</p>
                    <Badge variant={status.tone} size="sm" className="mt-1.5 max-w-full truncate font-normal">
                      {status.badge}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function NewReview({
  counts,
  onOpen,
  onInvite,
}: {
  counts: Record<OwnHiringBucket, number>;
  onOpen: (id: number) => void;
  onInvite: (ids: number[]) => void;
}) {
  const [bucket, setBucket] = useState<OwnHiringBucket>("match");
  const [selected, setSelected] = useState<number[]>([]);
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const list = useQuery({
    queryKey: ["own-hiring", "new", bucket],
    queryFn: () => ownHiringApi.newList(bucket),
  });
  const reject = useMutation({
    mutationFn: (ids: number[]) => ownHiringApi.reject(ids),
    onSuccess: ({ rejected }) => {
      showSuccess(`Odrzucono: ${rejected}`);
      setSelected([]);
      void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all });
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się odrzucić.")),
  });
  const toggle = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  return (
    <>
      <nav className="flex items-center gap-5 border-b border-border px-5 text-sm">
        {BUCKETS.map((item) => (
          <button
            key={item.key}
            type="button"
            title={item.hint}
            onClick={() => {
              setBucket(item.key);
              setSelected([]);
            }}
            className={cn(
              "-mb-px border-b-2 py-2",
              bucket === item.key ? "border-primary font-medium" : "border-transparent text-muted-foreground",
            )}
          >
            {item.label} <span className="tabular-nums text-muted-foreground">{counts[item.key]}</span>
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">Najdłuższe doświadczenie najpierw</span>
      </nav>
      <div className="min-h-0 flex-1 overflow-auto px-5">
        {list.isError && <QueryStateNotice state="error" />}
        {list.isPending && <p className="py-6 text-sm text-muted-foreground">Wczytuję…</p>}
        {list.isSuccess && list.data.length === 0 && (
          <p className="py-6 text-sm text-muted-foreground">Nie ma tu nikogo.</p>
        )}
        {list.isSuccess && list.data.length > 0 && (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-background text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="w-8 py-2" />
                <th className="py-2 font-medium">Osoba</th>
                <th className="py-2 font-medium">Doświadczenie w rekrutacji</th>
                <th className="py-2 font-medium">Skąd</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((person) => {
                const on = selected.includes(person.id);
                return (
                  <tr key={person.id} className={cn("border-b border-border", on && "bg-primary/5")}>
                    <td className="py-2">
                      <button
                        type="button"
                        aria-pressed={on}
                        aria-label={`Zaznacz: ${person.name}`}
                        onClick={() => toggle(person.id)}
                        className={cn(
                          "flex size-4 items-center justify-center rounded border",
                          on ? "border-primary bg-primary text-primary-foreground" : "border-border",
                        )}
                      >
                        {on && <Check className="size-3" />}
                      </button>
                    </td>
                    <td className="py-2">
                      <button type="button" onClick={() => onOpen(person.id)} className="text-left font-medium hover:underline">
                        {person.name}
                      </button>
                      <p className="text-xs text-muted-foreground">{person.city ?? "Brak miasta"}</p>
                    </td>
                    <td className="py-2">
                      <p>
                        {person.role ?? "Brak odczytanej roli"}
                        {person.role && <> · <span className="font-medium">{formatMonths(person.months)}</span></>}
                        {person.is_it && <Badge variant="info" size="sm" className="ml-1.5">IT</Badge>}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {person.company ?? ""}{person.until ? `, do ${person.until}` : person.role ? ", obecnie" : ""}
                      </p>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground">
                      {person.source}<br />{formatDay(person.applied_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <footer className="flex items-center justify-between border-t border-border bg-card px-5 py-2.5">
        <span className="text-sm">Zaznaczone: {selected.length}</span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={selected.length === 0 || reject.isPending}
            onClick={async () => {
              const ok = await askConfirm({
                title: `Odrzucić zaznaczone osoby (${selected.length})?`,
                description: "Karty trafią do zamkniętych. Maile z odmową nie zostaną wysłane.",
                confirmLabel: "Odrzuć",
              });
              if (ok) reject.mutate(selected);
            }}
          >
            Odrzuć
          </Button>
          <Button size="sm" disabled={selected.length === 0} onClick={() => onInvite(selected)}>
            <Send className="mr-1.5 size-3.5" /> Zaproś na rozmowę
          </Button>
        </div>
      </footer>
      {confirmDialog}
    </>
  );
}

function InviteDialog({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const preview = useQuery({
    queryKey: ["own-hiring", "invitation-preview"],
    queryFn: ownHiringApi.invitationPreview,
    enabled: ids.length > 0,
  });
  const send = useMutation({
    mutationFn: () => ownHiringApi.invite(ids),
    onSuccess: ({ results }) => {
      const sent = results.filter((item) => item.outcome === "sent").length;
      const missed = results.length - sent;
      if (missed === 0) showSuccess(`Wysłano zaproszenia: ${sent}`);
      else showError(`Wysłano: ${sent}. Nie wysłano: ${missed} (brak adresu albo błąd skrzynki).`);
      void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all });
      onClose();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się wysłać zaproszeń.")),
  });
  return (
    <AppModal
      open={ids.length > 0}
      onOpenChange={(open) => !open && onClose()}
      title={`Zaproszenie dla: ${ids.length}`}
      size="lg"
      footer={
        <Button size="sm" disabled={!preview.isSuccess || send.isPending} onClick={() => send.mutate()}>
          {send.isPending ? "Wysyłam…" : `Wyślij (${ids.length})`}
        </Button>
      }
    >
      {preview.isError && <p className="text-sm text-destructive">Nie udało się przygotować podglądu.</p>}
      {preview.isSuccess && (
        <div className="space-y-2 text-sm">
          <p className="text-xs"><span className="text-muted-foreground">Temat:</span> {preview.data.subject}</p>
          <p className="whitespace-pre-line rounded-md bg-muted/40 p-3 leading-relaxed">{preview.data.body_text}</p>
          <p className="text-xs text-muted-foreground">
            Mail wyjdzie z Twojej skrzynki. Bez odpowiedzi do końca dnia {formatDueDay(preview.data.response_due_at)} karta przejdzie do „Bez odpowiedzi”.
          </p>
        </div>
      )}
    </AppModal>
  );
}

function CreateProcess() {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [title, setTitle] = useState("IT Rekruter");
  const [ads, setAds] = useState("IT Rekruter / IT Rekruterka\nIT Recruiter");
  const [since, setSince] = useState(() => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10));
  const create = useMutation({
    mutationFn: () =>
      ownHiringApi.createProcess({
        title: title.trim(),
        ad_titles: ads.split("\n").map((line) => line.trim()).filter(Boolean),
        intake_since: since,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all }),
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się utworzyć procesu.")),
  });
  return (
    <div className="mx-auto w-full max-w-md space-y-3 p-6">
      <h1 className="text-base font-semibold">Nowa rekrutacja własna</h1>
      <p className="text-sm text-muted-foreground">Zgłoszenia z podanych ogłoszeń trafią do prywatnego procesu.</p>
      <label className="block text-xs font-medium text-muted-foreground" htmlFor="oh-title">Stanowisko</label>
      <Input id="oh-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} />
      <label className="block text-xs font-medium text-muted-foreground" htmlFor="oh-ads">Tytuły ogłoszeń, każdy w osobnej linii</label>
      <Textarea id="oh-ads" value={ads} onChange={(e) => setAds(e.target.value)} rows={4} />
      <label className="block text-xs font-medium text-muted-foreground" htmlFor="oh-since">Importuj zgłoszenia od</label>
      <Input id="oh-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
      <Button size="sm" disabled={create.isPending || title.trim().length < 2} onClick={() => create.mutate()}>
        Utwórz proces
      </Button>
    </div>
  );
}

function OwnerApp() {
  const [view, setView] = useState<View>("board");
  const [personId, setPersonId] = useState<number | null>(null);
  const [inviteIds, setInviteIds] = useState<number[]>([]);
  const processQuery = useQuery({ queryKey: ["own-hiring", "process"], queryFn: ownHiringApi.process });
  const boardQuery = useQuery({
    queryKey: ["own-hiring", "board"],
    queryFn: ownHiringApi.board,
    refetchInterval: 60_000,
  });
  if (boardQuery.isError || processQuery.isError) return <QueryStateNotice state="error" />;
  if (!boardQuery.data || !processQuery.data) {
    return <p className="p-6 text-sm text-muted-foreground">Wczytuję…</p>;
  }
  const board = boardQuery.data;
  const lastImport = board.last_import_at
    ? `ostatnie zgłoszenie ${formatDay(board.last_import_at)}, ${formatTime(board.last_import_at)}`
    : "bez zgłoszeń";
  const closed = board.closed_counts;
  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-0 flex-col">
      <Header
        title={processQuery.data.title}
        sub={`Ogłoszenia: ${processQuery.data.ad_titles.length} · ${lastImport}`}
        actions={
          <>
            <Button size="sm" variant={view === "board" ? "secondary" : "ghost"} onClick={() => setView("board")}>Tablica</Button>
            <Button size="sm" variant={view === "new" ? "secondary" : "primary"} onClick={() => setView("new")}>
              Przejrzyj Nowych <span className="ml-1.5 tabular-nums">{board.new_counts.match}</span>
            </Button>
            <Button size="icon" variant="ghost" aria-label="Ustawienia" onClick={() => setView("settings")}>
              <Settings className="size-4" />
            </Button>
          </>
        }
      />
      {view === "board" && (
        <>
          <BoardView data={board} onOpen={setPersonId} />
          <footer className="flex items-center gap-5 border-t border-border px-5 py-2 text-xs text-muted-foreground">
            <span>Odrzuceni {closed.rejected ?? 0}</span>
            <span>Zrezygnowali {closed.withdrawn ?? 0}</span>
            <span>Do sprawdzenia {board.new_counts.review}</span>
            <span>Odfiltrowani {board.new_counts.filtered}</span>
          </footer>
        </>
      )}
      {view === "new" && <NewReview counts={board.new_counts} onOpen={setPersonId} onInvite={setInviteIds} />}
      {view === "settings" && <SettingsView process={processQuery.data} />}
      <PersonPanel
        applicationId={personId}
        onClose={() => setPersonId(null)}
        onInvite={(id) => {
          setPersonId(null);
          setInviteIds([id]);
        }}
      />
      <InviteDialog ids={inviteIds} onClose={() => setInviteIds([])} />
    </div>
  );
}

export function OwnHiringApp() {
  const me = useQuery({ queryKey: ownHiringKeys.me, queryFn: ownHiringApi.me });
  if (me.isError) return <QueryStateNotice state="error" />;
  if (!me.data) return <p className="p-6 text-sm text-muted-foreground">Wczytuję…</p>;
  if (me.data.role === "owner") return <OwnerApp />;
  if (me.data.role === "assistant") return <CallQueue />;
  if (me.data.can_create) return <CreateProcess />;
  return <QueryStateNotice state="forbidden" />;
}
