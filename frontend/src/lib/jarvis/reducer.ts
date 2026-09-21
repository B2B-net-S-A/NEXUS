/**
 * Zdarzenia strumienia → pozycje rozmowy. Czysta funkcja: testowana bez
 * sieci i bez Reacta; `JarvisRoot` tylko ją woła.
 */

import type { JarvisItem, JarvisMood, JarvisStreamEvent } from "./types";

export interface JarvisTurnState {
  items: JarvisItem[];
  thinking: boolean;
  mood: JarvisMood;
  conversationId: string | null;
}

export function applyStreamEvent(state: JarvisTurnState, event: JarvisStreamEvent): JarvisTurnState {
  switch (event.type) {
    case "conversation":
      return { ...state, conversationId: event.conversation_id };
    case "thinking":
      return { ...state, thinking: true, mood: "thinking" };
    case "step": {
      const items = [...state.items];
      const last = items[items.length - 1];
      const step = { tool: event.tool, label: event.label, status: event.status };
      if (last?.kind === "steps") {
        const steps = [...last.steps];
        if (event.status !== "running") {
          const index = steps.map((s) => s.tool).lastIndexOf(event.tool);
          if (index >= 0 && steps[index].status === "running") steps[index] = step;
          else steps.push(step);
        } else {
          steps.push(step);
        }
        items[items.length - 1] = { kind: "steps", steps };
      } else {
        items.push({ kind: "steps", steps: [step] });
      }
      return { ...state, items, mood: event.status === "running" ? "working" : "thinking" };
    }
    case "message":
      return {
        ...state,
        items: [...state.items, { kind: "message", role: "assistant", markdown: event.markdown }],
        thinking: event.final ? false : state.thinking,
      };
    case "action_proposed":
      return { ...state, items: [...state.items, { kind: "action", action: event.action }], mood: "listening" };
    case "sources":
      return state.items.length === 0 && event.items.length === 0
        ? state
        : { ...state, items: [...state.items, { kind: "sources", items: event.items }] };
    case "deep_link":
      return {
        ...state,
        items: [...state.items, { kind: "link", href: event.href, label: event.label, reason: event.reason }],
      };
    case "error":
      return {
        ...state,
        items: [...state.items, { kind: "error", message: event.message }],
        thinking: false,
        mood: "error",
      };
    case "done": {
      const proposed = state.items.some((i) => i.kind === "action" && i.action.status === "proposed");
      return { ...state, thinking: false, mood: proposed ? "listening" : "idle" };
    }
    default:
      return state;
  }
}

/** Podmiana karty akcji po zatwierdzeniu/odrzuceniu (+ ewentualna karta „mimo ostrzeżenia”). */
export function replaceAction(
  items: JarvisItem[],
  updated: Extract<JarvisItem, { kind: "action" }>["action"],
  followUp?: Extract<JarvisItem, { kind: "action" }>["action"] | null,
  message?: string,
): JarvisItem[] {
  const next: JarvisItem[] = [];
  for (const item of items) {
    if (item.kind === "action" && item.action.id === updated.id) {
      next.push({ kind: "action", action: updated });
      if (message) next.push({ kind: "message", role: "assistant", markdown: message });
      if (followUp) next.push({ kind: "action", action: followUp });
    } else {
      next.push(item);
    }
  }
  return next;
}
