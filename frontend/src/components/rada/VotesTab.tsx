"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, FilePlus2, Gavel, Minus, X } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  VOTE_CHOICE_LABELS,
  useBoardDocuments,
  useBoardVotes,
  useCastBoardBallot,
  useCloseBoardVote,
  useCreateBoardVote,
  type BoardVote,
  type VoteChoice,
  type VoteTally,
  type VotesResponse,
} from "@/lib/api/supervisory-board";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

// ── Czyste wyliczenia (testy) ────────────────────────────────────────────────

export type VerdictTone = "passed" | "failed" | "pending" | "withdrawn";

/** Co pokazać przy uchwale: wynik zamkniętej albo stan głosowania w toku. */
export function verdict(vote: Pick<BoardVote, "status" | "result" | "tally">): { tone: VerdictTone; label: string } {
  if (vote.status === "withdrawn") return { tone: "withdrawn", label: "wycofana" };
  if (vote.status === "closed" && vote.result) {
    if (vote.result.passed) return { tone: "passed", label: "podjęta" };
    return { tone: "failed", label: vote.result.quorum_met ? "niepodjęta" : "niepodjęta — za mało głosów" };
  }
  const t = vote.tally;
  if (!t.quorum_met) return { tone: "pending", label: `głosowało ${t.voted} z ${t.members} — potrzeba ${t.quorum}` };
  return { tone: "pending", label: t.passed ? "na razie większość za" : "na razie brak większości" };
}

export function tallyLine(t: VoteTally): string {
  return `za ${t.for} · przeciw ${t.against} · wstrzymało się ${t.abstain}`;
}

const VERDICT_BADGE: Record<VerdictTone, "success" | "danger" | "info" | "neutral"> = {
  passed: "success",
  failed: "danger",
  pending: "info",
  withdrawn: "neutral",
};

const CHOICE_ICON: Record<VoteChoice, typeof Check> = { for: Check, against: X, abstain: Minus };

function plDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── Widok ────────────────────────────────────────────────────────────────────

export function VotesTab() {
  const params = useSearchParams();
  const isAdmin = hasRole(useAuthStore((s) => s.user), "admin");
  const votes = useBoardVotes();
  const [creating, setCreating] = React.useState(false);
  const focus = Number(params.get("uchwala")) || null;
  const state = resolveViewState({
    isLoading: votes.isLoading,
    isError: votes.isError,
    error: votes.error,
    isSuccess: votes.isSuccess,
  });
  if (isBlockingViewState(state)) {
    return <QueryStateNotice state={state as "forbidden" | "not_found" | "error"} onRetry={() => votes.refetch()} />;
  }
  if (!votes.data) {
    return <div className="h-40 animate-pulse rounded-lg border border-border bg-card" aria-hidden />;
  }
  const data = votes.data;
  const open = data.items.filter((v) => v.status === "open");
  const done = data.items.filter((v) => v.status !== "open");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-[12px] leading-snug text-muted-foreground">
          Uchwały Rady w trybie pisemnym (§ 25 ust. 4 statutu): ważne, gdy projekt dostali wszyscy członkowie Rady i głosowała co
          najmniej połowa. Rozstrzyga zwykła większość głosów oddanych, przy remisie głos Przewodniczącego. Podjęta uchwała trafia do
          Dokumentów → Uchwały Rady. Reguły według projektu statutu z 16.09.2025.
        </p>
        {isAdmin ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            <FilePlus2 className="mr-1 h-3.5 w-3.5" />
            Uchwała do głosowania
          </Button>
        ) : null}
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">Do głosowania</h2>
        {open.length ? (
          open.map((v) => <VoteCard key={v.id} vote={v} isAdmin={isAdmin} focused={v.id === focus} />)
        ) : (
          <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted-foreground">
            Nie ma uchwał czekających na głos.
          </p>
        )}
      </section>

      {done.length ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">Zakończone</h2>
          {done.map((v) => (
            <VoteCard key={v.id} vote={v} isAdmin={isAdmin} focused={v.id === focus} />
          ))}
        </section>
      ) : null}

      {creating ? <CreateDialog data={data} onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

function VoteCard({ vote, isAdmin, focused }: { vote: BoardVote; isAdmin: boolean; focused: boolean }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const cast = useCastBoardBallot();
  const close = useCloseBoardVote();
  const v = verdict(vote);
  const t = vote.result ?? vote.tally;
  const chair = vote.members.find((m) => m.id === vote.chair_user_id);

  const onClose = async (action: "close" | "withdraw") => {
    const ok = await askConfirm(
      action === "close"
        ? {
            title: "Zamknąć głosowanie?",
            description: `${tallyLine(vote.tally)}; głosowało ${vote.tally.voted} z ${vote.tally.members}. ${
              vote.tally.passed ? "Uchwała zostanie podjęta i trafi do Dokumentów." : "Uchwała nie zostanie podjęta."
            } Rada dostanie dzwonek z wynikiem.`,
            confirmLabel: "Zamknij",
          }
        : {
            title: "Wycofać uchwałę?",
            description: "Głosowanie się zakończy bez wyniku. Oddane głosy zostaną w historii.",
            confirmLabel: "Wycofaj",
            variant: "destructive",
          },
    );
    if (!ok) return;
    close.mutate(
      { id: vote.id, action },
      {
        onSuccess: (r) =>
          showToast(action === "withdraw" ? "Wycofano uchwałę." : r.result?.passed ? "Uchwała podjęta." : "Uchwała niepodjęta."),
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zamknąć głosowania."), "error"),
      },
    );
  };

  return (
    <article
      className={cn(
        "min-w-0 rounded-lg border bg-card p-4",
        focused ? "border-primary" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] text-muted-foreground">
            {vote.number ? `Uchwała nr ${vote.number} · ` : ""}
            {vote.status === "open" ? `głos do ${plDate(vote.deadline)}` : `zamknięta ${plDate(vote.closed_at)}`}
            {chair ? ` · Przewodniczący: ${chair.name}` : ""}
          </div>
          <h3 className="text-[15px] font-semibold text-foreground">{vote.title}</h3>
        </div>
        <Badge variant={VERDICT_BADGE[v.tone]} size="sm">
          {v.label}
        </Badge>
      </div>

      <p className="mt-2 whitespace-pre-line rounded-md bg-muted/40 px-3 py-2 text-[13px] leading-relaxed text-foreground">
        {vote.draft}
      </p>
      {vote.document_id ? (
        <Link href="/rada?tab=dokumenty" className="mt-1 inline-block text-[12px] text-primary hover:underline">
          Projekt w Dokumentach
        </Link>
      ) : null}

      <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto]">
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          {vote.members.map((m) => {
            const Icon = m.choice ? CHOICE_ICON[m.choice] : null;
            return (
              <li key={m.id} className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "inline-flex h-4 w-4 items-center justify-center rounded-full border",
                    m.choice === "for" && "border-success text-success",
                    m.choice === "against" && "border-destructive text-destructive",
                    m.choice === "abstain" && "border-border text-muted-foreground",
                    !m.choice && "border-dashed border-border",
                  )}
                  aria-hidden
                >
                  {Icon ? <Icon className="h-3 w-3" /> : null}
                </span>
                <span className="text-foreground">{m.name}</span>
                <span className="text-muted-foreground">{m.choice ? VOTE_CHOICE_LABELS[m.choice].toLowerCase() : "jeszcze nie głosował(a)"}</span>
              </li>
            );
          })}
        </ul>
        <div className="text-right text-[12px] tabular-nums text-muted-foreground">
          {tallyLine(t)}
          {t.tie_broken_by_chair ? " · remis rozstrzygnął Przewodniczący" : ""}
          {vote.resolution_document_id ? (
            <>
              {" · "}
              <Link href="/rada?tab=dokumenty" className="text-primary hover:underline">
                uchwała w Dokumentach
              </Link>
            </>
          ) : null}
        </div>
      </div>

      {vote.can_vote || (isAdmin && vote.status === "open") ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          {vote.can_vote ? (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Twój głos">
              <span className="text-[12px] text-muted-foreground">Twój głos:</span>
              {(Object.keys(VOTE_CHOICE_LABELS) as VoteChoice[]).map((choice) => (
                <Button
                  key={choice}
                  size="sm"
                  variant={vote.my_choice === choice ? "primary" : "outline"}
                  aria-pressed={vote.my_choice === choice}
                  disabled={cast.isPending}
                  onClick={() =>
                    cast.mutate(
                      { id: vote.id, choice },
                      {
                        onSuccess: () => showToast(`Oddano głos: ${VOTE_CHOICE_LABELS[choice].toLowerCase()}.`),
                        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się oddać głosu."), "error"),
                      },
                    )
                  }
                >
                  {VOTE_CHOICE_LABELS[choice]}
                </Button>
              ))}
            </div>
          ) : (
            <span />
          )}
          {isAdmin && vote.status === "open" ? (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => onClose("withdraw")} disabled={close.isPending}>
                Wycofaj
              </Button>
              {!vote.closable ? (
                <span className="text-[11px] text-muted-foreground">zamknięcie po {plDate(vote.deadline)} albo gdy zagłosują wszyscy</span>
              ) : null}
              <Button size="sm" variant="outline" onClick={() => onClose("close")} disabled={close.isPending || !vote.closable}>
                <Gavel className="mr-1 h-3.5 w-3.5" />
                Zamknij głosowanie
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {confirmDialog}
    </article>
  );
}

// ── Nowa uchwała (admin) ─────────────────────────────────────────────────────

const NONE = "none";

function CreateDialog({ data, onClose }: { data: VotesResponse; onClose: () => void }) {
  const { showToast } = useToast();
  const create = useCreateBoardVote();
  const documents = useBoardDocuments(null);
  const [number, setNumber] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [draft, setDraft] = React.useState("");
  const [deadline, setDeadline] = React.useState(inDays(7));
  const [chair, setChair] = React.useState<number | null>(null);
  const [documentId, setDocumentId] = React.useState<number | null>(null);
  const [confirmed, setConfirmed] = React.useState(false);
  const valid = title.trim() !== "" && draft.trim() !== "" && /^\d{4}-\d{2}-\d{2}$/.test(deadline) && confirmed;

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title="Uchwała Rady do głosowania pisemnego"
      description={`Projekt dostanie ${data.board.length} członków Rady (dzwonek w NEXUSIE).`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={create.isPending}>
            Anuluj
          </Button>
          <Button
            disabled={create.isPending || !valid}
            onClick={() =>
              create.mutate(
                {
                  number: number.trim() || null,
                  title: title.trim(),
                  draft: draft.trim(),
                  document_id: documentId,
                  meeting_id: null,
                  deadline,
                  chair_user_id: chair,
                  not_excluded_matter: confirmed,
                },
                {
                  onSuccess: () => {
                    showToast("Wysłano projekt uchwały do Rady.");
                    onClose();
                  },
                  onError: (e) => showToast(apiErrorMessage(e, "Nie udało się wysłać uchwały."), "error"),
                },
              )
            }
          >
            Wyślij Radzie
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
        <div className="space-y-1">
          <Label htmlFor="board-vote-number">Numer</Label>
          <Input id="board-vote-number" value={number} onChange={(e) => setNumber(e.target.value)} placeholder="np. 4/2026" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-vote-title">W sprawie</Label>
          <Input id="board-vote-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="np. oceny sprawozdania finansowego za 2025" />
        </div>
      </div>
      <div className="mt-3 space-y-1">
        <Label htmlFor="board-vote-draft">Treść projektu</Label>
        <Textarea id="board-vote-draft" rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="board-vote-deadline">Głos do</Label>
          <Input id="board-vote-deadline" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-vote-chair">Przewodniczący (remis)</Label>
          <Select value={chair === null ? NONE : String(chair)} onValueChange={(v) => setChair(v === NONE ? null : Number(v))}>
            <SelectTrigger id="board-vote-chair">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>—</SelectItem>
              {data.board.map((m) => (
                <SelectItem key={m.id} value={String(m.id)}>
                  {m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-vote-document">Projekt w Dokumentach</Label>
          <Select value={documentId === null ? NONE : String(documentId)} onValueChange={(v) => setDocumentId(v === NONE ? null : Number(v))}>
            <SelectTrigger id="board-vote-document" className="[&>span]:truncate">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>bez pliku</SelectItem>
              {(documents.data?.items ?? []).map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {d.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <label className="mt-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-[12px] text-warning-muted-foreground" htmlFor="board-vote-confirm">
        <input
          id="board-vote-confirm"
          type="checkbox"
          className="mt-0.5"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>
          Uchwała nie dotyczy spraw wyłączonych z trybu pisemnego (§ 25 ust. 5 statutu): {data.excluded_matters.join(", ")}.
        </span>
      </label>
    </AppModal>
  );
}
