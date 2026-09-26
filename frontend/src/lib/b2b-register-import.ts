// Etykiety raportu importu rejestru umów z Excela (Ustawienia → Umowy i stawki).
// Kody przychodzą z `backend/app/services/b2b_register_import/service.py`.
import type {
  B2BRegisterImportCounters,
  B2BRegisterImportMode,
} from "@/lib/api";

/** Liczby na górze raportu — w tej kolejności. */
export const REGISTER_IMPORT_COUNTER_LABELS: readonly {
  key: keyof B2BRegisterImportCounters;
  label: string;
}[] = [
  { key: "contract_rows", label: "Wiersze umów" },
  { key: "created", label: "Nowe" },
  { key: "updated", label: "Zaktualizowane" },
  { key: "unchanged", label: "Bez zmian" },
  { key: "skipped", label: "Pominięte" },
  { key: "cancelled", label: "Nie doszły do skutku" },
  { key: "closed", label: "Zakończone" },
  { key: "likely_ended", label: "Prawdopodobnie zakończone" },
  { key: "generator_matches", label: "Zgodne z NEXUSEM" },
  { key: "generator_discrepancies", label: "Rozbieżne z NEXUSEM" },
  { key: "number_collisions", label: "Kolizje numerów" },
  { key: "missing_marked", label: "Brak w pliku" },
  { key: "candidates_matched", label: "Kandydaci dopasowani" },
  { key: "clients_unknown_rows", label: "Wiersze z nieznanym klientem" },
  { key: "annex_matched", label: "„Bez działalności” dopasowane" },
  { key: "annex_unmatched", label: "„Bez działalności” bez dopasowania" },
  { key: "generator_annex_flagged", label: "Aneks do zrobienia (umowy z NEXUSA)" },
  { key: "annex_cleared", label: "Zdjęte z „Bez działalności”" },
  { key: "signing_dates_unparsed", label: "Nieczytelne daty podpisania" },
];

const MODE_LABELS: Record<B2BRegisterImportMode, string> = {
  dry_run: "Podgląd",
  applied: "Zastosowany",
  rolled_back: "Cofnięty",
};

export function registerImportModeLabel(mode: B2BRegisterImportMode): string {
  return MODE_LABELS[mode] ?? mode;
}

const REASON_LABELS: Record<string, string> = {
  duplicate_in_file: "ten sam numer w kilku wierszach pliku",
  deleted_in_nexus: "numer był wydany i usunięty w NEXUSIE",
  number_taken: "numer zajęty w NEXUSIE przez inną umowę",
  legend: "legenda pod tabelą",
  no_name_no_number: "brak nazwiska i numeru",
  no_name: "brak nazwiska",
  ambiguous: "kilka pasujących umów",
  not_found: "brak umowy tej osoby w arkuszu „Umowy B2B”",
};

export function registerImportReasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}
