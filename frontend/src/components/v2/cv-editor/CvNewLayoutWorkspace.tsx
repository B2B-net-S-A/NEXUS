"use client";

/**
 * Zakładki „Strona 1” i „Stanowiska” edytora nowego CV (wariant A, decyzja
 * Artura 22.11.2026): formularz po lewej, po prawej strona PDF z ramką
 * edytowanego bloku i chipem „Strona 1 z N · mieści się · pismo 10 pt”.
 *
 * Formularze piszą do dokumentu edytora (Word i PDF to jedna treść), więc
 * okno zostaje jedynym właścicielem zapisu, historii i QC. Podgląd odświeża
 * `useNewCvPreview` (4 s po ostatniej zmianie, w limicie trasy PDF); obie
 * zakładki dzielą jeden PDF, więc przełączanie nie wysyła nowego żądania.
 * Komponent stoi zamontowany także w „Cały tekst” (`active: false`) —
 * powrót do formularza nie pobiera PDF-u od nowa, jeśli treść się nie zmieniła.
 */

import { useState } from "react";
import type { Editor } from "@tiptap/core";
import { Loader2, RefreshCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { CvPage1Extras, CvPage1Update } from "@/lib/api";
import type { AuthenticatedDownload } from "@/lib/authenticated-files";
import type { CvLang, CvSectionKey } from "@/lib/cv-editor-blocks";
import { allRoleFields, companyName, whyPoints } from "@/lib/cv-new-layout-form";
import { pageChip } from "@/lib/cv-new-preview";
import { cn } from "@/lib/utils";

import { CvNewLayoutPage1, chosenResult } from "./CvNewLayoutPage1";
import { CvNewLayoutPositions } from "./CvNewLayoutPositions";
import { CvPdfPageView, type CvPdfPlacement } from "./CvPdfPageView";
import { useEditorDoc } from "./cv-new-layout-fields";
import { useNewCvPreview } from "./useNewCvPreview";

export type CvNewLayoutTab = "page1" | "positions";

export interface CvNewLayoutWorkspaceProps {
  editor: Editor;
  tab: CvNewLayoutTab;
  lang: CvLang;
  extras: CvPage1Extras | null | undefined;
  /** Formularz i kartka tylko do odczytu (zapis, asystent liczy, CV bez treści). */
  disabled: boolean;
  /** Zakładka na ekranie — tylko wtedy podgląd prosi serwer o PDF. */
  active: boolean;
  /** PDF nowego CV z bieżącej treści (te same nagłówki co „Jak u klienta”). */
  loadPreview: () => Promise<AuthenticatedDownload>;
  onSaveResult?: (patch: CvPage1Update) => Promise<void>;
  /** „Policz wyniki od nowa” przy najmocniejszym wyniku (tylko CV etapu). */
  onRecalcResults?: () => Promise<void>;
  onTab: (tab: CvNewLayoutTab) => void;
  onOpenText: (section: CvSectionKey) => void;
}

export function CvNewLayoutWorkspace({
  editor,
  tab,
  lang,
  extras,
  disabled,
  active,
  loadPreview,
  onSaveResult,
  onRecalcResults,
  onTab,
  onOpenText,
}: CvNewLayoutWorkspaceProps) {
  const { doc, version } = useEditorDoc(editor);
  const [selected, setSelected] = useState(0);
  const [placement, setPlacement] = useState<CvPdfPlacement | null>(null);
  const preview = useNewCvPreview({
    load: loadPreview,
    changeKey: `${version}:${JSON.stringify(extras ?? null)}`,
    active,
  });

  const roles = allRoleFields(doc);
  const role = roles[Math.min(selected, roles.length - 1)] ?? null;
  const points = whyPoints(doc).map((point) => point.text);
  const third = extras?.result_text?.trim() || chosenResult(extras)?.result.text || points[2] || "";
  const needles =
    tab === "page1"
      ? [points[0] ?? "", points[1] ?? "", third]
      : role
        ? [companyName(role.company), role.title, role.period, ...role.duties, role.technologies ?? ""]
        : [];
  const placed = placement && preview.file ? placement : null;
  const chip = placed
    ? pageChip(placed.page, placed.pages, preview.file?.info)
    : tab === "page1"
      ? "Strona 1"
      : "Strona stanowiska";

  return (
    // Układ po szerokości kolumny (`@container`), nie okna: obok stoi „Do poprawy” albo oryginał.
    <div className="@container flex min-h-0 min-w-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto bg-muted/40 @3xl:flex-row @3xl:overflow-hidden">
        <div
          className={cn(
            "min-h-0 min-w-0 flex-none bg-card @3xl:border-r @3xl:border-border",
            tab === "page1"
              ? "@3xl:w-[45%] @3xl:max-w-[30rem] @3xl:overflow-auto"
              : "flex @3xl:w-[70%] @3xl:max-w-[52rem] @3xl:overflow-hidden",
          )}
        >
          {tab === "page1" ? (
            <CvNewLayoutPage1
              editor={editor}
              extras={extras}
              disabled={disabled}
              onSaveResult={onSaveResult}
              onRecalcResults={onRecalcResults}
              onOpenPositions={() => onTab("positions")}
              onOpenText={onOpenText}
            />
          ) : (
            <CvNewLayoutPositions
              editor={editor}
              lang={lang}
              disabled={disabled}
              selected={selected}
              onSelect={setSelected}
            />
          )}
        </div>
        <section
          aria-label="Podgląd strony nowego CV"
          className="flex min-h-[28rem] min-w-0 flex-1 flex-col gap-2 p-3 @3xl:min-h-0"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span
              data-testid="cv-new-preview-chip"
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-medium",
                placed?.page === 1 && preview.file?.info.fits === false
                  ? "bg-destructive/10 text-destructive"
                  : "bg-primary/10 text-primary",
              )}
            >
              {chip}
            </span>
            {tab === "positions" && placed && !placed.outlined ? (
              <span className="text-xs text-muted-foreground">Stanowisko jest na tej stronie — bez ramki.</span>
            ) : null}
            {preview.loading ? (
              <span role="status" className="flex items-center gap-1 text-xs text-muted-foreground">
                <Loader2 aria-hidden className="h-3 w-3 animate-spin" /> Odświeżam…
              </span>
            ) : null}
          </div>
          {preview.error ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">
              <span className="min-w-0 flex-1">{preview.error}</span>
              <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={preview.retry}>
                <RefreshCcw aria-hidden className="mr-1 h-3 w-3" /> Ponów
              </Button>
            </div>
          ) : null}
          {preview.file ? (
            <CvPdfPageView
              blob={preview.file.blob}
              page={tab === "page1" ? 1 : undefined}
              needles={needles}
              onPlaced={setPlacement}
              className="flex-1"
            />
          ) : !preview.error ? (
            <p role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Przygotowuję stronę CV…
            </p>
          ) : null}
        </section>
      </div>
    </div>
  );
}
