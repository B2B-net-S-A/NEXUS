"use client";

// Pole zapisu nad strumieniem „Rozmowy i notatki” (wariant A, 20.11.2026).
// Rodzaj wpisu to pigułki zamiast natywnej listy:
// - „Notatka” — notatka przy kontrakcie (`POST /api/contracts/{id}/notes`,
//   ta sama bramka co dotąd: edycja kontraktów w zakresie klienta), rodzaj
//   notatki (notatka, telefon, spotkanie, e-mail) z menu pod polem;
// - „Rozmowa z konsultantem” — okno rozmowy opieki z wpisanym tekstem
//   i najbliższym punktem planu (zapis jak z karty: forma, ocena, sygnały);
// - „Rozmowa z klientem” — okno opinii menedżera u klienta.
// Pole notatki kontraktu nie ma wzmianek „@”: ta trasa ich nie rozsyła,
// więc lista osób obiecywałaby powiadomienie, które nie wyjdzie.

import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { contractsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import type { CareStreamActions } from "../card/ConsultantCard";

export type ComposerKind = "note" | "consultant" | "client";
export type NoteType = "general" | "call" | "meeting" | "email";

export const NOTE_TYPES: { value: NoteType; label: string }[] = [
  { value: "general", label: "Notatka" },
  { value: "call", label: "Telefon" },
  { value: "meeting", label: "Spotkanie" },
  { value: "email", label: "E-mail" },
];

const KIND_LABELS: Record<ComposerKind, string> = {
  note: "Notatka",
  consultant: "Rozmowa z konsultantem",
  client: "Rozmowa z klientem",
};

const PLACEHOLDERS: Record<ComposerKind, string> = {
  note: "Co warto zapamiętać przy tym kontrakcie?",
  consultant: "Co ustalono w rozmowie z konsultantem?",
  client: "Co powiedział menedżer u klienta?",
};

/** Rodzaje wpisu, do których czytający ma prawo; kolejność jak w makiecie. */
export function composerKinds(canAddNote: boolean, care: CareStreamActions | null): ComposerKind[] {
  return [
    canAddNote ? ("note" as const) : null,
    care?.canTalk ? ("consultant" as const) : null,
    care?.canFeedback ? ("client" as const) : null,
  ].filter((kind): kind is ComposerKind => kind !== null);
}

/** Na start rozmowa, gdy czeka punkt planu (to najczęstszy wpis), inaczej pierwszy rodzaj. */
export function defaultKind(kinds: ComposerKind[], care: CareStreamActions | null): ComposerKind | null {
  if (kinds.includes("consultant") && care?.nextPlan) return "consultant";
  return kinds[0] ?? null;
}

interface CareComposerProps {
  contractId: number;
  canAddNote: boolean;
  care: CareStreamActions | null;
}

export function CareComposer({ contractId, canAddNote, care }: CareComposerProps) {
  const ids = { text: useId(), hint: useId() };
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const kinds = composerKinds(canAddNote, care);
  const [picked, setPicked] = useState<ComposerKind | null>(null);
  const [noteType, setNoteType] = useState<NoteType>("general");
  const [text, setText] = useState("");
  const kind = picked && kinds.includes(picked) ? picked : defaultKind(kinds, care);

  const saveNote = useMutation({
    mutationFn: () => contractsApi.createNote(contractId, { content: text.trim(), note_type: noteType }),
    onSuccess: () => {
      setText("");
      setNoteType("general");
      void queryClient.invalidateQueries({ queryKey: ["contract-notes-timeline", contractId] });
      showToast("Notatka zapisana przy kontrakcie", "success");
    },
    onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać notatki."), "error"),
  });

  if (!kind) return null;
  const noManager = kind === "client" && !care?.managerName;
  const clear = () => setText("");
  const submit = () => {
    if (kind === "note") {
      if (text.trim() && !saveNote.isPending) saveNote.mutate();
      return;
    }
    if (kind === "consultant") care?.startTalk(text.trim(), clear);
    if (kind === "client" && !noManager) care?.openFeedback(text.trim(), clear);
  };
  const disabled = kind === "note" ? !text.trim() || saveNote.isPending : noManager;
  const label = kind === "note" ? (saveNote.isPending ? "Zapisywanie…" : "Zapisz") : kind === "consultant" ? "Zapisz rozmowę…" : "Zapisz opinię…";
  const plan = care?.nextPlan;

  return (
    <form
      data-tour="contract.care.composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="rounded-lg border border-border bg-card transition-colors focus-within:border-primary">
        <label htmlFor={ids.text} className="sr-only">
          Treść wpisu
        </label>
        <textarea
          id={ids.text}
          rows={2}
          maxLength={kind === "note" ? 20000 : 4000}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={PLACEHOLDERS[kind]}
          aria-describedby={ids.hint}
          className="block w-full resize-y bg-transparent px-3 pt-2.5 text-[13px] leading-5 text-foreground outline-hidden placeholder:text-muted-foreground"
        />
        <div className="flex flex-wrap items-center gap-1.5 px-2 pb-2 pt-1">
          {kinds.length > 1 ? (
            <div role="radiogroup" aria-label="Rodzaj wpisu" className="flex flex-wrap gap-1">
              {kinds.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={kind === value}
                  onClick={() => setPicked(value)}
                  className={cn(
                    "hit-area rounded-full border px-2.5 py-0.5 text-[12px] transition-colors",
                    kind === value
                      ? "border-primary bg-primary/10 font-medium text-foreground"
                      : "border-border text-muted-foreground hover:bg-muted",
                  )}
                >
                  {KIND_LABELS[value]}
                </button>
              ))}
            </div>
          ) : (
            <span className="px-1 text-[12px] font-medium text-muted-foreground">{KIND_LABELS[kind]}</span>
          )}
          <span className="flex-1" />
          <Button type="submit" size="sm" disabled={disabled}>
            {label}
          </Button>
        </div>
      </div>
      <div id={ids.hint} className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] text-muted-foreground">
        {kind === "note" ? (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="hit-area inline-flex items-center gap-0.5 font-medium text-foreground hover:underline"
                  aria-label={`Rodzaj notatki: ${NOTE_TYPES.find((t) => t.value === noteType)?.label}`}
                >
                  {NOTE_TYPES.find((t) => t.value === noteType)?.label}
                  <ChevronDown aria-hidden className="size-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup value={noteType} onValueChange={(value) => setNoteType(value as NoteType)}>
                  {NOTE_TYPES.map((type) => (
                    <DropdownMenuRadioItem key={type.value} value={type.value}>
                      {type.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <span aria-hidden>·</span>
            <span>Notatka będzie też widoczna w profilu kandydata.</span>
          </>
        ) : kind === "consultant" ? (
          <span>
            {plan
              ? `Zaliczy punkt planu z ${formatIsoDatePl(plan.due_on)}${plan.overdue ? " (po terminie)" : ""}; formę, ocenę i sygnały dopiszesz w oknie.`
              : "Formę, ocenę i sygnały dopiszesz w oknie rozmowy."}
          </span>
        ) : noManager ? (
          <span>Najpierw wskaż menedżera w „Co wiemy o projekcie” — opinię zbiera się od niego.</span>
        ) : (
          <span>Opinia menedżera {care?.managerName} — oceny i przedłużenie dopiszesz w oknie.</span>
        )}
      </div>
    </form>
  );
}
