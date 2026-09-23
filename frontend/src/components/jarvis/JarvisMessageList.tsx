"use client";

/** Lista pozycji rozmowy — wiadomości, kroki, karty akcji i linki. */

import { useEffect, useRef } from "react";
import { AlertCircle, MousePointerClick } from "lucide-react";
import type { JarvisAction, JarvisItem, ScreenGuideTask } from "@/lib/jarvis/types";
import { JarvisGuideCard } from "./JarvisGuideCard";
import { JarvisActionCard } from "./JarvisActionCard";
import { JarvisDeepLinkCard } from "./JarvisDeepLinkCard";
import { JarvisMarkdown } from "./JarvisMarkdown";
import { JarvisSources } from "./JarvisSources";
import { JarvisStepTrace } from "./JarvisStepTrace";

interface Props {
  items: JarvisItem[];
  thinking?: boolean;
  assistantName: string;
  busyActionId?: string | null;
  actionsDisabled?: boolean;
  onConfirm?: (action: JarvisAction) => void;
  onReject?: (action: JarvisAction) => void;
  onNavigate?: () => void;
  onGuideTask?: (task: ScreenGuideTask) => void;
  onShowAnchor?: (anchorId: string) => void;
  onAskOther?: () => void;
}

export function JarvisMessageList({
  items,
  thinking = false,
  assistantName,
  busyActionId,
  actionsDisabled,
  onConfirm,
  onReject,
  onNavigate,
  onGuideTask,
  onShowAnchor,
  onAskOther,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [items, thinking]);

  return (
    <div className="space-y-3" aria-live="polite">
      {items.map((item, index) => {
        switch (item.kind) {
          case "message":
            return item.role === "user" ? (
              <div key={index} className="flex justify-end">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-3 py-2 text-sm text-primary-foreground">
                  {item.markdown}
                </div>
              </div>
            ) : (
              <div key={index} className="max-w-[92%] rounded-2xl rounded-bl-md bg-muted px-3 py-2">
                <JarvisMarkdown>{item.markdown}</JarvisMarkdown>
                {item.streaming && (
                  <span
                    className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/60 align-middle"
                    aria-hidden
                    data-testid="jarvis-streaming-caret"
                  />
                )}
              </div>
            );
          case "guide":
            return (
              <JarvisGuideCard
                key={`guide-${index}`}
                guide={item.guide}
                onTask={onGuideTask}
                onShow={onShowAnchor}
                onAskOther={onAskOther}
              />
            );
          case "highlight":
            return (
              <div
                key={index}
                className="flex items-start gap-2 rounded-xl border border-primary/40 bg-primary/5 px-3 py-2 text-sm"
                data-testid="jarvis-highlight-item"
              >
                <MousePointerClick className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="font-medium">Pokazuję: {item.label}</p>
                  {item.reason && <p className="text-xs text-muted-foreground">{item.reason}</p>}
                </div>
                {onShowAnchor && (
                  <button
                    type="button"
                    onClick={() => onShowAnchor(item.anchor)}
                    className="shrink-0 text-xs font-medium text-primary hover:underline"
                  >
                    Pokaż ponownie
                  </button>
                )}
              </div>
            );
          case "steps":
            return (
              <div key={index} className="pl-1">
                <JarvisStepTrace steps={item.steps} />
              </div>
            );
          case "action":
            return (
              <JarvisActionCard
                key={item.action.id}
                action={item.action}
                busy={busyActionId === item.action.id}
                disabled={actionsDisabled}
                onConfirm={onConfirm}
                onReject={onReject}
              />
            );
          case "sources":
            return <JarvisSources key={index} items={item.items} />;
          case "link":
            return <JarvisDeepLinkCard key={index} link={item} onNavigate={onNavigate} />;
          case "error":
            return (
              <p
                key={index}
                role="alert"
                className="flex items-start gap-1.5 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {item.message}
              </p>
            );
          default:
            return null;
        }
      })}
      {thinking && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="jarvis-thinking">
          <span className="inline-flex gap-0.5" aria-hidden>
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.2s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.1s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
          </span>
          {assistantName} myśli…
        </p>
      )}
      <div ref={endRef} />
    </div>
  );
}
