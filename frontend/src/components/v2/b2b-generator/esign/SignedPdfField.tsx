"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signedPdfProblem } from "@/lib/api/b2bEsign";

/** Pole na podpisany PDF — wspólne dla kontraktora i reprezentanta firmy. */
export function SignedPdfField({
  id,
  label,
  file,
  onFile,
  disabled = false,
}: {
  id: string;
  label: string;
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
}) {
  const problem = file ? signedPdfProblem(file) : null;
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="file"
        accept=".pdf,application/pdf"
        disabled={disabled}
        aria-invalid={problem ? true : undefined}
        aria-describedby={`${id}-hint`}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        PDF podpisany podpisem kwalifikowanym, do 20 MB. Nie zmieniaj treści i nie
        zapisuj pliku „jako nowy PDF”.
      </p>
      {problem ? (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
