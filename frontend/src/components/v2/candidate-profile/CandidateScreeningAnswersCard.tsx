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
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronDown, MessagesSquare, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { candidateViewerScopeKey } from "@/components/v2/pages/candidate-query-keys";
import { ScreeningAnswersList } from "@/components/v2/screening/ScreeningAnswersList";
import { useCandidateScreeningAnswers } from "@/lib/api/screeningAnswers";
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

export function CandidateScreeningAnswersCard({ candidateId }: { candidateId: number }) {
  const viewerScope = candidateViewerScopeKey(useAuthStore((state) => state.user));
  const query = useCandidateScreeningAnswers(candidateId, viewerScope);
  const [phrase, setPhrase] = useState("");
  // Rozmowy rozwinięte/zwinięte ręcznie; bez wpisu rozwinięta jest najnowsza.
  const [toggled, setToggled] = useState<Record<number, boolean>>({});

  const conversations = useMemo(() => query.data?.conversations ?? [], [query.data]);
  const visible = useMemo(() => filterConversations(conversations, phrase), [conversations, phrase]);
  const searching = phrase.trim().length > 0;

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
  // Brak rozmów = brak karty (pusta ramka nic by nie mówiła).
  if (!query.isSuccess || conversations.length === 0) return null;

  const newestStageId = conversations[0].stage_id;
  const isOpen = (conversation: FilteredConversation) =>
    toggled[conversation.stage_id] ?? (searching || conversation.stage_id === newestStageId);

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
      <CardContent className="space-y-3">
        {conversations.length >= 2 ? (
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
        {visible.length === 0 ? (
          <p role="status" className="text-sm text-muted-foreground">
            Żadna odpowiedź nie pasuje do „{phrase.trim()}”.
          </p>
        ) : (
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
      </CardContent>
    </Card>
  );
}
