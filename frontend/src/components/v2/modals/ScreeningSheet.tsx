"use client";

/**
 * Arkusz „Screening kandydata" jako wysuwany panel.
 *
 * Stan, walidacja, hydratacja i zapis mieszkają od PR 6/7 programu „flow
 * w języku C2" w `@/components/v2/screening/ScreeningForm` — ten sam hook
 * i te same pola renderuje stanowisko screeningu (krok 05), które pokazuje
 * arkusz INLINE, w środku ekranu. Modal zostaje bez zmian dla ścieżek, które
 * otwierają go z tablicy: auto-prompt po ruchu na „Zweryfikowany" i na etapy
 * klienta oraz przycisk „Screening" na karcie.
 */

import { Send, Sparkles, User } from "lucide-react";

import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/v2/forms";
import {
  ScreeningFormFields,
  ScreeningNoQuestions,
  ScreeningSubmitError,
  useScreeningForm,
} from "@/components/v2/screening/ScreeningForm";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stageId: number;
  candidateName: string;
  onSubmitted?: (matchPercent: number) => void;
}

export function ScreeningSheet({
  open,
  onOpenChange,
  stageId,
  candidateName,
  onSubmitted,
}: Props) {
  const { query, questions, methods, submitMut, onSubmit, submitError } =
    useScreeningForm({
      stageId,
      enabled: open,
      onSubmitted,
      onAfterSubmit: () => onOpenChange(false),
    });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="xl">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <SheetTitle>Screening kandydata</SheetTitle>
          </div>
          <SheetDescription>
            <span className="inline-flex items-center gap-1.5">
              <User className="h-3.5 w-3.5" />
              {candidateName}
            </span>
          </SheetDescription>
        </SheetHeader>

        {query.isLoading ? (
          <SheetBody>
            <div className="py-8 text-center text-sm text-muted-foreground">
              Ładowanie pytań screeningowych…
            </div>
          </SheetBody>
        ) : questions.length === 0 ? (
          <SheetBody>
            <ScreeningNoQuestions />
          </SheetBody>
        ) : (
          <Form
            methods={methods}
            onSubmit={onSubmit}
            className="flex h-full flex-col overflow-hidden"
          >
            <SheetBody>
              <ScreeningFormFields questions={questions} methods={methods} />
              {submitError && <ScreeningSubmitError message={submitError} />}
            </SheetBody>

            <SheetFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={submitMut.isPending}
              >
                Anuluj
              </Button>
              <Button type="submit" variant="primary" loading={submitMut.isPending}>
                <Send className="h-4 w-4" />
                Zapisz screening
              </Button>
            </SheetFooter>
          </Form>
        )}
      </SheetContent>
    </Sheet>
  );
}
