"use client";

import { Download, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CALM_HEAD } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";

import { DocIcon } from "./DocIcon";
import { daysFromToday, type CurrentDocuments, type DocItem } from "./document-groups";
import { useDocumentFileActions } from "./useDocumentFileActions";

/** Termin „do …” w nazwie: forma zgodna z rodzajem dokumentu w karcie. */
interface UntilWords {
  valid: string;
  expired: string;
}

function nowMeta(item: DocItem, words: UntilWords): string {
  const parts: string[] = [];
  if (item.active) parts.push("bieżące zamówienie klienta");
  if (item.docDate) {
    const date = formatIsoDatePl(item.docDate);
    if (item.docDateUntil) {
      const past = (daysFromToday(item.docDate) ?? 0) < 0;
      parts.push(`${past ? words.expired : words.valid} ${date}`);
    } else {
      parts.push(`z ${date}`);
    }
  } else if (item.origin === "import") {
    parts.push(`bez daty w nazwie · import ${formatIsoDatePl(item.addedDay)}`);
  } else if (item.origin === "sharepoint") {
    parts.push(`bez daty w nazwie · z SharePointa ${formatIsoDatePl(item.addedDay)}`);
  } else {
    parts.push(`dodano ${formatIsoDatePl(item.addedDay)}${item.addedBy ? ` · ${item.addedBy}` : ""}`);
  }
  return parts.join(" · ");
}

interface CardProps {
  contractId: number;
  label: string;
  tag?: string | null;
  item: DocItem | null;
  /** „Pobierz umowę” — nazwa przycisku dla czytnika ekranu. */
  downloadLabel: string;
  untilWords: UntilWords;
  emptyTitle: string;
  emptyHint: string;
  onError: (message: string) => void;
}

function NowCard({
  contractId,
  label,
  tag,
  item,
  downloadLabel,
  untilWords,
  emptyTitle,
  emptyHint,
  onError,
}: CardProps) {
  const { busy, open, download } = useDocumentFileActions(contractId, onError);
  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card px-4 pb-3 pt-2.5 shadow-xs">
      <div className="flex h-7 items-center justify-between gap-2">
        <h3 className={CALM_HEAD}>
          {label}
          {tag ? <span className="ml-1.5 font-normal normal-case tracking-normal">{tag}</span> : null}
        </h3>
        {item ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="-mr-2 h-7 gap-1.5 px-2 text-[12px]"
            onClick={() => void download(item)}
            disabled={busy}
            aria-label={`${downloadLabel}: ${item.name}`}
          >
            {busy ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Download className="size-3.5" aria-hidden="true" />
            )}
            Pobierz
          </Button>
        ) : null}
      </div>
      {item ? (
        <div className="mt-1 flex min-w-0 items-start gap-2">
          <DocIcon group={item.group} className="mt-0.5" />
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => void open(item)}
              disabled={busy}
              title={item.name}
              className="block max-w-full text-left text-[13.5px] font-medium leading-5 text-foreground hover:text-primary hover:underline disabled:opacity-60"
            >
              <span className="line-clamp-2 break-words">{item.name}</span>
            </button>
            <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{nowMeta(item, untilWords)}</p>
          </div>
        </div>
      ) : (
        <div className="mt-1">
          <p className="text-[13.5px] font-medium leading-5 text-foreground">{emptyTitle}</p>
          <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{emptyHint}</p>
        </div>
      )}
    </section>
  );
}

interface Props {
  contractId: number;
  current: CurrentDocuments;
  /** Numer bieżącej umowy (`current_contract_number` z folderów). */
  contractNumber: string | null;
  readOnly: boolean;
  onError: (message: string) => void;
}

/**
 * Trzy karty „Obowiązuje teraz”: umowa, ostatni aneks i najnowsze
 * zamówienie spośród plików poza folderami (folder to archiwum), z datą
 * z nazwy pliku i „Pobierz”. Pusta karta mówi, czego brakuje.
 */
export function DocumentsNowCards({ contractId, current, contractNumber, readOnly, onError }: Props) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <NowCard
        contractId={contractId}
        label="Umowa"
        tag={contractNumber ? `nr ${contractNumber}` : null}
        item={current.contract}
        downloadLabel="Pobierz umowę"
        untilWords={{ valid: "ważna do", expired: "wygasła" }}
        emptyTitle="Brak pliku umowy"
        emptyHint={
          readOnly
            ? "W dokumentach kontraktu nie ma podpisanej umowy."
            : "Dodaj podpisaną umowę — przyda się przy aneksach i zakończeniu."
        }
        onError={onError}
      />
      <NowCard
        contractId={contractId}
        label="Ostatni aneks"
        item={current.annex}
        downloadLabel="Pobierz ostatni aneks"
        untilWords={{ valid: "ważny do", expired: "wygasł" }}
        emptyTitle="Brak plików aneksów"
        emptyHint="Aneksy zapisane w kontrakcie są w zakładce Aneksy."
        onError={onError}
      />
      <NowCard
        contractId={contractId}
        label="Najnowsze zamówienie"
        item={current.order}
        downloadLabel="Pobierz najnowsze zamówienie"
        untilWords={{ valid: "ważne do", expired: "wygasło" }}
        emptyTitle="Brak pliku zamówienia"
        emptyHint={readOnly ? "PDF zamówienia klienta nie jest dodany." : "Dodaj PDF zamówienia klienta."}
        onError={onError}
      />
    </div>
  );
}
