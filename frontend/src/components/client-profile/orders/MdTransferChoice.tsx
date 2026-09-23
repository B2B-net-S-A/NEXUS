"use client";

import type { MdTransferMethod } from "@/lib/api/orderGroups";
import {
  MD_TRANSFER_METHOD_LABELS,
  type TransferPreview,
} from "@/lib/order-takeover";
import { formatPLN } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

interface Props {
  preview: TransferPreview | null;
  /** Kto przejmuje — w komunikacie o puli w MD. */
  incomingName: string;
  departingName: string;
  value: MdTransferMethod | null;
  onChange: (method: MdTransferMethod) => void;
  /** Nazwa grupy radiowej — unikalna w obrębie okna. */
  name: string;
}

/** Przejęcie pozostałych MD (B1): pula w MD → komunikat 1:1 bez przelicznika;
 *  pula w kwocie → wyliczenie kwoty i dwie opcje z gotowym wynikiem, żadna
 *  nie jest zaznaczona z góry. */
export function MdTransferChoice({
  preview,
  incomingName,
  departingName,
  value,
  onChange,
  name,
}: Props) {
  if (!preview) return null;
  if (preview.unit === "md") {
    return (
      <p
        role="status"
        className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground"
      >
        Zamówienie ma pulę w MD — {incomingName || "nowa osoba"} przejmuje{" "}
        <strong>{formatMd(preview.remaining)} MD</strong> 1:1.
      </p>
    );
  }
  return (
    <fieldset className="flex flex-col gap-2 rounded-md border border-border px-3 py-3">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Przelicz pozostałe MD *
      </legend>
      <p className="text-sm text-muted-foreground">
        Pozostało {formatMd(preview.remaining)} MD × stawka {departingName || "osoby odchodzącej"}{" "}
        ={" "}
        <strong className="text-foreground">
          {preview.amount == null ? "—" : formatPLN(preview.amount)}
        </strong>
      </p>
      {preview.options.map((option) => (
        <label
          key={option.method}
          className="flex cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2"
        >
          <input
            type="radio"
            name={name}
            value={option.method}
            checked={value === option.method}
            onChange={() => onChange(option.method)}
          />
          <span className="flex-1 text-sm text-foreground">
            {MD_TRANSFER_METHOD_LABELS[option.method]}
          </span>
          <span className="text-sm font-semibold text-foreground">
            {option.md == null ? "podaj stawkę" : `${formatMd(option.md)} MD`}
          </span>
        </label>
      ))}
      {value == null ? (
        <p className="text-xs text-muted-foreground">
          Wybierz sposób przeliczenia — bez tego zapis jest nieaktywny.
        </p>
      ) : null}
    </fieldset>
  );
}
