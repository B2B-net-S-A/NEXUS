"use client";

/**
 * Kolumna asystenta w edytorze CV (Edytor CV 3, PR 4, „Ekran 3” makiet).
 *
 * Jedno miejsce do AI (zasada 1): zastępuje pole „Polecenie”, panel planu
 * zmian i dymek nad zaznaczeniem. Rekruter pisze jak do czatu; zmiany są od
 * razu na kartce na zielono, z jednym „Cofnij” na wiadomość (zasada 3). Pytanie
 * z „Tak” i „Nie” pada tylko przy fakcie bez źródła i przy usunięciu jedynego
 * miejsca z wymaganiem klienta (zasada 6). Zaznaczony tekst to kontekst
 * wiadomości. Logika: `useCvAssistant`.
 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import { Check, Loader2, SendHorizontal, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CV_PANEL_ATTR, Marked } from "@/components/v2/cv-editor/Marked";
import type { AssistantMessage, CvAssistantController } from "@/components/v2/cv-editor/useCvAssistant";
import { CV_COMMAND_PRESETS } from "@/lib/api/cvEditorCommand";
import { CV_COMMAND_MAX } from "@/lib/cv-editor-command";
import { cn } from "@/lib/utils";

export interface CvEditorAssistantProps {
  controller: CvAssistantController;
  editor: Editor;
}

const REWRITE_PREFIX = "Napisz od nowa: ";

const EXAMPLES = "Np. „rolę w Logistyce skróć do 3 punktów”, „pogrub Kafkę i Spring Boot”, „stanowisko: Senior Java Engineer”.";

export function CvEditorAssistant({ controller, editor }: CvEditorAssistantProps) {
  const [text, setText] = useState("");
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const view = useEditorState({
    editor,
    selector: ({ editor: current }) => {
      const { from, to, empty } = current.state.selection;
      return {
        doc: current.state.doc,
        selection: empty ? null : current.state.doc.textBetween(from, to, " ").replace(/\s+/g, " ").trim().slice(0, 80) || null,
      };
    },
  });
  const disabled = !controller.enabled || controller.busy;
  // Z „Napisz od nowa…” mieszczą się cztery podpowiedzi, jak na makiecie —
  // „Usuń najstarsze role” wpisuje się wtedy słowami.
  const chips = controller.canRewrite
    ? CV_COMMAND_PRESETS.filter((item) => item.preset !== "drop_old_roles")
    : CV_COMMAND_PRESETS;
  // Nowa odpowiedź albo pytanie ląduje na dole rozmowy — pokaż ją bez przewijania ręką.
  useEffect(() => {
    const node = log.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [controller.messages.length, controller.locked]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (disabled || text.trim().length < 3) return;
    controller.send({ command: text });
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter wysyła, Shift+Enter to nowa linia — jak w czacie.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  // Wysokość minimalna: nagłówek, dwa rzędy podpowiedzi, pole i kilka linii rozmowy przy 1280×720.
  return (
    <section
      aria-label="Asystent CV"
      className="flex min-h-[18rem] flex-[3_1_0%] flex-col border-t border-border"
      {...{ [CV_PANEL_ATTR]: "" }}
    >
      <header className="px-3 pb-1 pt-2">
        <h2 className="text-sm font-semibold">Napisz, co zmienić</h2>
        <p className="text-[11px] text-muted-foreground">Asystent zmienia CV od razu. Każdą zmianę cofniesz jednym kliknięciem.</p>
      </header>
      <div ref={log} role="log" aria-live="polite" className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {controller.messages.length === 0 ? <p className="text-xs text-muted-foreground">{EXAMPLES}</p> : null}
        {controller.messages.map((message) => (
          <MessageView key={message.id} message={message} controller={controller} doc={view.doc} />
        ))}
        {controller.locked ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> Asystent pracuje… kartka czeka na zmiany.
          </p>
        ) : null}
      </div>
      <div className="space-y-1.5 border-t border-border p-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Podpowiedzi">
          {chips.map((item) => (
            <Button
              key={item.preset}
              type="button"
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              disabled={disabled}
              onClick={() => controller.send({ preset: item.preset, label: item.label })}
            >
              {item.label}
            </Button>
          ))}
          {controller.canRewrite ? (
            // Makieta „Ekran 1”: czwarta podpowiedź wpisuje początek zdania.
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              disabled={disabled}
              onClick={() => {
                setText(REWRITE_PREFIX);
                input.current?.focus();
              }}
            >
              Napisz od nowa…
            </Button>
          ) : null}
        </div>
        {view.selection ? (
          <p className="truncate text-[11px] text-muted-foreground" data-testid="cv-assistant-selection">
            Dotyczy zaznaczenia: „{view.selection}”
          </p>
        ) : null}
        <form className="flex items-end gap-1.5" onSubmit={submit}>
          <textarea
            ref={input}
            aria-label="Napisz, co zmienić"
            placeholder="Napisz, co zmienić…"
            rows={2}
            maxLength={CV_COMMAND_MAX}
            value={text}
            disabled={!controller.enabled}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            className="min-h-[3rem] w-0 flex-1 resize-none rounded-md border border-input bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
          />
          <Button type="submit" size="icon-sm" aria-label="Wyślij" disabled={disabled || text.trim().length < 3}>
            {controller.locked ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : <SendHorizontal aria-hidden className="h-4 w-4" />}
          </Button>
        </form>
      </div>
    </section>
  );
}

function MessageView({
  message,
  controller,
  doc,
}: {
  message: AssistantMessage;
  controller: CvAssistantController;
  doc: unknown;
}) {
  if (message.role === "user") {
    return (
      <div className="ml-6 rounded-lg bg-primary/10 px-2.5 py-1.5 text-sm text-foreground">
        {message.selection ? (
          <p className="mb-0.5 truncate text-[11px] text-muted-foreground">Zaznaczenie: „{message.selection}”</p>
        ) : null}
        <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{message.text}</p>
      </div>
    );
  }
  const question = message.question;
  const undo = message.undo;
  const canUndo = undo?.state === "ready" && undo.after === doc;
  return (
    <div
      className={cn(
        "mr-4 space-y-1.5 rounded-lg px-2.5 py-1.5 text-sm",
        message.tone === "error" ? "bg-destructive-muted text-destructive-muted-foreground" : "bg-muted/60 text-foreground",
      )}
      data-testid="cv-assistant-reply"
    >
      <p>{message.text}</p>
      {message.items && message.items.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-4 text-xs">
          {message.items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      ) : null}
      {question?.kind === "source" && question.operation.text ? (
        <p className="rounded-md border border-border bg-background px-2 py-1 text-xs">
          <Marked text={question.operation.text} />
        </p>
      ) : null}
      {message.words && message.words.length > 0 ? (
        <p className="text-[11px] text-muted-foreground">Sprawdź nowe słowa: {message.words.join(", ")}</p>
      ) : null}
      {question ? <QuestionView messageId={message.id} question={question} controller={controller} /> : null}
      {undo ? (
        undo.state === "done" ? (
          <p className="text-[11px] text-muted-foreground">Cofnięte.</p>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            disabled={!canUndo}
            title={canUndo ? undefined : "CV zmieniło się po tej zmianie — cofnij ręcznie (Ctrl+Z)."}
            onClick={() => controller.undo(message.id)}
          >
            <Undo2 aria-hidden className="mr-1 h-3.5 w-3.5" /> Cofnij
          </Button>
        )
      ) : null}
    </div>
  );
}

function QuestionView({
  messageId,
  question,
  controller,
}: {
  messageId: number;
  question: NonNullable<AssistantMessage["question"]>;
  controller: CvAssistantController;
}) {
  if (question.state === "yes") {
    return (
      <p className="flex items-center gap-1 text-[11px] text-success-muted-foreground">
        <Check aria-hidden className="h-3.5 w-3.5" />
        {question.kind === "source" ? "Dopisane. Fakt jest w notatkach rekrutacji z Twoim nazwiskiem." : "Zmienione."}
      </p>
    );
  }
  if (question.state === "no") return <p className="text-[11px] text-muted-foreground">Pominięte.</p>;
  const busy = question.state === "busy";
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          className="h-7 px-2 text-xs"
          disabled={busy || controller.busy}
          loading={busy}
          onClick={() => void controller.answer(messageId, true)}
        >
          {question.kind === "source" ? "Tak, dopisz" : "Tak, zmień"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 px-2 text-xs"
          disabled={busy || controller.busy}
          onClick={() => void controller.answer(messageId, false)}
        >
          Nie
        </Button>
      </div>
      {question.kind === "source" ? (
        <p className="text-[11px] text-muted-foreground">
          „Tak” zapisze w notatkach rekrutacji: „Potwierdzone z kandydatem: {question.subject}”.
        </p>
      ) : null}
    </div>
  );
}
