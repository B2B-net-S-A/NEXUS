"use client";

// Podpisany przez klienta protokół albo arkusz zbiorczy wgrany ręcznie, gdy nie
// przyszedł na rozliczenia@ (roadmapa E6). NEXUS rozpoznaje go po treści
// i podpisie, tak jak plik z maila; osoby i miesiąc bierze z dokumentu.
import { Upload } from "lucide-react";
import { useRef } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useUploadSignedDocument } from "@/lib/api/client-settlements";

export function SignedDocumentUpload({ month, label }: { month: string; label: string }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useUploadSignedDocument(month);
  const { showError, showSuccess } = useToast();

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      await upload.mutateAsync(file);
      showSuccess("Podpisany dokument rozpoznany i przypisany osobom.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wgrać podpisanego dokumentu."));
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".pdf,.msg,.eml"
        className="hidden"
        aria-hidden
        tabIndex={-1}
        onChange={(event) => onFile(event.target.files?.[0])}
      />
      <Button size="sm" variant="outline" disabled={upload.isPending} onClick={() => input.current?.click()}>
        <Upload aria-hidden className="size-3.5" /> {upload.isPending ? "Sprawdzam…" : label}
      </Button>
    </>
  );
}
