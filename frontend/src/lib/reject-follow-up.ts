/**
 * Odrzucenie albo rezygnacja z panelu osoby (13.10.2026): okno zapowiada,
 * kogo panel pokaże po potwierdzeniu, a `onMoved` przychodzi dopiero po
 * ruchu potwierdzonym przez serwer. Odmowa serwera nie woła niczego.
 * Zasady: docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md.
 */
export interface RejectFollowUp {
  /** Kolumna Tablicy zamykanej osoby — do linii „kogo zamykasz” w oknie. */
  stageLabel: string | null;
  /** Następna osoba w kolejności „›”; `null` — to ostatnia osoba. */
  next: { name: string; stageLabel: string } | null;
  onMoved: (info: { reasonLabel: string | null }) => void;
}
