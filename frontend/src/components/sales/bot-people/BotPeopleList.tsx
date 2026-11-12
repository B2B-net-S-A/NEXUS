"use client";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useBotPeoplePending } from "@/lib/api/sales-bot-people";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";

import { peopleCount } from "../research-import/research-import";

interface BotPeopleListProps {
  /** Wynik, którego przegląd się wczytuje. */
  opening: number | null;
  error: string | null;
  onOpen: (resultId: number) => void;
}

/**
 * Leady → „Lista z researchu”: osoby od bota czekające na przegląd, firma po firmie.
 * „Przejrzyj” otwiera ten sam ekran co plik z researchu. Z wyłączonymi zadaniami
 * bota nic nie pokazuje; awaria zapytania to komunikat, nie pusta lista.
 */
export function BotPeopleList({ opening, error, onOpen }: BotPeopleListProps) {
  const query = useBotPeoplePending();
  if (query.isPending) return null;
  if (query.isError) {
    return (
      <p role="alert" className="flex flex-wrap items-center gap-2 text-xs text-warning">
        Nie udało się wczytać osób od bota.
        <Button size="sm" variant="outline" className="h-6 px-2" onClick={() => void query.refetch()}>
          Spróbuj ponownie
        </Button>
      </p>
    );
  }
  if (!query.data.enabled) return null;
  const items = query.data.items;
  return (
    <section className="max-w-3xl space-y-2 rounded-lg border border-border bg-card p-4" data-tour="sales.bot-people.list">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold text-foreground">Osoby od bota</h2>
        <p className="text-sm text-muted-foreground">
          Decydenci, których bot znalazł na publicznych stronach firm, z linkiem do źródła. Przegląd wygląda jak przy
          pliku: nic nie trafia na mapę bez Twojej akceptacji.
        </p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Żaden wynik bota nie czeka na przegląd.</p>
      ) : (
        <Table density="compact">
          <TableHeader>
            <TableRow>
              <TableHead className={CALM_HEAD}>Firma</TableHead>
              <TableHead className={CALM_HEAD}>Do decyzji</TableHead>
              <TableHead className={CALM_HEAD}>Od bota</TableHead>
              <TableHead className={`${CALM_HEAD} text-right`}>Co zrobić</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id} className={CALM_ROW}>
                <TableCell className="py-1.5 font-medium text-foreground">{item.company.name}</TableCell>
                <TableCell className="py-1.5 text-sm">
                  {peopleCount(item.open)}
                  {item.status === "partial" && <span className={CALM_SUBLINE}>z {item.people}, część już dodana</span>}
                </TableCell>
                <TableCell className="py-1.5 text-sm tabular-nums">{formatIsoDatePl(item.created_at.slice(0, 10))}</TableCell>
                <TableCell className="py-1.5 text-right">
                  <Button
                    size="sm"
                    className="h-7 px-2.5"
                    aria-label={`Przejrzyj osoby od bota: ${item.company.name}`}
                    loading={opening === item.id}
                    disabled={opening !== null && opening !== item.id}
                    onClick={() => onOpen(item.id)}
                  >
                    Przejrzyj
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
