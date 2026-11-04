"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TextLimitCounter } from "@/components/v2/forms/TextLimitCounter";
import { readCvRewriteDraft, writeCvRewriteDraft } from "@/lib/cv-rewrite-drafts";
import { useTextareaAutogrow } from "@/lib/use-textarea-autogrow";
import { useAuthStore } from "@/store/auth";

/** Długość uwagi „Napisz od nowa” — jak limit serwera (`GenerateRequest.instruction`). */
export const REWRITE_MAX = 2000;

interface CvRewriteFormProps {
  /** Wiersz etapu, którego szkic CV zostanie napisany od nowa — klucz szkicu listy. */
  stageId: number;
  onRewrite: (instruction: string) => void;
}

/**
 * „Co poprawić?” + „Napisz od nowa” w karcie „CV do klienta” (15.10.2026):
 * lista poprawek do 2000 znaków, linia = poprawka. Pole rośnie do 8 linii,
 * Enter robi nową linię (lista nie wysyła się w połowie), Ctrl/⌘+Enter
 * wysyła. Za długiej listy nic nie ucina — przycisk czeka. Niewysłana lista
 * zostaje w szkicu karty przeglądarki (lib/cv-rewrite-drafts.ts).
 */
export function CvRewriteForm({ stageId, onRewrite }: CvRewriteFormProps) {
  const userId = useAuthStore((s) => s.user?.id);
  const [text, setTextState] = useState(() => readCvRewriteDraft(userId, stageId));
  const setText = (next: string) => {
    setTextState(next);
    writeCvRewriteDraft(userId, stageId, next);
  };
  const field = useRef<HTMLTextAreaElement | null>(null);
  const [wrapper, setWrapper] = useState<HTMLDivElement | null>(null);
  useTextareaAutogrow(field, wrapper, text, 8);

  const length = text.trim().length;
  const tooLong = length > REWRITE_MAX;
  const submit = () => {
    if (tooLong) return;
    setText("");
    onRewrite(text);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  return (
    <form
      aria-label="Napisz od nowa"
      className="space-y-1 border-t border-border pt-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div ref={setWrapper}>
        <textarea
          ref={field}
          aria-label="Co poprawić?"
          placeholder="Co poprawić?"
          rows={1}
          value={text}
          aria-invalid={tooLong || undefined}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          className="block w-full resize-none rounded-md border border-input bg-background px-2.5 py-1.5 text-sm leading-5 placeholder:text-muted-foreground aria-[invalid=true]:border-destructive"
        />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1">
        <span className="mr-auto text-[11px] text-muted-foreground">Enter nowa linia · Ctrl+Enter napisz od nowa</span>
        <TextLimitCounter length={length} max={REWRITE_MAX} />
        <Button
          type="submit"
          size="sm"
          variant="outline"
          disabled={tooLong}
          title={tooLong ? `Lista jest za długa — skróć ją o ${length - REWRITE_MAX} znaków.` : undefined}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden /> Napisz od nowa
        </Button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Każda linia to osobna poprawka. Twoje ręczne poprawki zostaną, a fakty z listy zapiszą się w notatkach.
      </p>
    </form>
  );
}
