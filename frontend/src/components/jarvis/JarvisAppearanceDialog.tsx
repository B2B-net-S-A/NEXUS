"use client";

/**
 * Okno „Wygląd asystenta”.
 *
 * Treść przewija się w `DialogBody` (flex-1 + min-h-0), a „Anuluj”/„Zapisz” stoją
 * w STAŁEJ stopce. Zgłoszenie 21.09: na ekranie 768 px okno (max 90vh,
 * overflow-hidden) ucinało przycisk „Zapisz” pod dolną krawędzią, a wewnętrzna
 * warstwa bez ograniczonej wysokości nie dawała się przewinąć — imię dało się
 * wpisać, ale nie zapisać. Na dużym monitorze wszystko się mieściło.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { JarvisPrefs, JarvisPrefsResponse } from "@/lib/jarvis/types";
import { JarvisAppearanceForm } from "./JarvisAppearanceForm";

const FORM_ID = "jarvis-appearance-form";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  prefs: JarvisPrefsResponse;
  saving?: boolean;
  error?: string | null;
  onSave: (next: Partial<JarvisPrefs>) => void;
  onResetTips?: () => void;
}

export function JarvisAppearanceDialog({ open, onOpenChange, prefs, saving = false, error, onSave, onResetTips }: Props) {
  const [valid, setValid] = useState(true);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Ustawienia asystenta</DialogTitle>
        </DialogHeader>
        <DialogBody>
          {open && (
            <JarvisAppearanceForm
              formId={FORM_ID}
              hideActions
              prefs={prefs}
              saving={saving}
              error={error}
              onSave={onSave}
              onCancel={() => onOpenChange(false)}
              onValidityChange={setValid}
              onResetTips={onResetTips}
            />
          )}
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button type="submit" form={FORM_ID} loading={saving} disabled={!valid}>
            Zapisz
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
