// Plik w kwarantannie tożsamości i jego kopia na liście plików profilu.
// Decyzja parsera bywa fałszywym alarmem, a po #3060 osoba może przez to zostać
// bez bieżącego CV, więc wiersz mówi, co się stało i kto może to zwolnić.

import { Badge } from "@/components/ui/badge";
import { formatFileDate } from "@/lib/candidate-files";

/** Odpowiedź `GET /api/candidates/{id}/identity-quarantine`. */
export interface DocumentQuarantine {
  document_id: number;
  state: "quarantined" | "copy";
  source_document_id: number;
  source_filename: string;
  source_removed: boolean;
  manual: boolean;
  reviewed_at: string;
}

/**
 * Czy przycisk stoi przy tym wierszu. Przy oryginale, bo zwolnienie oddaje od
 * razu wszystkie kopie; przy kopii tylko, gdy oryginał usunięto z profilu i nie
 * ma go na liście.
 */
export function quarantineReleaseOf(entry: DocumentQuarantine): boolean {
  return entry.state === "quarantined" || entry.source_removed;
}

export function fileQuarantineBadge(entry: DocumentQuarantine) {
  const since = [
    `W kwarantannie od ${formatFileDate(entry.reviewed_at) ?? "—"}`,
    entry.manual ? "oznaczone ręcznie" : "decyzja odczytu CV",
  ].join(" · ");
  return (
    <Badge size="sm" variant="warning" title={since}>
      {entry.state === "quarantined" ? "kwarantanna" : "kopia pliku z kwarantanny"}
    </Badge>
  );
}

export function FileQuarantineNotice({
  entry,
  canRelease,
}: {
  entry: DocumentQuarantine;
  canRelease: boolean;
}) {
  const who = canRelease ? null : " Zwolnić może administrator albo Head of Recruitment.";
  return (
    <p className="mt-0.5 text-xs text-warning-muted-foreground">
      {entry.state === "quarantined"
        ? `${entry.manual ? "Plik oznaczono ręcznie jako CV innej osoby." : "W pliku odczytano inną osobę niż w profilu."} Nie zasila profilu i nie jest bieżącym CV.`
        : entry.source_removed
          ? `Ten sam plik co „${entry.source_filename}”, usunięty z profilu i w kwarantannie. Nie jest bieżącym CV, dopóki tamten plik nie zostanie zwolniony.`
          : `Ten sam plik co „${entry.source_filename}”. Nie jest bieżącym CV, dopóki tamten plik nie zostanie zwolniony.`}
      {who}
    </p>
  );
}
