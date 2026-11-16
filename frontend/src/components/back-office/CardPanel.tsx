"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Hand } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAssignCard,
  useBoCard,
  useCaseReply,
  useBoTeam,
  useCardNote,
  useDismissCard,
  useReleaseCard,
  useSetCardState,
  useStepDone,
  type BoBoard,
  type BoCard,
} from "@/lib/api/back-office";
import { cn } from "@/lib/utils";

import { amountLabel, dueTone, formatDay } from "./board-model";
import { CardDocuments } from "./CardDocuments";
import { CardSettlementExtras } from "./CardSettlementExtras";
import { ACTION_LABELS } from "./CardTile";
import { ReasonDialog } from "./ReasonDialog";
import type { CardCommands } from "./use-card-commands";

const EVENT_LABELS: Record<string, string> = {
  taken: "wziął(a) kartę",
  substituted: "zastępuje",
  released: "oddał(a) kartę",
  assigned: "przydzielił(a) kartę",
  escalated: "Bez osoby po dniu roboczym: u kierownika",
  closed_by_source: "Zamknięta, bo źródło jest załatwione",
  closed_with_case: "Zamknięta razem ze sprawą",
  step_done: "zaliczył(a) krok",
  step_done_auto: "Krok zaliczony przez system",
  state_new: "ustawił(a) „Nowa”",
  state_in_progress: "ustawił(a) „W toku”",
  state_waiting: "ustawił(a) „Czeka na kogoś”",
  state_done: "zamknął(ęła) kartę",
  dismissed: "„Nie dotyczy”",
  moved: "przeniósł(a) kartę",
  note: "notatka",
  settlement_extra: "zgłosił(a) dodatek do rozliczenia",
  reviewed: "przegląd przed startem",
  routed: "Rozdzielona przez reguły",
  triaged: "Do rozdzielenia u kierownika",
};

/** Sprawy z wątkiem maila: tylko na nie da się odpowiedzieć ze sprawy. */
const MAIL_SOURCES = new Set(["mail"]);

function when(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface CardPanelProps {
  cardId: number;
  board: BoBoard;
  commands: CardCommands;
  onClose: () => void;
}

export function CardPanel({ cardId, board, commands, onClose }: CardPanelProps) {
  const { showToast } = useToast();
  const query = useBoCard(cardId);
  const team = useBoTeam(board.me.is_lead);
  const release = useReleaseCard();
  const assign = useAssignCard();
  const setState = useSetCardState();
  const note = useCardNote();
  const dismiss = useDismissCard();
  const stepDone = useStepDone();
  const reply = useCaseReply();
  const [draft, setDraft] = useState("");
  const [dialog, setDialog] = useState<"waiting" | "dismiss" | "reply" | null>(null);
  const card = query.data;

  const run = async (work: Promise<unknown>, fallback: string, success?: string) => {
    try {
      await work;
      if (success) showToast(success, "success");
    } catch (error) {
      showToast(apiErrorMessage(error, fallback), "error");
    }
  };

  const heading = card ? card.person || card.title : "Sprawa";
  const own = card ? board.me.is_lead || board.me.teams.includes(card.team) : false;
  const mine = card?.assignee?.id === board.me.user_id;
  const amount = card ? amountLabel(card as BoCard) : null;

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-[460px] max-w-full" aria-label="Sprawa">
        <SheetHeader>
          <SheetTitle className="pr-8">{heading}</SheetTitle>
          <SheetDescription asChild>
            <div className="truncate text-sm">
              {card ? [card.person ? card.title : null, card.client].filter(Boolean).join(" · ") : ""}
            </div>
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          {query.isError ? (
            <p className="text-sm text-destructive">{apiErrorMessage(query.error, "Nie udało się wczytać karty.")}</p>
          ) : null}
          {card ? (
            <>
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant={dueTone(card.due_on, board.today)}>Termin: {formatDay(card.due_on)}</Badge>
                {card.assignee ? (
                  <Badge variant="soft">
                    Prowadzi: {card.assignee.name}
                    {card.substituting ? " (zastępuje)" : ""}
                  </Badge>
                ) : (
                  <Badge variant="neutral">Bez osoby</Badge>
                )}
                {card.state === "waiting" && card.waiting_on ? (
                  <Badge variant="warning">Czeka na: {card.waiting_on}</Badge>
                ) : null}
                {amount ? <Badge variant="neutral">Razem {amount}</Badge> : null}
              </div>
              {card.source_kind === "document" ? <CardDocuments cardId={card.id} /> : null}
              {card.source_kind === "case" ? (
                <CardSettlementExtras cardId={card.id} today={board.today} canAdd={own || mine} />
              ) : null}
              {card.priority ? (
                <p className="text-sm text-muted-foreground">
                  Ostatnio rozmawiał(a): {card.priority.name ?? "inna osoba"}
                  {card.priority.until ? `, pierwszeństwo do ${formatDay(card.priority.until)}` : ""}.
                </p>
              ) : null}

              {card.actions.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {card.actions.map((action, index) => (
                    <Button
                      key={action}
                      size="sm"
                      variant={index === 0 ? "primary" : "outline"}
                      disabled={commands.busy}
                      onClick={() => commands.runAction(card, action)}
                    >
                      {ACTION_LABELS[action]}
                    </Button>
                  ))}
                </div>
              ) : null}

              {card.bonuses?.length ? (
                <section>
                  <h4 className="pb-1.5 text-sm font-semibold">Premie w okresie</h4>
                  <ul className="max-h-60 divide-y overflow-y-auto rounded-lg border text-sm">
                    {card.bonuses.map((row) => (
                      <li key={row.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
                        <span className="min-w-0 truncate">
                          {row.person}
                          {row.category ? <span className="text-muted-foreground"> · {row.category}</span> : null}
                        </span>
                        <span className="shrink-0 tabular-nums">
                          {Number(row.amount).toLocaleString("pl-PL")} {row.currency}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {card.step_cards.length > 0 ? (
                <section>
                  <h4 className="pb-1.5 text-sm font-semibold">Kroki</h4>
                  <ol className="divide-y rounded-lg border">
                    {card.step_cards.map((step) => {
                      const done = step.state === "done";
                      return (
                        <li key={step.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                          <span
                            className={cn(
                              "inline-flex size-4 shrink-0 items-center justify-center rounded-sm border",
                              done && "border-success bg-success text-success-foreground",
                            )}
                          >
                            {done ? <Check aria-hidden className="size-3" /> : null}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className={cn("block truncate", done && "text-muted-foreground line-through")}>
                              {step.label}
                            </span>
                            <span className="block text-xs text-muted-foreground">
                              {step.team_label}
                              {step.assignee ? ` · ${step.assignee.name}` : ""}
                            </span>
                          </span>
                          {!done && step.can_act ? (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 px-2.5 text-xs"
                              disabled={stepDone.isPending}
                              onClick={() =>
                                run(stepDone.mutateAsync({ id: step.id }), "Nie udało się zaliczyć kroku.", "Krok zaliczony")
                              }
                            >
                              Zrobione
                            </Button>
                          ) : null}
                          {!done && !step.can_act ? (
                            <span className="text-xs text-muted-foreground">czeka na zespół</span>
                          ) : null}
                        </li>
                      );
                    })}
                  </ol>
                </section>
              ) : null}

              {card.actions.length === 0 && card.state !== "done" ? (
                <div className="flex flex-wrap gap-2">
                  {!card.assignee ? (
                    <Button
                      size="sm"
                      disabled={commands.busy}
                      onClick={() => commands.take(card, { substitute: !own })}
                    >
                      <Hand aria-hidden className="size-3.5" /> {own ? "Biorę" : "Zastępuję"}
                    </Button>
                  ) : null}
                  {card.source_kind === "step" ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={stepDone.isPending || !own}
                      onClick={() =>
                        run(stepDone.mutateAsync({ id: card.id }), "Nie udało się zaliczyć kroku.", "Krok zaliczony")
                      }
                    >
                      Krok zrobiony
                    </Button>
                  ) : null}
                  {mine || board.me.is_lead ? (
                    card.assignee ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={release.isPending}
                        onClick={() => run(release.mutateAsync({ id: card.id }), "Nie udało się oddać karty.")}
                      >
                        Oddaj
                      </Button>
                    ) : null
                  ) : null}
                  {own && board.me.cases_handler && card.case_id != null && MAIL_SOURCES.has(card.case_source ?? "") ? (
                    <Button size="sm" variant="outline" onClick={() => setDialog("reply")}>
                      Odpowiedz
                    </Button>
                  ) : null}
                  {own && card.state !== "waiting" ? (
                    <Button size="sm" variant="outline" onClick={() => setDialog("waiting")}>
                      Czeka na kogoś
                    </Button>
                  ) : null}
                  {own && card.state === "waiting" ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        run(
                          setState.mutateAsync({
                            id: card.id,
                            state: "in_progress",
                            expected_updated_at: card.updated_at,
                          }),
                          "Nie udało się zmienić stanu.",
                        )
                      }
                    >
                      Wraca do pracy
                    </Button>
                  ) : null}
                  {own ? (
                    <Button size="sm" variant="outline" onClick={() => setDialog("dismiss")}>
                      Nie dotyczy
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {board.me.is_lead && team.data && card.actions.length === 0 ? (
                <label className="flex items-center gap-2 text-sm">
                  <span className="shrink-0 text-muted-foreground">Przydziel</span>
                  <select
                    className="h-8 w-0 min-w-0 flex-1 rounded-md border bg-card px-2 text-sm"
                    value=""
                    onChange={(event) => {
                      const userId = Number(event.target.value);
                      if (userId) {
                        run(assign.mutateAsync({ id: card.id, user_id: userId }), "Nie udało się przydzielić.", "Przydzielono");
                      }
                    }}
                  >
                    <option value="">wybierz osobę…</option>
                    {team.data.candidates.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              <section>
                <h4 className="pb-1.5 text-sm font-semibold">Notatka</h4>
                <Textarea
                  rows={2}
                  maxLength={2000}
                  value={draft}
                  aria-label="Treść notatki"
                  onChange={(event) => setDraft(event.target.value)}
                />
                <div className="pt-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!draft.trim() || note.isPending}
                    onClick={async () => {
                      await run(note.mutateAsync({ id: card.id, body: draft.trim() }), "Nie udało się zapisać notatki.");
                      setDraft("");
                    }}
                  >
                    Dodaj notatkę
                  </Button>
                </div>
              </section>

              <section>
                <h4 className="pb-1.5 text-sm font-semibold">Historia</h4>
                {card.events.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Jeszcze nic się tu nie wydarzyło.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm text-muted-foreground">
                    {card.events.map((event, index) => (
                      <li key={`${event.at}-${index}`}>
                        <span className="tabular-nums">{when(event.at)}</span>{" "}
                        {event.actor ? `${event.actor} ` : ""}
                        {EVENT_LABELS[event.action] ?? event.action}
                        {event.note ? `: ${event.note}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {card.href ? (
                <Button size="sm" variant="outline" asChild>
                  <Link href={card.href}>
                    Otwórz ekran pracy <ArrowUpRight aria-hidden className="ml-1 size-3.5" />
                  </Link>
                </Button>
              ) : null}
            </>
          ) : null}
        </SheetBody>
      </SheetContent>
      {commands.dialogs}
      {dialog === "waiting" && card ? (
        <ReasonDialog
          title="Na kogo czeka ta sprawa?"
          label="Kto ma teraz ruch"
          confirmLabel="Zapisz"
          onCancel={() => setDialog(null)}
          onConfirm={async (text) => {
            await run(
              setState.mutateAsync({
                id: card.id,
                state: "waiting",
                waiting_on: text,
                expected_updated_at: card.updated_at,
              }),
              "Nie udało się zmienić stanu.",
            );
            setDialog(null);
          }}
        />
      ) : null}
      {dialog === "reply" && card?.case_id != null ? (
        <ReasonDialog
          title="Odpowiedz w wątku maila"
          label="Treść odpowiedzi"
          confirmLabel="Wyślij"
          busy={reply.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={async (text) => {
            await run(
              reply.mutateAsync({ caseId: card.case_id ?? 0, body: text }),
              "Nie udało się wysłać odpowiedzi.",
              "Odpowiedź wysłana",
            );
            setDialog(null);
          }}
        />
      ) : null}
      {dialog === "dismiss" && card ? (
        <ReasonDialog
          title="Ta karta nie dotyczy"
          label="Dlaczego"
          confirmLabel="Zamknij kartę"
          onCancel={() => setDialog(null)}
          onConfirm={async (text) => {
            await run(dismiss.mutateAsync({ id: card.id, body: text }), "Nie udało się zamknąć karty.");
            setDialog(null);
            onClose();
          }}
        />
      ) : null}
    </Sheet>
  );
}
