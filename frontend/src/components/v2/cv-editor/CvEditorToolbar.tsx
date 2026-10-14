"use client";

/**
 * Pasek narzędzi edytora CV. Przyciski wołają polecenia z
 * `lib/cv-editor-blocks.ts`; polecenie, które nie ma zastosowania w miejscu
 * kursora, jest wyłączone, a nie ukryte.
 *
 * Edytor CV 3 (PR 3, 14.10.2026, „bardzo prosto”): w pasku zostaje to, czego
 * używa się co chwilę — cofnij, pogrubienie, lista, wyrównanie i „Pogrub
 * wymagania (N)”. Reszta (dodawanie bloków, typ akapitu, stanowisko pod
 * kursorem, AI na zaznaczeniu, wyrównanie całego CV oraz pozycje okna:
 * polecenie, historia, pliki) jest w jednym menu „Więcej”.
 */

import { Fragment, useRef, type ReactNode } from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  AlignJustify,
  AlignLeft,
  ArrowDown,
  ArrowUp,
  Bold,
  ChevronDown,
  Copy,
  List,
  Plus,
  Redo2,
  Sparkles,
  Trash2,
  Undo2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { CvSelectionAiController } from "@/components/v2/cv-editor/useCvSelectionAi";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { CV_AI_ACTIONS } from "@/lib/api/cvEditorAi";
import {
  CV_DEFAULT_ALIGN,
  cvAlignAt,
  setCvAlign,
  setCvAlignEverywhere,
  type CvAlign,
} from "@/lib/cv-editor-align";
import {
  CV_BLOCK_MARKERS,
  CV_SECTION_KEYS,
  blockKindOf,
  cvContext,
  deleteRole,
  duplicateRole,
  insertBullet,
  insertRole,
  insertRow,
  moveRole,
  runCvCommand,
  setBlockKind,
  type CvBlockKind,
  type CvCommand,
  type CvLang,
} from "@/lib/cv-editor-blocks";
import { cn } from "@/lib/utils";

const KIND_LABELS: Record<CvBlockKind, string> = {
  text: "Zwykły tekst",
  role: "Stanowisko",
  employer: "Firma",
  duties_label: "Etykieta obowiązków",
  technologies: "Technologie",
  why_points: "Dlaczego ten kandydat",
  education: "Edukacja",
  skills: "Umiejętności",
  certifications: "Certyfikaty",
  languages: "Języki",
  experience: "Doświadczenie",
};

function Divider() {
  return <span aria-hidden className="mx-1 h-5 w-px flex-none bg-border" />;
}

export interface CvEditorToolbarProps {
  editor: Editor;
  /** Język CV — etykiety szablonu we wstawianych blokach. */
  language: CvLang;
  /** Domyślne wyrównanie treści CV (reguła klienta); akapit bez jawnego idzie za nim. */
  defaultAlign?: CvAlign;
  disabled?: boolean;
  /**
   * „AI na zaznaczeniu”: drugie wejście obok dymka nad tekstem — dla klawiatury
   * i telefonu, gdzie dymek bywa niewygodny. Brak = edytor bez AI.
   */
  ai?: CvSelectionAiController;
  /**
   * „Pogrub wymagania (N)”: liczba z QC (`null` — QC jeszcze liczy albo nie
   * odpowiada). Brak = edytor bez QC (wynik generatora bez etapu).
   */
  boldRequirements?: { count: number | null; disabled: boolean; onRun: () => void };
  /** Pozycje „Więcej” spoza treści (polecenie, historia, pliki); grupy rozdziela linia. */
  moreGroups?: readonly (readonly CvEditorMoreItem[])[];
}

export interface CvEditorMoreItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  title?: string;
  icon?: ReactNode;
}

const NO_GROUPS: readonly (readonly CvEditorMoreItem[])[] = [];

export function CvEditorToolbar({
  editor,
  language,
  defaultAlign = CV_DEFAULT_ALIGN,
  disabled = false,
  ai,
  boldRequirements,
  moreGroups = NO_GROUPS,
}: CvEditorToolbarProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const view = useEditorState({
    editor,
    selector: ({ editor: current }) => {
      const context = cvContext(current.state);
      const kind = blockKindOf(context.block);
      return {
        canUndo: current.can().undo(),
        canRedo: current.can().redo(),
        bold: current.isActive("bold"),
        list: current.isActive("bulletList"),
        align: cvAlignAt(current.state, defaultAlign),
        kind,
        kindLocked: context.locked || context.inList || kind === null,
        // Akapit ze znacznikiem struktury w liście straciłby go — najpierw „Zwykły tekst”.
        listLocked: context.locked || (kind !== null && kind !== "text"),
        canBullet: insertBullet(language)(current.state) !== null,
        role: context.role?.title ?? null,
        canMoveUp: context.canMoveUp,
        canMoveDown: context.canMoveDown,
      };
    },
  });

  const kindLabel = view.kind ? KIND_LABELS[view.kind] : "—";
  const run = (command: CvCommand) => runCvCommand(editor, command);
  // Menu po zamknięciu oddaje fokus przyciskowi, a polecenie właśnie zaznaczyło
  // pole do wypełnienia — pisanie ma je zastąpić, więc fokus wraca do tekstu.
  const backToText = (event: Event) => {
    event.preventDefault();
    // Menu potrafi domknąć się już po zamknięciu okna — edytora wtedy nie ma.
    if (!editor.isDestroyed) editor.view.focus();
  };
  // Pozycja okna z „Więcej” (polecenie, historia, pliki) otwiera własne pole
  // albo panel — fokus nie wraca do kartki (inaczej tekst polecenia wpisywał
  // się w CV), a sama akcja rusza po zamknięciu menu: otwarte menu trzyma
  // fokus w sobie i zabrałoby go polu z `autoFocus`.
  const keepFocus = useRef(false);
  const onMoreClosed = (event: Event) => {
    if (keepFocus.current) {
      keepFocus.current = false;
      event.preventDefault();
      return;
    }
    backToText(event);
  };
  const removeRole = async () => {
    const confirmed = await askConfirm({
      title: "Usunąć stanowisko?",
      description: `„${view.role ?? ""}” zniknie z CV razem z obowiązkami i technologiami. Przywrócisz je przyciskiem „Cofnij”.`,
      confirmLabel: "Usuń stanowisko",
      variant: "destructive",
    });
    if (confirmed) run(deleteRole);
  };

  return (
    <div
      role="toolbar"
      aria-label="Narzędzia edytora CV"
      // `basis-64`: na telefonie przełączniki widoku schodzą do drugiego wiersza,
      // zamiast zostawiać paskowi kilkadziesiąt pikseli do przewijania.
      className="relative flex min-w-0 flex-1 basis-64 items-center gap-0.5 overflow-x-auto"
    >
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Cofnij"
        disabled={disabled || !view.canUndo}
        onClick={() => editor.chain().focus().undo().run()}
      >
        <Undo2 aria-hidden className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Ponów"
        disabled={disabled || !view.canRedo}
        onClick={() => editor.chain().focus().redo().run()}
      >
        <Redo2 aria-hidden className="h-4 w-4" />
      </Button>
      <Divider />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Pogrubienie"
        aria-pressed={view.bold}
        disabled={disabled}
        className={cn(view.bold && "bg-muted text-primary")}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <Bold aria-hidden className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Lista punktowana"
        aria-pressed={view.list}
        disabled={disabled || view.listLocked}
        className={cn(view.list && "bg-muted text-primary")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        <List aria-hidden className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Do lewej"
        aria-pressed={view.align === "left"}
        disabled={disabled || view.align === null}
        className={cn(view.align === "left" && "bg-muted text-primary")}
        onClick={() => run(setCvAlign("left"))}
      >
        <AlignLeft aria-hidden className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Wyjustuj"
        aria-pressed={view.align === "justify"}
        disabled={disabled || view.align === null}
        className={cn(view.align === "justify" && "bg-muted text-primary")}
        onClick={() => run(setCvAlign("justify"))}
      >
        <AlignJustify aria-hidden className="h-4 w-4" />
      </Button>
      <Divider />

      {boldRequirements ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="flex-none gap-1 px-2"
          aria-label={
            boldRequirements.count === null
              ? "Pogrub wymagania"
              : `Pogrub wymagania (${boldRequirements.count})`
          }
          disabled={disabled || boldRequirements.disabled || !boldRequirements.count}
          title={
            boldRequirements.count === 0
              ? "Wymagania klienta są już pogrubione."
              : boldRequirements.count === null
                ? "QC jeszcze sprawdza CV — liczba pojawi się za chwilę."
                : "Pogrubia w całym CV wymagania klienta, których QC nie widzi pogrubionych. Cofniesz to przyciskiem „Cofnij”."
          }
          onClick={boldRequirements.onRun}
        >
          <Bold aria-hidden className="h-4 w-4 text-primary" />
          Pogrub wymagania
          {boldRequirements.count !== null ? (
            <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums">{boldRequirements.count}</span>
          ) : null}
        </Button>
      ) : null}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          {/* Włączone także przy wyłączonym pasku: pliki i historia działają w „Jak u klienta”. */}
          <Button type="button" variant="ghost" size="sm" className="flex-none gap-1 px-2">
            Więcej
            <ChevronDown aria-hidden className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64" onCloseAutoFocus={onMoreClosed}>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger disabled={disabled} className="gap-2">
              <Plus aria-hidden className="h-4 w-4" />
              Dodaj
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem onSelect={() => run(insertRole(language))}>Stanowisko</DropdownMenuItem>
              <DropdownMenuItem disabled={!view.canBullet} onSelect={() => run(insertBullet(language))}>
                Punkt
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => run(insertRow("education", language))}>
                Wiersz edukacji
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => run(insertRow("skills", language))}>
                Grupa umiejętności
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => run(insertRow("certifications", language))}>
                Certyfikat
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => run(insertRow("languages", language))}>Język</DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger
              disabled={disabled || view.kindLocked}
              aria-label={`Typ akapitu: ${kindLabel}`}
              className="gap-1"
            >
              <span className="text-muted-foreground">Typ akapitu:</span>
              <span className="truncate">{kindLabel}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuRadioGroup
                value={view.kind ?? ""}
                onValueChange={(value) => run(setBlockKind(value as CvBlockKind, language))}
              >
                {(["text", ...CV_BLOCK_MARKERS] as const).map((kind) => (
                  <DropdownMenuRadioItem key={kind} value={kind}>
                    {KIND_LABELS[kind]}
                  </DropdownMenuRadioItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Nagłówek sekcji</DropdownMenuLabel>
                {CV_SECTION_KEYS.map((kind) => (
                  <DropdownMenuRadioItem key={kind} value={kind}>
                    {KIND_LABELS[kind]}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          {view.role ? (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger disabled={disabled} className="gap-1">
                <span className="truncate">
                  <span className="text-muted-foreground">Stanowisko:</span> {view.role}
                </span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuItem disabled={!view.canMoveUp} onSelect={() => run(moveRole(-1))}>
                  <ArrowUp aria-hidden className="h-4 w-4" />
                  Przenieś stanowisko wyżej
                </DropdownMenuItem>
                <DropdownMenuItem disabled={!view.canMoveDown} onSelect={() => run(moveRole(1))}>
                  <ArrowDown aria-hidden className="h-4 w-4" />
                  Przenieś stanowisko niżej
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => run(duplicateRole)}>
                  <Copy aria-hidden className="h-4 w-4" />
                  Powiel stanowisko
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void removeRole()}>
                  <Trash2 aria-hidden className="h-4 w-4" />
                  Usuń stanowisko
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          ) : null}
          {ai?.enabled ? (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger
                disabled={disabled || ai.phase !== "idle"}
                aria-label="AI na zaznaczonym tekście"
                className="gap-2"
              >
                <Sparkles aria-hidden className="h-4 w-4 text-primary" />
                AI na zaznaczonym tekście
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="max-w-72">
                <DropdownMenuLabel className="font-normal text-muted-foreground">
                  {ai.selection.ok
                    ? "Propozycja dla zaznaczonego tekstu"
                    : (ai.selection.reason ?? "Zaznacz fragment w akapicie albo punkcie.")}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {CV_AI_ACTIONS.map((item) => (
                  <DropdownMenuItem
                    key={item.action}
                    disabled={!ai.selection.ok}
                    onSelect={() => ai.start(item.action)}
                  >
                    {item.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          ) : null}
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={disabled} onSelect={() => run(setCvAlignEverywhere("justify"))}>
            <AlignJustify aria-hidden className="h-4 w-4" />
            Wyjustuj całe CV
          </DropdownMenuItem>
          <DropdownMenuItem disabled={disabled} onSelect={() => run(setCvAlignEverywhere("left"))}>
            <AlignLeft aria-hidden className="h-4 w-4" />
            Całe CV do lewej
          </DropdownMenuItem>
          {moreGroups.map((group, index) =>
            group.length > 0 ? (
              <Fragment key={index}>
                <DropdownMenuSeparator />
                {group.map((item) => (
                  <DropdownMenuItem
                    key={item.label}
                    disabled={item.disabled}
                    title={item.title}
                    onSelect={() => {
                      keepFocus.current = true;
                      window.setTimeout(item.onSelect, 0);
                    }}
                  >
                    {item.icon}
                    {item.label}
                  </DropdownMenuItem>
                ))}
              </Fragment>
            ) : null,
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {confirmDialog}
    </div>
  );
}
