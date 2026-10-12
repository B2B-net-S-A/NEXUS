"use client";

/**
 * Jeden blok ogłoszenia: podgląd (tekst albo lista), edycja w polu tekstowym
 * i „Kopiuj”. Karta w zakładce Pracuj.pl (`variant="card"`) i sekcja opisu
 * w zakładce JustJoin.IT (`variant="section"`).
 *
 * Podgląd rysuje się z napisów policzonych przez serwer jako zwykły tekst —
 * HTML z odpowiedzi idzie wyłącznie do schowka.
 *
 * Niezapisany tekst (`draft`) trzyma okno, nie blok: zakładki pokazują to samo
 * pole, a nieaktywna zakładka jest odmontowana — stan lokalny gubił poprawkę
 * przy przejściu Pracuj.pl → JustJoin.IT.
 */

import { Check, Copy, Pencil } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { RenderedKind } from "@/lib/api/jobAd";
import { cn } from "@/lib/utils";

export type AdBlockTone = "block" | "advise" | null;

export interface AdBlockProps {
  /** Klucz pola — kotwica dla „Pokaż” z panelu kontroli. */
  fieldKey: string;
  label: string | null;
  kind: RenderedKind;
  text: string;
  items: string[];
  /** Pierwsze N pozycji pochodzi z pól rekrutacji. */
  autoCount?: number;
  /** Ostatnie N pozycji to stały blok z Ustawień. */
  fixedCount?: number;
  variant?: "card" | "section";
  tone?: AdBlockTone;
  /** Tekst do edytora; `undefined` = bloku nie poprawia się w oknie. */
  editValue?: string;
  editHint?: string;
  /** Niezapisany tekst; `null` = blok nie jest w edycji. */
  draft?: string | null;
  onDraftChange?: (text: string | null) => void;
  onSave?: (text: string) => Promise<boolean>;
  saving?: boolean;
  /** Trwa przygotowanie nowej treści — poprawek nie zaczyna się ani nie zapisuje. */
  locked?: boolean;
  /** Brak = blok bez własnego „Kopiuj” (sekcja opisu JustJoin.IT). */
  onCopy?: () => void;
  copied?: boolean;
  /** Powód, dla którego kopiowanie jest wyłączone. */
  copyBlockedReason?: string | null;
}

function ItemTag({ children }: { children: string }) {
  return <span className="ml-1.5 text-[11px] text-muted-foreground">· {children}</span>;
}

export function AdBlock({
  fieldKey,
  label,
  kind,
  text,
  items,
  autoCount = 0,
  fixedCount = 0,
  variant = "card",
  tone = null,
  editValue,
  editHint,
  draft = null,
  onDraftChange,
  onSave,
  saving = false,
  locked = false,
  onCopy,
  copied = false,
  copyBlockedReason = null,
}: AdBlockProps) {
  const editable = editValue !== undefined && !!onSave && !!onDraftChange;
  const editing = editable && draft !== null;
  const empty = kind === "text" ? !text.trim() : items.length === 0;
  const name = label ?? "Wstęp";

  const ListTag = kind === "ordered" ? "ol" : "ul";
  const body = empty ? (
    <p className="text-[13px] text-muted-foreground">
      {editable ? "Brak treści — dopisz ją albo uzupełnij Profil Championa." : "Brak treści."}
    </p>
  ) : kind === "text" ? (
    <div className="space-y-2">
      {text.split("\n\n").map((paragraph, index) => (
        <p key={index} className="text-[13px] leading-[19px] text-foreground">
          {paragraph}
        </p>
      ))}
    </div>
  ) : (
    <ListTag
      className={cn(
        "space-y-0.5 pl-5 text-[13px] leading-[19px] text-foreground",
        kind === "ordered" ? "list-decimal" : "list-disc",
      )}
    >
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>
          {item}
          {index < autoCount ? <ItemTag>z rekrutacji</ItemTag> : null}
          {index >= items.length - fixedCount ? <ItemTag>stały blok</ItemTag> : null}
        </li>
      ))}
    </ListTag>
  );

  return (
    <section
      data-ad-field={fieldKey}
      aria-label={name}
      className={cn(
        "flex flex-col gap-1.5",
        variant === "card" && "rounded-lg border bg-card px-3.5 py-2.5",
        variant === "card" &&
          (tone === "block"
            ? "border-destructive/40"
            : tone === "advise"
              ? "border-warning/40"
              : copied
                ? "border-success/30"
                : "border-border"),
      )}
    >
      {label || editable || onCopy ? (
        <div className="flex min-h-7 items-center justify-between gap-2">
          {label ? (
            <h3
              className={cn(
                variant === "card"
                  ? "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                  : "text-[13px] font-semibold text-foreground",
              )}
            >
              {label}
            </h3>
          ) : (
            <span />
          )}
          <div className="flex shrink-0 items-center gap-1">
            {editable && !editing ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                aria-label={`Edytuj: ${name}`}
                disabled={locked}
                onClick={() => onDraftChange?.(editValue ?? "")}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                Edytuj
              </Button>
            ) : null}
            {onCopy ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className={cn(
                  "h-7 px-2.5",
                  copied && "border-success/30 bg-success-muted text-success-muted-foreground",
                )}
                aria-label={`${copied ? "Skopiowane" : "Kopiuj"}: ${name}`}
                title={copyBlockedReason ?? undefined}
                disabled={!!copyBlockedReason || editing || empty}
                onClick={onCopy}
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {copied ? "Skopiowane" : "Kopiuj"}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {editing ? (
        <div className="flex flex-col gap-2">
          <Textarea
            aria-label={`Treść: ${name}`}
            value={draft ?? ""}
            rows={kind === "text" ? 4 : Math.min(10, Math.max(4, items.length + 1))}
            onChange={(event) => onDraftChange?.(event.target.value)}
            className="text-[13px]"
            autoFocus
          />
          {editHint ? <p className="text-xs text-muted-foreground">{editHint}</p> : null}
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              loading={saving}
              disabled={locked}
              onClick={() => void onSave?.(draft ?? "")}
            >
              Zapisz
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={saving}
              onClick={() => onDraftChange?.(null)}
            >
              Anuluj
            </Button>
          </div>
        </div>
      ) : (
        body
      )}
    </section>
  );
}
