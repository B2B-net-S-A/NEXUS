"use client";

/**
 * Pasek narzędzi edytora CV. Przyciski wołają polecenia z
 * `lib/cv-editor-blocks.ts`; polecenie, które nie ma zastosowania w miejscu
 * kursora, jest wyłączone, a nie ukryte.
 */

import { useEditorState, type Editor } from "@tiptap/react";
import {
  ArrowDown,
  ArrowUp,
  Bold,
  ChevronDown,
  Copy,
  List,
  Plus,
  Redo2,
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
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
  disabled?: boolean;
}

export function CvEditorToolbar({ editor, language, disabled = false }: CvEditorToolbarProps) {
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
      <Divider />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="flex-none gap-1 px-2"
            // Odstęp robi `gap`, więc bez etykiety czytnik sklejałby oba słowa.
            aria-label={`Typ akapitu: ${kindLabel}`}
            disabled={disabled || view.kindLocked}
          >
            <span className="text-muted-foreground">Typ akapitu:</span>
            {kindLabel}
            <ChevronDown aria-hidden className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" onCloseAutoFocus={backToText}>
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
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="flex-none gap-1 px-2" disabled={disabled}>
            <Plus aria-hidden className="h-4 w-4" />
            Dodaj
            <ChevronDown aria-hidden className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" onCloseAutoFocus={backToText}>
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
        </DropdownMenuContent>
      </DropdownMenu>

      {view.role ? (
        <>
          <Divider />
          <span className="min-w-0 max-w-56 flex-none truncate px-1 text-xs text-muted-foreground">
            Stanowisko: <span className="text-foreground">{view.role}</span>
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Przenieś stanowisko wyżej"
            disabled={disabled || !view.canMoveUp}
            onClick={() => run(moveRole(-1))}
          >
            <ArrowUp aria-hidden className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Przenieś stanowisko niżej"
            disabled={disabled || !view.canMoveDown}
            onClick={() => run(moveRole(1))}
          >
            <ArrowDown aria-hidden className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Powiel stanowisko"
            disabled={disabled}
            onClick={() => run(duplicateRole)}
          >
            <Copy aria-hidden className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="quiet"
            size="icon-sm"
            aria-label="Usuń stanowisko"
            disabled={disabled}
            onClick={() => void removeRole()}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </Button>
        </>
      ) : null}
      {confirmDialog}
    </div>
  );
}
