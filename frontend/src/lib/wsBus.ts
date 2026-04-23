/**
 * Module-level WebSocket send slot, shared between `useNotifications` (which
 * owns the socket) and `usePresence` (which needs to send presence:* frames
 * without opening a second connection).
 *
 * Also tracks currently-mounted presence subscriptions so `useNotifications`
 * can replay them on reconnect.
 */

type WsMessage = Record<string, unknown>;

let sender: ((msg: WsMessage) => void) | null = null;

export const activePresenceKeys = new Set<string>();

export function setWsSender(fn: (msg: WsMessage) => void): void {
  sender = fn;
}

export function clearWsSender(): void {
  sender = null;
}

/**
 * Dispatch a JSON frame over the shared WS. Returns true if the message was
 * handed to the socket; false if no socket is currently connected.
 */
export function sendWs(msg: WsMessage): boolean {
  if (!sender) return false;
  try {
    sender(msg);
    return true;
  } catch {
    return false;
  }
}

/** Dispatched by `useNotifications` every time the WS successfully opens. */
export const WS_OPEN_EVENT = "nexus:ws-open";

/** Dispatched by `useNotifications` for every message whose type starts with `presence:`. */
export const PRESENCE_EVENT = "nexus:presence";
