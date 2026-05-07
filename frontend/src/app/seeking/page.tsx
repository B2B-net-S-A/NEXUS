import { redirect } from "next/navigation";

// Convenience alias /seeking → /sourcing/seeking-contractors (P3-C audit-2026-05-07).
// Niektóre usery linkują/zapamiętują skrócony URL; zamiast 404 redirectujemy.
export default function SeekingAlias() {
  redirect("/sourcing/seeking-contractors");
}
