"use client";

/**
 * Dymek nad zaznaczeniem i karta propozycji AI w edytorze CV (Edytor CV 2, PR 3).
 *
 * Oba stoją WEWNĄTRZ przewijanej kolumny kartki, pozycjonowane względem niej:
 * jadą z tekstem przy przewijaniu i zostają w oknie edytora (okno jest modalne —
 * element doczepiony do `body` byłby poza nim nieklikalny). Dymek pokazuje się po
 * skończonym zaznaczeniu (puszczenie myszy albo klawisza), nie w trakcie
 * przeciągania. Przycisk wciśnięty myszą nie zabiera fokusu edytorowi, więc
 * zaznaczenie zostaje.
 */

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Editor } from "@tiptap/core";
import { Bold, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CvAiProposalCard } from "@/components/v2/cv-editor/CvAiProposalCard";
import type { CvSelectionAiController } from "@/components/v2/cv-editor/useCvSelectionAi";
import { CV_AI_ACTIONS } from "@/lib/api/cvEditorAi";
import { pendingTarget } from "@/lib/cv-editor-ai";
import { cn } from "@/lib/utils";

export interface CvEditorSelectionAiProps {
  editor: Editor;
  controller: CvSelectionAiController;
  /** Przewijana kolumna kartki (`.cv-paper`) — w niej stoją dymek i karta. */
  container: HTMLElement | null;
  /** CV po polsku: tłumaczenie fragmentu zostawia polskie etykiety szablonu. */
  cvLanguage: "pl" | "en";
  onShowSource?: (quote: string) => void;
}

interface Spot {
  top: number;
  left: number;
  /** Dymek nad zaznaczeniem (`true`) albo pod nim. */
  above: boolean;
}

const CARD_WIDTH = 420;
const GAP = 8;

/** Pozycja zakresu względem przewijanej kolumny; `null`, gdy przeglądarka nie liczy układu. */
function rangeBox(editor: Editor, container: HTMLElement, from: number, to: number) {
  try {
    const start = editor.view.coordsAtPos(from);
    const end = editor.view.coordsAtPos(to, -1);
    const box = container.getBoundingClientRect();
    return {
      top: Math.min(start.top, end.top) - box.top + container.scrollTop,
      bottom: Math.max(start.bottom, end.bottom) - box.top + container.scrollTop,
      left: start.left - box.left + container.scrollLeft,
    };
  } catch {
    return null;
  }
}

function Positioned({
  container,
  spot,
  width,
  reveal = false,
  children,
}: {
  container: HTMLElement;
  spot: Spot;
  width?: number;
  /** Przewiń kolumnę tak, żeby element był widoczny w całości (karta pod zaznaczeniem na dole ekranu). */
  reveal?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(spot.left);
  useEffect(() => {
    if (reveal) ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [reveal, spot.top]);
  // Po narysowaniu znamy szerokość — nie wypuszczamy elementu poza kolumnę.
  useLayoutEffect(() => {
    const own = ref.current?.offsetWidth ?? 0;
    const room = container.clientWidth - own - GAP;
    setLeft(Math.max(GAP, Math.min(spot.left, room)));
  }, [container, spot.left, children]);
  return createPortal(
    <div
      ref={ref}
      style={{ top: spot.top, left, width, maxWidth: `calc(100% - ${2 * GAP}px)` }}
      // `w-max`: szerokość z treści, nie z miejsca do prawej krawędzi kolumny.
      className={cn("absolute z-20", width == null && "w-max", spot.above && "-translate-y-full")}
    >
      {children}
    </div>,
    container,
  );
}

export function CvEditorSelectionAi({
  editor,
  controller,
  container,
  cvLanguage,
  onShowSource,
}: CvEditorSelectionAiProps) {
  // Zaznaczanie myszą trwa — dymek czeka na puszczenie przycisku.
  const [dragging, setDragging] = useState(false);
  const [, setTick] = useState(0);
  useEffect(() => {
    const dom = editor.view.dom;
    const down = () => setDragging(true);
    const up = () => setDragging(false);
    const moved = () => setTick((tick) => tick + 1);
    dom.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    window.addEventListener("resize", moved);
    editor.on("selectionUpdate", moved);
    editor.on("transaction", moved);
    return () => {
      dom.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.removeEventListener("resize", moved);
      editor.off("selectionUpdate", moved);
      editor.off("transaction", moved);
    };
  }, [editor]);

  if (!container || !controller.enabled || editor.isDestroyed) return null;

  if (controller.phase !== "idle") {
    const pending = pendingTarget(editor.state);
    // Zakres zniknął (tekst zmieniono) — karta zostaje tam, gdzie kursor.
    const at = pending ?? { from: editor.state.selection.from, to: editor.state.selection.to };
    const box = rangeBox(editor, container, at.from, at.to);
    const width = Math.min(CARD_WIDTH, container.clientWidth - 2 * GAP);
    const title = CV_AI_ACTIONS.find((item) => item.action === controller.action)?.title ?? "Propozycja AI";
    return (
      <Positioned
        container={container}
        spot={{ top: (box?.bottom ?? 0) + GAP, left: box?.left ?? GAP, above: false }}
        width={width > 0 ? width : undefined}
        reveal
      >
        <CvAiProposalCard
          title={title}
          state={controller.phase}
          before={controller.before}
          response={controller.response}
          message={controller.message}
          canRetry={controller.canRetry}
          busy={controller.busy}
          mixedLanguage={controller.action === "translate" && cvLanguage === "pl"}
          onAccept={controller.accept}
          onAgain={controller.again}
          onRefine={controller.refine}
          onReject={controller.reject}
          onShowSource={onShowSource}
        />
      </Positioned>
    );
  }

  if (dragging || controller.selection.hidden) return null;
  const { from, to } = editor.state.selection;
  const box = rangeBox(editor, container, from, to);
  // Na ekranie dotykowym nad zaznaczeniem stoi systemowe menu — dymek idzie pod spód.
  const touch = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;
  const above = !touch && (box?.top ?? 0) - container.scrollTop > 56;
  const spot: Spot = {
    top: box ? (above ? box.top - GAP : box.bottom + GAP) : 0,
    left: box?.left ?? GAP,
    above,
  };
  const reason = controller.selection.ok ? undefined : (controller.selection.reason ?? undefined);
  // `mousedown` bez domyślnej akcji: przycisk nie zabiera fokusu edytorowi.
  const keepSelection = (event: React.MouseEvent) => event.preventDefault();

  return (
    <Positioned container={container} spot={spot}>
      <div
        role="toolbar"
        aria-label="Zaznaczony tekst"
        className="flex flex-wrap items-center gap-0.5 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md"
      >
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="Pogrubienie"
          aria-pressed={editor.isActive("bold")}
          onMouseDown={keepSelection}
          onClick={() => editor.chain().focus().toggleBold().run()}
        >
          <Bold className="size-4" aria-hidden />
        </Button>
        <span aria-hidden className="mx-0.5 h-5 w-px bg-border" />
        <Sparkles className="mx-1 size-3.5 flex-none text-primary" aria-hidden />
        {CV_AI_ACTIONS.map((item) => (
          <Button
            key={item.action}
            type="button"
            size="sm"
            variant="ghost"
            className="px-2"
            disabled={!controller.selection.ok}
            title={reason}
            onMouseDown={keepSelection}
            onClick={() => controller.start(item.action)}
          >
            {item.label}
          </Button>
        ))}
        {reason ? <p className="basis-full px-2 pb-0.5 text-xs text-muted-foreground">{reason}</p> : null}
      </div>
    </Positioned>
  );
}
