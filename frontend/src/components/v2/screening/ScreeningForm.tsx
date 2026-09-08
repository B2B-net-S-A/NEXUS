"use client";

/**
 * Wspólne wnętrze arkusza screeningu Championa — stan, walidacja, zapis
 * i pola — wydzielone z `ScreeningSheet.tsx` (krok 05 programu „flow
 * w języku C2", PR 6/7).
 *
 * Powód wydzielenia: makieta kroku 05 stawia arkusz W ŚRODKU stanowiska
 * pracy, nie w wysuwanym panelu, a `ScreeningSheet` jest modalem (Radix
 * `Sheet`) — jego treść nie da się wyrenderować inline bez wycięcia
 * `SheetBody`/`SheetFooter`. Zamiast forka (dwie kopie schematu zod, dwie
 * hydratacje, dwa payloady zapisu — rozjadą się przy pierwszej zmianie pytań)
 * modal i stanowisko renderują TE SAME pola i wołają TEN SAM hook.
 *
 * Zachowanie modala jest bit w bit takie samo jak przed wydzieleniem: te same
 * klucze cache, ta sama walidacja („odpowiedź wymagana" na każdym pytaniu),
 * ten sam trwały komunikat błędu nad stopką, ten sam payload `POST
 * /api/pipeline/stages/{id}/screening`.
 */

import { useEffect, useState } from "react";
import { useForm, type UseFormReturn } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import {
  extractErrorMsg,
  screeningApi,
  type ScreeningAnswerItem,
  type ScreeningAnswers,
  type ScreeningQuestion,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { FormField, TextareaField } from "@/components/v2/forms";

export const FIT_OPTIONS = [
  {
    value: "fit" as const,
    label: "Pasuje",
    description: "Spełnia wszystkie kluczowe kryteria.",
  },
  {
    value: "uncertain" as const,
    label: "Niepewne",
    description: "Warto dopytać lub zostawić do decyzji klienta.",
  },
  {
    value: "miss" as const,
    label: "Nie pasuje",
    description: "Nie rekomenduję — deal-breaker lub brak kompetencji.",
  },
];

export interface ScreeningFormValues {
  answers: Record<string, { response: string; deal_breaker_hit: boolean }>;
  overall_fit: "fit" | "uncertain" | "miss";
  notes: string;
}

function makeSchema(questions: ScreeningQuestion[]) {
  const answersShape = Object.fromEntries(
    questions.map((q) => [
      q.id,
      z.object({
        response: z.string().min(1, "Odpowiedź jest wymagana"),
        deal_breaker_hit: z.boolean(),
      }),
    ]),
  );
  return z.object({
    answers: z.object(answersShape),
    overall_fit: z.enum(["fit", "uncertain", "miss"]),
    notes: z.string().optional().default(""),
  });
}

/**
 * Pytania Championa z odpowiedzi `GET /api/pipeline/stages/{id}/screening`.
 *
 * `StageScreeningResponse.champion_profile` jest typowane jako
 * `ChampionProfile | Record<string, never>`, więc każdy czytelnik robił
 * własne rzutowanie. Jedno miejsce zamiast czterech.
 */
export function championScreeningQuestions(
  championProfile: unknown,
): ScreeningQuestion[] {
  const questions = (championProfile as { screening_questions?: unknown } | null)
    ?.screening_questions;
  return Array.isArray(questions) ? (questions as ScreeningQuestion[]) : [];
}

export interface UseScreeningFormOptions {
  stageId: number;
  /** Arkusz nie pobiera danych, dopóki nie jest widoczny (modal zamknięty). */
  enabled?: boolean;
  onSubmitted?: (matchPercent: number) => void;
  /** Po udanym zapisie — modal się zamyka, stanowisko zostaje otwarte. */
  onAfterSubmit?: () => void;
}

export function useScreeningForm({
  stageId,
  enabled = true,
  onSubmitted,
  onAfterSubmit,
}: UseScreeningFormOptions) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["screening-v2", stageId],
    queryFn: () => screeningApi.getForStage(stageId).then((r) => r.data),
    enabled,
  });
  const data = query.data;

  const questions = championScreeningQuestions(data?.champion_profile);
  const existing = data?.screening_answers;

  const methods = useForm<ScreeningFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(makeSchema(questions)) as any,
    defaultValues: { answers: {}, overall_fit: "uncertain", notes: "" },
  });

  // Hydratacja formularza po dojściu danych (i po zmianie etapu — inne
  // pytania, inne odpowiedzi).
  useEffect(() => {
    if (!data) return;
    const entries: Record<
      string,
      { response: string; deal_breaker_hit: boolean }
    > = {};
    for (const q of questions) {
      const existingAnswer = existing?.answers.find(
        (a) => a.question_id === q.id,
      );
      entries[q.id] = {
        response: existingAnswer?.response ?? "",
        deal_breaker_hit: existingAnswer?.deal_breaker_hit ?? false,
      };
    }
    methods.reset({
      answers: entries,
      overall_fit: existing?.overall_fit ?? "uncertain",
      notes: existing?.notes ?? "",
    });
  }, [data, existing, questions.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Jedyną ścieżką wyjścia tej mutacji był `onSuccess`, więc odrzucony zapis
  // (403 — bramka POST-a jest węższa niż bramka GET-a, albo 422 z walidacji)
  // wyglądał identycznie jak kliknięcie, które nie zadziałało. Screening
  // niesie flagi `deal_breaker_hit`, które wykluczają kandydata z shortlisty —
  // cicho nieudany zapis kosztuje kandydata.
  const submitMut = useMutation({
    mutationFn: (payload: ScreeningAnswers) =>
      screeningApi.submit(stageId, payload),
    onSuccess: (r) => {
      setSubmitError(null);
      queryClient.invalidateQueries({ queryKey: ["screening-v2", stageId] });
      queryClient.invalidateQueries({
        queryKey: ["pipeline-stage-screening", stageId],
      });
      queryClient.invalidateQueries({ queryKey: ["candidate"] });
      onSubmitted?.(r.data.match_percent);
      onAfterSubmit?.();
    },
    onError: (e) => {
      // Toast znika, a arkusz zostaje otwarty z niezapisanymi danymi — dlatego
      // powód porażki zostaje też na stałe nad stopką.
      const msg = extractErrorMsg(e);
      setSubmitError(msg);
      showError(msg);
    },
  });

  const onSubmit = (values: ScreeningFormValues) => {
    setSubmitError(null);
    const answers: ScreeningAnswerItem[] = questions.map((q) => ({
      question_id: q.id,
      response: values.answers[q.id]?.response ?? "",
      deal_breaker_hit: !!values.answers[q.id]?.deal_breaker_hit,
    }));
    submitMut.mutate({
      answers,
      overall_fit: values.overall_fit,
      notes: values.notes ?? "",
    });
  };

  return {
    query,
    data,
    questions,
    existing,
    methods,
    submitMut,
    onSubmit,
    submitError,
  };
}

/** Pola arkusza — pytania, ocena ogólna i notatki. Bez opakowania `<form>`. */
export function ScreeningFormFields({
  questions,
  methods,
}: {
  questions: ScreeningQuestion[];
  methods: UseFormReturn<ScreeningFormValues>;
}) {
  return (
    <div className="space-y-5">
      {questions.map((q, i) => {
        const dealBreakerName = `answers.${q.id}.deal_breaker_hit` as const;
        return (
          <div
            key={q.id}
            className="space-y-3 rounded-lg border border-border bg-background/40 p-4"
          >
            <div className="flex items-start gap-2">
              <Badge variant="soft" size="sm" className="shrink-0 font-mono">
                Q{i + 1}
              </Badge>
              <div className="flex-1">
                <p className="text-sm font-semibold text-foreground">
                  {q.question}
                </p>
                {q.ideal_answer && (
                  <p className="mt-1 text-xs italic text-muted-foreground">
                    Idealnie: {q.ideal_answer}
                  </p>
                )}
                {q.deal_breaker && (
                  <p className="mt-1 text-xs text-primary">
                    Deal-breaker: {q.deal_breaker}
                  </p>
                )}
              </div>
            </div>
            <FormField name={`answers.${q.id}.response`} label="Odpowiedź">
              <TextareaField
                name={`answers.${q.id}.response`}
                rows={3}
                placeholder="Jak odpowiedział kandydat?"
              />
            </FormField>
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs">
              <Checkbox
                checked={!!methods.watch(dealBreakerName)}
                onCheckedChange={(v) =>
                  methods.setValue(dealBreakerName, !!v, {
                    shouldValidate: true,
                  })
                }
              />
              <span>Odpowiedź narusza deal-breaker</span>
            </label>
          </div>
        );
      })}

      <div className="pt-2">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Ogólna ocena dopasowania
        </h3>
        <RadioGroup
          value={methods.watch("overall_fit")}
          onValueChange={(v) =>
            methods.setValue(
              "overall_fit",
              v as ScreeningFormValues["overall_fit"],
            )
          }
        >
          {FIT_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className="flex cursor-pointer items-start gap-2 rounded-md p-2 hover:bg-primary/10"
            >
              <RadioGroupItem value={opt.value} className="mt-0.5" />
              <div>
                <div className="text-sm font-medium text-foreground">
                  {opt.label}
                </div>
                <div className="text-xs text-muted-foreground">
                  {opt.description}
                </div>
              </div>
            </label>
          ))}
        </RadioGroup>
      </div>

      <FormField
        name="notes"
        label="Notatki rekrutera"
        description="Kontekst, follow-upy, deal-breakers — widoczne w share portalu klienta."
      >
        <TextareaField
          name="notes"
          rows={4}
          placeholder="Np. kandydat był gotowy zacząć w 2 tyg, rozmowa po angielsku…"
        />
      </FormField>
    </div>
  );
}

/** Trwały komunikat porażki zapisu — nad stopką, obok znikającego toastu. */
export function ScreeningSubmitError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="mt-4 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        Nie udało się zapisać screeningu: {message} Odpowiedzi są nadal
        w formularzu — popraw przyczynę i spróbuj ponownie.
      </span>
    </div>
  );
}

/** Rekrutacja bez pytań Championa — to nie jest awaria ani brak uprawnień. */
export function ScreeningNoQuestions() {
  return (
    <div className="py-8 text-center text-sm text-muted-foreground">
      <AlertTriangle className="mx-auto mb-2 h-10 w-10 opacity-40" />
      Ta rekrutacja nie ma skonfigurowanego Champion Profile — poproś TAC
      o uzupełnienie pytań screeningowych.
    </div>
  );
}
