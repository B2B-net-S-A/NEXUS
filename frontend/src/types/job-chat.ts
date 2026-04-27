// Frontend typy dla Job Chat — wewnętrznego czatu zespołu per rekrutacja.
// Backend kontrakty: backend/app/schemas/job_chat.py + backend/app/api/job_chat.py.

export interface ChatUserMini {
  id: number;
  name: string;
  email: string;
  role: string;
}

export interface ChatMessage {
  id: number;
  job_id: number;
  /** Gdy `is_deleted=true` backend zwraca placeholder "[wiadomość usunięta]". */
  content: string;
  author: ChatUserMini | null;
  reply_to_message_id: number | null;
  reply_to_preview: string | null;
  is_edited: boolean;
  edited_at: string | null;
  is_deleted: boolean;
  pinned: boolean;
  pinned_at: string | null;
  pinned_by: number | null;
  /** user_ids osób które zostały @mention'owane (resolved do członków). */
  mentions: number[];
  created_at: string;
  updated_at: string;
}

export interface ChatMessageListResp {
  /** DESC po created_at, id (najnowsze pierwsze). */
  items: ChatMessage[];
  has_more: boolean;
  next_before_id: number | null;
}

export interface ChatUnreadCount {
  job_id: number;
  unread_count: number;
  last_read_message_id: number | null;
}

export interface ChatPinResponse {
  message_id: number;
  pinned: boolean;
}

// ── WS event payloads ────────────────────────────────────────────────────────

export interface ChatNewMessageEvent {
  job_id: number;
  message: ChatMessage;
}

export interface ChatEditMessageEvent {
  job_id: number;
  message: ChatMessage;
}

export interface ChatDeleteMessageEvent {
  job_id: number;
  message_id: number;
}

export interface ChatPinEvent {
  job_id: number;
  message_id: number;
  pinned: boolean;
}

export type ChatBusEvent =
  | { kind: "new"; data: ChatNewMessageEvent }
  | { kind: "edit"; data: ChatEditMessageEvent }
  | { kind: "delete"; data: ChatDeleteMessageEvent }
  | { kind: "pin"; data: ChatPinEvent };

/** Custom event nazwa dla window.addEventListener / dispatchEvent. */
export const CHAT_BUS_EVENT = "nexus:chat-bus";
