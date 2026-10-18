// Załącznik do wniosku urlopowego — reguły i teksty (czyste funkcje).
//
// Lustro `backend/app/services/hr/leave_proofs.py` (test
// `backend/tests/test_hr_leave_proofs.py`): PDF, JPG, PNG do 5 MB, najwyżej
// 5 plików na wniosek. Plik trafia do e-teczki osoby jako „potwierdzenie
// nieobecności”; treść widzą osoba i Kadry, przełożony tylko „Załącznik ✓” (D6).

import type { LeaveRequestRow, LeaveType } from "@/lib/api/hr-leave";
import { countPl } from "@/lib/plural-pl";

export const PROOF_MAX_BYTES = 5 * 1024 * 1024;
export const PROOF_ACCEPT = ".pdf,.jpg,.jpeg,.png";
export const PROOF_MAX_PER_REQUEST = 5;

/** Rodzaje, przy których okno podpowiada dokument (L4 przychodzi przez e-ZLA). */
export const PROOF_SUGGESTED_TYPES: readonly LeaveType[] = [
  "occasional",
  "childcare",
  "blood_donation",
];

const HINTS: Partial<Record<LeaveType, string>> = {
  occasional: "Dołącz akt ślubu, urodzenia albo zgonu — Kadry potwierdzą urlop.",
  childcare: "Dołącz oświadczenie albo akt urodzenia dziecka, jeśli Kadry go nie mają.",
  blood_donation: "Dołącz zaświadczenie z punktu krwiodawstwa.",
};

/** Podpowiedź w oknie wniosku — `null` przy rodzajach bez dokumentu. */
export function proofHint(type: LeaveType): string | null {
  return HINTS[type] ?? null;
}

/** Plik, którego serwer nie przyjmie — ten sam komunikat przed wysłaniem. */
export function proofProblem(file: File): string | null {
  const dot = file.name.lastIndexOf(".");
  const extension = dot === -1 ? "" : file.name.slice(dot).toLowerCase();
  if (!PROOF_ACCEPT.split(",").includes(extension)) {
    return "Dołącz PDF albo zdjęcie (JPG, PNG).";
  }
  if (file.size === 0) return "Plik jest pusty.";
  if (file.size > PROOF_MAX_BYTES) return "Załącznik może mieć najwyżej 5 MB.";
  return null;
}

/** „Załącznik ✓” / „2 załączniki ✓” — `null`, gdy nie ma albo patrzący nie widzi. */
export function proofSummary(row: Pick<LeaveRequestRow, "proof_count">): string | null {
  const count = row.proof_count ?? 0;
  if (count <= 0) return null;
  if (count === 1) return "Załącznik ✓";
  return `${countPl(count, "załącznik", "załączniki", "załączników")} ✓`;
}

/** Czy osoba może dołączyć kolejny plik do tego wniosku. */
export function canAttachMore(row: LeaveRequestRow): boolean {
  return Boolean(row.can_add_proof) && (row.proof_count ?? 0) < PROOF_MAX_PER_REQUEST;
}
