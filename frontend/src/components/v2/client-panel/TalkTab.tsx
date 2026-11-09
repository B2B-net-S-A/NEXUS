"use client";

import { Button } from "@/components/ui/button";
import type {
  InterviewStatus,
  PanelCandidateDetail,
  PanelThreadItem,
} from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";

import { formatPanelDate, formatSlotLabel } from "./panel-logic";
import { PANEL_CARD, Pill } from "./parts";

/** Otwarty wniosek albo potwierdzona rozmowa: drugi wniosek serwer odrzuci (409). */
export function interviewOpen(status: InterviewStatus): boolean {
  return status === "awaiting_recruiter" || status === "awaiting_dl" || status === "confirmed";
}

/**
 * Serwer oddaje w `thread` wszystkie sprawy osoby, także prośbę o rozmowę i „nie
 * pasuje”. Tu są tylko pytania: tamte mają własne miejsce i nikt na nie nie odpowiada.
 */
export function clientQuestions(detail: PanelCandidateDetail): PanelThreadItem[] {
  return detail.thread.filter((item) => item.kind === "question");
}

const STEPS = ["Terminy wysłane", "Kandydat wybiera", "Rozmowa potwierdzona"] as const;

function InterviewSteps({ status }: { status: InterviewStatus }) {
  const reached = status === "confirmed" ? 2 : 1;
  return (
    <ol className="my-2.5 flex flex-wrap text-xs">
      {STEPS.map((step, index) => (
        <li
          key={step}
          aria-current={index === reached ? "step" : undefined}
          className={cn(
            "min-w-[100px] flex-1 border-t-[3px] pr-2 pt-1.5",
            index < reached && "border-success text-foreground",
            index === reached && "border-primary font-semibold text-foreground",
            index > reached && "border-border text-muted-foreground",
          )}
        >
          {step}
        </li>
      ))}
    </ol>
  );
}

export function TalkTab({
  detail,
  allowActions,
  ownerName,
  onAsk,
  onRequestInterview,
}: {
  detail: PanelCandidateDetail;
  allowActions: boolean;
  ownerName: string | null;
  onAsk: () => void;
  onRequestInterview: () => void;
}) {
  const { interview } = detail;
  const thread = clientQuestions(detail);
  const open = interviewOpen(interview.status);

  return (
    <div className="grid items-start gap-3 overflow-auto md:grid-cols-2">
      <section className={cn(PANEL_CARD, "px-3.5 py-3")}>
        <h2 className="mb-1.5 font-display text-sm font-semibold">Pytania o kandydata</h2>
        <div className="grid gap-2">
          {thread.length === 0 ? (
            <p className="text-sm text-muted-foreground">Jeszcze nie ma pytań.</p>
          ) : (
            thread.map((item) => (
              <div key={item.id} className="grid gap-1">
                <div className="rounded-lg border border-border px-3 py-2 text-sm">
                  <div className="mb-0.5 text-xs text-muted-foreground">
                    {[item.author, formatPanelDate(item.at)].filter(Boolean).join(", ")}
                  </div>
                  <span className="whitespace-pre-wrap break-words">{item.body}</span>
                </div>
                <div className="ml-6 rounded-lg border border-border bg-muted px-3 py-2 text-sm">
                  {item.answer ? (
                    <>
                      <div className="mb-0.5 text-xs text-muted-foreground">
                        {[ownerName ?? "Opiekun procesu", item.answered_at ? formatPanelDate(item.answered_at) : null]
                          .filter(Boolean)
                          .join(", ")}
                      </div>
                      <span className="whitespace-pre-wrap break-words">{item.answer}</span>
                    </>
                  ) : (
                    <Pill tone="warning">Czeka u opiekuna</Pill>
                  )}
                </div>
              </div>
            ))
          )}
          {allowActions ? (
            <div>
              <Button variant="outline" onClick={onAsk}>
                Zadaj pytanie
              </Button>
            </div>
          ) : null}
        </div>
      </section>

      <section className={cn(PANEL_CARD, "px-3.5 py-3")}>
        <h2 className="mb-1.5 font-display text-sm font-semibold">Rozmowa</h2>
        {open ? (
          <>
            <InterviewSteps status={interview.status} />
            {interview.status === "confirmed" && interview.chosen ? (
              <p className="mb-1 rounded-md bg-success-muted px-2 py-1 text-sm tabular-nums text-success-muted-foreground">
                Termin: {formatSlotLabel(interview.chosen.start)}
              </p>
            ) : (
              interview.slots.map((slot) => (
                <div
                  key={slot.start}
                  className="mb-1 rounded-md bg-muted px-2 py-1 text-sm tabular-nums"
                >
                  {formatSlotLabel(slot.start, slot.window_end)}
                </div>
              ))
            )}
            <p className="mt-1.5 text-xs text-muted-foreground">
              {interview.status === "confirmed"
                ? "Zaproszenie do Teams wysyłasz Ty."
                : "Gdy kandydat wybierze termin, zobaczysz go tutaj. Zaproszenie do Teams wysyłasz Ty, po potwierdzeniu godziny."}
            </p>
          </>
        ) : (
          <>
            <p className="mb-2 text-sm text-muted-foreground">
              {interview.status === "cancelled"
                ? "Poprzedni wniosek o rozmowę został anulowany. "
                : ""}
              {allowActions
                ? "Wybierz kilka terminów. Trafią od razu do opiekuna procesu, a kandydat wybierze jeden."
                : "O rozmowę poprosisz przez opiekuna procesu."}
            </p>
            {allowActions ? <Button onClick={onRequestInterview}>Poproś o rozmowę</Button> : null}
          </>
        )}
      </section>
    </div>
  );
}
