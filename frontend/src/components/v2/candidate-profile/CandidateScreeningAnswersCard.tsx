"use client";

/**
 * „Odpowiedzi z rozmów screeningowych” — zakładka Profil (02.10.2026).
 *
 * Zgłoszenie testerki: po przejściu wszystkich etapów w profilu nie było widać,
 * co kandydat odpowiedział na pytania screeningowe, więc to samo pytanie padało
 * w kolejnej rekrutacji. Karta pokazuje jedną rozmowę na rekrutację (najnowsza
 * rozwinięta, starsze zwinięte); pole szukania pojawia się dopiero przy co
 * najmniej dwóch rozmowach. Bez rozmów karty nie ma; awaria odczytu to
 * komunikat z „Ponów”, nigdy pustka.
 *
 * Zastępuje dawną kartę „Screeningi”, która czytała nieużywaną tabelę notatek
 * screeningowych (ostatni wpis z 15.04.2026).
 *
 * 03.10.2026: pod arkuszami stoją odpowiedzi zapisane w notatkach-kartach
 * rekomendacji (także wpisanych w Traffit) — dla rekrutacji bez arkusza.
 * Arkusz wypełniono w historii kilkadziesiąt razy, a kart z odpowiedziami
 * jest kilka tysięcy; bez nich karta była prawie zawsze pusta.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronDown, MessagesSquare, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { candidateViewerScopeKey } from "@/components/v2/pages/candidate-query-keys";
import { ScreeningAnswersList } from "@/components/v2/screening/ScreeningAnswersList";
import {
  useCandidateCardOverview,
  type CandidateCardConversation,
} from "@/lib/api/candidateCards";
import { useCandidateScreeningAnswers } from "@/lib/api/screeningAnswers";
import { cardConversationMeta, conversationsWithoutSheet } from "@/lib/candidate-card-facts";
import { countPl } from "@/lib/plural-pl";
import {
  SCREENING_FIT_LABEL,
  SCREENING_FIT_VARIANT,
  conversationTitle,
  filterConversations,
  type FilteredConversation,
} from "@/lib/screening-conversations";
import { cn, formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

function Conversation({
  conversation,
  open,
  onToggle,
  highlight,
}: {
  conversation: FilteredConversation;
  open: boolean;
  onToggle: () => void;
  highlight: string;
}) {
  const bodyId = `screening-conversation-${conversation.stage_id}`;
  const meta = [
    conversation.answered_at ? `rozmowa: ${formatDate(conversation.answered_at)}` : null,
    conversation.answered_by_name,
    countPl(conversation.answers.length, "odpowiedź", "odpowiedzi", "odpowiedzi"),
  ].filter(Boolean);
  return (
    <li className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className={cn(
          "flex w-full items-start gap-3 px-3 py-2.5 text-left",
          open && "border-b border-border bg-muted/40",
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-foreground [overflow-wrap:anywhere]">
            {conversationTitle(conversation)}
          </span>
          <span className="block text-xs text-muted-foreground">{meta.join(" · ")}</span>
        </span>
        <Badge size="sm" variant={SCREENING_FIT_VARIANT[conversation.overall_fit]} className="shrink-0">
          {SCREENING_FIT_LABEL[conversation.overall_fit]}
        </Badge>
        <ChevronDown
          className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? (
        <div id={bodyId} className="space-y-3 px-3 py-3">
          <ScreeningAnswersList
            answers={conversation.answers}
            experienceChecks={conversation.experience_checks}
            notes={conversation.notes}
            internalNote={conversation.internal_note}
            highlight={highlight}
          />
          <Link
            href={`/jobs/${conversation.job_id}`}
            className="inline-block text-xs font-medium text-primary hover:underline"
          >
            Otwórz rekrutację
          </Link>
        </div>
      ) : null}
    </li>
  );
}

const fold = (value: string): string => value.toLocaleLowerCase("pl");

/** Odpowiedzi z notatki-karty jednej rekrutacji; domyślnie zwinięte. */
function NoteConversation({
  conversation,
  open,
  onToggle,
}: {
  conversation: CandidateCardConversation;
  open: boolean;
  onToggle: () => void;
}) {
  const bodyId = `card-conversation-${conversation.job_id}`;
  const job = conversation.job_title?.trim() || `Rekrutacja #${conversation.job_id}`;
  const client = conversation.client_name?.trim();
  return (
    <li className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className={cn(
          "flex w-full items-start gap-3 px-3 py-2.5 text-left",
          open && "border-b border-border bg-muted/40",
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-foreground [overflow-wrap:anywhere]">
            {client ? `${job} · ${client}` : job}
          </span>
          <span className="block text-xs text-muted-foreground">
            {cardConversationMeta(conversation)}
          </span>
        </span>
        <ChevronDown
          className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>
      {open ? (
        <div id={bodyId} className="space-y-3 px-3 py-3">
          <ol className="space-y-2">
            {conversation.answers.map((item) => (
              <li key={item.number} className="text-sm">
                <p className="font-medium text-foreground">
                  {item.number}. {item.question || "pytanie bez treści w notatce"}
                </p>
                <p className="mt-0.5 whitespace-pre-line text-foreground [overflow-wrap:anywhere]">
                  {item.answer}
                </p>
              </li>
            ))}
          </ol>
          <Link
            href={`/jobs/${conversation.job_id}`}
            className="inline-block text-xs font-medium text-primary hover:underline"
          >
            Otwórz rekrutację
          </Link>
        </div>
      ) : null}
    </li>
  );
}

export function CandidateScreeningAnswersCard({
  candidateId,
  variant = "card",
}: {
  candidateId: number;
  /**
   * `tab` (04.10.2026) = zakładka „Odpowiedzi ze screeningu”: bez ramki karty,
   * szukanie już przy jednej rozmowie, a brak rozmów to zdanie, nie pustka.
   */
  variant?: "card" | "tab";
}) {
  const asTab = variant === "tab";
  const viewerScope = candidateViewerScopeKey(useAuthStore((state) => state.user));
  const query = useCandidateScreeningAnswers(candidateId, viewerScope);
  const [phrase, setPhrase] = useState("");
  // Rozmowy rozwinięte/zwinięte ręcznie; bez wpisu rozwinięta jest najnowsza.
  const [toggled, setToggled] = useState<Record<number, boolean>>({});
  const [noteToggled, setNoteToggled] = useState<Record<number, boolean>>({});
  // Karty to dodatek: ich awaria nie zasłania arkuszy (i odwrotnie — bez
  // arkuszy karta nadal pokazuje odpowiedzi z notatek).
  const cards = useCandidateCardOverview(candidateId, viewerScope);

  const conversations = useMemo(() => query.data?.conversations ?? [], [query.data]);
  const visible = useMemo(() => filterConversations(conversations, phrase), [conversations, phrase]);
  const searching = phrase.trim().length > 0;
  const noteConversations = useMemo(
    () =>
      conversationsWithoutSheet(
        cards.data?.conversations,
        new Set(conversations.map((conversation) => conversation.job_id)),
      ),
    [cards.data, conversations],
  );
  const visibleNotes = useMemo(() => {
    const needle = fold(phrase.trim());
    if (!needle) return noteConversations;
    return noteConversations
      .map((conversation) => ({
        ...conversation,
        answers: conversation.answers.filter(
          (item) => fold(item.question).includes(needle) || fold(item.answer).includes(needle),
        ),
      }))
      .filter((conversation) => conversation.answers.length > 0);
  }, [noteConversations, phrase]);

  if (query.isError && asTab) {
    return (
      <p role="alert" className="text-sm text-destructive-muted-foreground">
        Nie udało się wczytać odpowiedzi z rozmów.{" "}
        <button
          type="button"
          className="font-medium underline underline-offset-2"
          onClick={() => void query.refetch()}
        >
          Ponów
        </button>
      </p>
    );
  }
  if (query.isError) {
    return (
      <Card role="region" aria-labelledby="candidate-screening-answers-title">
        <CardHeader className="pb-1">
          <CardTitle id="candidate-screening-answers-title" className="flex items-center gap-2">
            <MessagesSquare aria-hidden className="size-4 text-primary" />
            Odpowiedzi z rozmów screeningowych
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p role="alert" className="text-sm text-destructive-muted-foreground">
            Nie udało się wczytać odpowiedzi z rozmów.{" "}
            <button
              type="button"
              className="font-medium underline underline-offset-2"
              onClick={() => void query.refetch()}
            >
              Ponów
            </button>
          </p>
        </CardContent>
      </Card>
    );
  }
  if (asTab && !query.isSuccess) {
    return (
      <p className="text-sm text-muted-foreground" aria-busy="true">
        Wczytuję odpowiedzi z rozmów…
      </p>
    );
  }
  // Karty rekomendacji dochodzą osobnym zapytaniem: zanim odpowiedzą, „nikt
  // nie zapisał” byłoby nieprawdą, a ich awaria nie może udawać pustki.
  const cardsLoading = cards.isPending && cards.fetchStatus !== "idle";
  const cardsRetry = (
    <button
      type="button"
      className="font-medium underline underline-offset-2"
      onClick={() => void cards.refetch()}
    >
      Ponów
    </button>
  );
  if (asTab && conversations.length + noteConversations.length === 0 && cardsLoading) {
    return (
      <p className="text-sm text-muted-foreground" aria-busy="true">
        Wczytuję odpowiedzi z rozmów…
      </p>
    );
  }
  if (asTab && conversations.length + noteConversations.length === 0 && cards.isError) {
    return (
      <p role="alert" className="text-sm text-destructive-muted-foreground">
        Nie udało się wczytać odpowiedzi z notatek. {cardsRetry}
      </p>
    );
  }
  if (asTab && conversations.length + noteConversations.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-help="candidate.profile.screening_answers"
      >
        Nikt jeszcze nie zapisał odpowiedzi z rozmowy screeningowej z tą osobą — ani
        w formularzu screeningu, ani w notatkach.
      </p>
    );
  }
  // Brak rozmów = brak karty (pusta ramka nic by nie mówiła).
  if (!query.isSuccess || conversations.length + noteConversations.length === 0) return null;

  const newestStageId = conversations[0]?.stage_id;
  // Bez arkuszy rozwinięta jest najnowsza rozmowa z notatki.
  const newestNoteJobId = conversations.length === 0 ? noteConversations[0]?.job_id : undefined;
  const isNoteOpen = (conversation: CandidateCardConversation) =>
    noteToggled[conversation.job_id] ?? (searching || conversation.job_id === newestNoteJobId);
  const isOpen = (conversation: FilteredConversation) =>
    toggled[conversation.stage_id] ?? (searching || conversation.stage_id === newestStageId);

  const body = (
    <>
        {conversations.length + noteConversations.length >= (asTab ? 1 : 2) ? (
          <div className="relative">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              value={phrase}
              onChange={(event) => setPhrase(event.target.value)}
              placeholder="Szukaj, np. mikroserwisy"
              aria-label="Szukaj w odpowiedziach"
              className="pl-8"
            />
          </div>
        ) : null}
        {visible.length + visibleNotes.length === 0 ? (
          <p role="status" className="text-sm text-muted-foreground">
            Żadna odpowiedź nie pasuje do „{phrase.trim()}”.
          </p>
        ) : visible.length === 0 ? null : (
          <ul className="space-y-2">
            {visible.map((conversation) => (
              <Conversation
                key={conversation.stage_id}
                conversation={conversation}
                open={isOpen(conversation)}
                onToggle={() =>
                  setToggled((prev) => ({ ...prev, [conversation.stage_id]: !isOpen(conversation) }))
                }
                highlight={phrase}
              />
            ))}
          </ul>
        )}
        {visibleNotes.length > 0 ? (
          <section aria-labelledby="candidate-card-answers-title" className="space-y-2">
            <h3 id="candidate-card-answers-title" className="text-xs font-semibold text-muted-foreground">
              Z notatek rekruterów
            </h3>
            <ul className="space-y-2">
              {visibleNotes.map((conversation) => (
                <NoteConversation
                  key={conversation.job_id}
                  conversation={conversation}
                  open={isNoteOpen(conversation)}
                  onToggle={() =>
                    setNoteToggled((prev) => ({
                      ...prev,
                      [conversation.job_id]: !isNoteOpen(conversation),
                    }))
                  }
                />
              ))}
            </ul>
          </section>
        ) : null}
    </>
  );

  if (asTab) {
    return (
      <div
        role="region"
        aria-label="Odpowiedzi z rozmów screeningowych"
        data-help="candidate.profile.screening_answers"
        className="space-y-3"
      >
        <p className="text-sm text-muted-foreground">
          Co kandydat odpowiedział na pytania z rekrutacji — sprawdź, zanim zapytasz o to samo.
        </p>
        {body}
        {cards.isError ? (
          <p role="alert" className="text-xs text-destructive-muted-foreground">
            Nie udało się wczytać odpowiedzi z notatek. {cardsRetry}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <Card
      role="region"
      aria-labelledby="candidate-screening-answers-title"
      data-help="candidate.profile.screening_answers"
    >
      <CardHeader className="pb-1">
        <CardTitle id="candidate-screening-answers-title" className="flex items-center gap-2">
          <MessagesSquare aria-hidden className="size-4 text-primary" />
          Odpowiedzi z rozmów screeningowych
        </CardTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Co kandydat odpowiedział na pytania z rekrutacji — sprawdź, zanim zapytasz o to samo.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">{body}</CardContent>
    </Card>
  );
}
