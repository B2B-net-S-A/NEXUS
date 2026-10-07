"use client";

/**
 * „Wróć do poprawy…” (D6, 08.10.2026) — Delivery Lead zaznacza pola, które
 * rekruter ma poprawić, i dopisuje uwagę. Do 07.10 było tylko jedno zdanie
 * uwagi: rekruter zgadywał, co poprawić, a DL po powrocie karty nie widział,
 * co się zmieniło. Lista idzie z ruchem (`fix_fields`), serwer zapisuje ją
 * jako prośbę w historii formularza screeningu, a rekruter widzi pola
 * podświetlone w formularzu.
 *
 * Potwierdzić można, gdy jest co najmniej jedno pole ALBO uwaga.
 */

import { useEffect, useId, useState } from "react";
import { Loader2, Undo2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { DlReviewFixOption } from "@/lib/api/dlReview";

const GROUP_LABEL: Record<DlReviewFixOption["group"], string> = {
  answers: "Pytania z Profilu Championa",
  terms: "Warunki",
  assessment: "Ocena rekrutera",
  rate: "Stawka",
  cv: "CV",
};
const GROUP_ORDER: DlReviewFixOption["group"][] = ["answers", "terms", "assessment", "rate", "cv"];
export const RETURN_REMARK_MAX = 2000;

export interface ReturnForFixDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateName: string;
  options: DlReviewFixOption[];
  /** Lista pól jeszcze się wczytuje (kontekst przeglądu). */
  optionsLoading?: boolean;
  busy?: boolean;
  /** Uwaga wpisana wcześniej w panelu — startowa treść pola. */
  initialRemark?: string;
  onConfirm: (input: { fields: string[]; remark: string }) => void;
}

export function canConfirmReturn(fields: string[], remark: string): boolean {
  return fields.length > 0 || remark.trim() !== "";
}

export function ReturnForFixDialog({
  open,
  onOpenChange,
  candidateName,
  options,
  optionsLoading = false,
  busy = false,
  initialRemark = "",
  onConfirm,
}: ReturnForFixDialogProps) {
  const [picked, setPicked] = useState<string[]>([]);
  const [remark, setRemark] = useState(initialRemark);
  const remarkId = useId();
  const hintId = useId();

  useEffect(() => {
    if (open) {
      setPicked([]);
      setRemark(initialRemark);
    }
  }, [open, initialRemark]);

  const toggle = (key: string) =>
    setPicked((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  const ready = canConfirmReturn(picked, remark) && !busy;
  const submit = () => {
    if (!ready) return;
    // Kolejność formularza, nie kolejność klikania.
    const order = new Map(options.map((o, i) => [o.key, i]));
    onConfirm({
      fields: [...picked].sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0)),
      remark: remark.trim(),
    });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={`Wróć do poprawy — ${candidateName}`}
      description="Zaznacz, co rekruter ma poprawić. Zobaczy te pola podświetlone w formularzu screeningu."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={!ready} aria-describedby={ready ? undefined : hintId}>
            {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Undo2 className="size-3.5" aria-hidden />}
            {picked.length > 0 ? `Wróć do poprawy (${picked.length})` : "Wróć do poprawy"}
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {optionsLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie pól formularza…
          </p>
        ) : options.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nie udało się wczytać listy pól — napisz w uwadze, co poprawić.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {GROUP_ORDER.map((group) => {
              const items = options.filter((o) => o.group === group);
              if (items.length === 0) return null;
              return (
                <fieldset key={group} className="min-w-0 space-y-1.5">
                  <legend className="text-xs font-semibold text-foreground">{GROUP_LABEL[group]}</legend>
                  {items.map((option) => (
                    <label key={option.key} className="flex cursor-pointer items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 shrink-0 accent-primary"
                        checked={picked.includes(option.key)}
                        onChange={() => toggle(option.key)}
                      />
                      <span className="min-w-0 [overflow-wrap:anywhere]">{option.label}</span>
                    </label>
                  ))}
                </fieldset>
              );
            })}
          </div>
        )}
        <div className="space-y-1">
          <label htmlFor={remarkId} className="text-xs font-medium">
            Uwaga dla rekrutera
          </label>
          <Textarea
            id={remarkId}
            rows={3}
            maxLength={RETURN_REMARK_MAX}
            value={remark}
            onChange={(event) => setRemark(event.target.value)}
          />
          <p id={hintId} className="text-[11px] text-muted-foreground">
            Zaznacz co najmniej jedno pole albo napisz uwagę. Stawki do klienta tu nie wpisuj — rekruter jej nie
            widzi.
          </p>
        </div>
      </form>
    </AppModal>
  );
}
