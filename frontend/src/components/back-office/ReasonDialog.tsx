"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";

interface ReasonDialogProps {
  title: string;
  label: string;
  confirmLabel: string;
  required?: boolean;
  busy?: boolean;
  onConfirm: (text: string) => void;
  onCancel: () => void;
}

/** Krótki tekst przed akcją: zwrot raportu, „Nie dotyczy”, „Czeka na kogoś”. */
export function ReasonDialog({
  title,
  label,
  confirmLabel,
  required = true,
  busy = false,
  onConfirm,
  onCancel,
}: ReasonDialogProps) {
  const [text, setText] = useState("");
  const missing = required && !text.trim();
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      title={title}
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>
            Anuluj
          </Button>
          <Button disabled={missing || busy} onClick={() => onConfirm(text.trim())}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <FormField label={label}>
        <Textarea rows={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
      </FormField>
    </AppModal>
  );
}
