// Frontend typy dla Job Chat — wewnętrznego czatu zespołu per rekrutacja.
// Backend kontrakty: backend/app/schemas/job_chat.py + backend/app/api/job_chat.py.

export interface ChatUserMini {
  id: number;
  name: string;
  email: string;
  role: string;
}

export interface ReactionAggregate {
  emoji: string;
  count: number;
  user_ids: number[];
}

export interface ReadByUser {
  user_id: number;
  name: string;
  read_at: string;
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
  reactions: ReactionAggregate[];
  created_at: string;
  updated_at: string;
}

export interface ReactionToggleResponse {
  message_id: number;
  reactions: ReactionAggregate[];
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

export interface ChatReactionEvent {
  job_id: number;
  message_id: number;
  reactions: ReactionAggregate[];
}

export type ChatBusEvent =
  | { kind: "new"; data: ChatNewMessageEvent }
  | { kind: "edit"; data: ChatEditMessageEvent }
  | { kind: "delete"; data: ChatDeleteMessageEvent }
  | { kind: "pin"; data: ChatPinEvent }
  | { kind: "reaction"; data: ChatReactionEvent };

/** Custom event nazwa dla window.addEventListener / dispatchEvent. */
export const CHAT_BUS_EVENT = "nexus:chat-bus";

// ── Candidate Chat (Phase 2) ─────────────────────────────────────────────────

export interface CandidateChatMessage extends Omit<ChatMessage, "job_id"> {
  candidate_id: number;
}

export interface CandidateChatMessageListResp {
  items: CandidateChatMessage[];
  has_more: boolean;
  next_before_id: number | null;
}

export interface CandidateChatBusEventNew {
  candidate_id: number;
  message: CandidateChatMessage;
}
export interface CandidateChatBusEventDelete {
  candidate_id: number;
  message_id: number;
}
export interface CandidateChatBusEventPin {
  candidate_id: number;
  message_id: number;
  pinned: boolean;
}
export interface CandidateChatBusEventReaction {
  candidate_id: number;
  message_id: number;
  reactions: ReactionAggregate[];
}

export type CandidateChatBusEvent =
  | { kind: "new"; data: CandidateChatBusEventNew }
  | { kind: "edit"; data: CandidateChatBusEventNew }
  | { kind: "delete"; data: CandidateChatBusEventDelete }
  | { kind: "pin"; data: CandidateChatBusEventPin }
  | { kind: "reaction"; data: CandidateChatBusEventReaction };

export const CANDIDATE_CHAT_BUS_EVENT = "nexus:candidate-chat-bus";

// ── Admin global chats (Feature 10) ──────────────────────────────────────────

export interface GlobalChatItem {
  chat_type: "job" | "candidate";
  message_id: number;
  parent_id: number;
  parent_label: string;
  author_id: number | null;
  author_name: string | null;
  content: string;
  is_deleted: boolean;
  created_at: string;
}

export interface GlobalChatList {
  items: GlobalChatItem[];
  has_more: boolean;
}
