"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  PRESENCE_EVENT,
  WS_OPEN_EVENT,
  activePresenceKeys,
  sendWs,
} from "@/lib/wsBus";

export type PresenceResourceType = "candidate" | "job";

export interface PresenceViewer {
  user_id: number;
  name: string;
  email: string;
  role: string;
  editing: string[];
  since: string | null;
}

interface PresenceUpdateEvent {
  type: "presence:update";
  resource_type: PresenceResourceType;
  resource_id: number;
  viewers: PresenceViewer[];
}

interface UsePresenceResult {
  viewers: PresenceViewer[];
  setEditing: (field: string, active: boolean) => void;
}

const EDITING_THROTTLE_MS = 400;

/**
 * Subscribe to live "currently viewing" state for a candidate or job.
 *
 * - Seeds initial viewer list from GET /api/presence/{type}/{id}/viewers
 * - Sends `presence:subscribe` over the shared WebSocket, listens for
 *   `presence:update` snapshots, and broadcasts field edits via
 *   `presence:editing`.
 * - Automatically unsubscribes on unmount, resource change, tab hide,
 *   and window blur.
 */
export function usePresence(
  resourceType: PresenceResourceType,
  resourceId: number | null | undefined,
): UsePresenceResult {
  const enabled = typeof resourceId === "number" && Number.isFinite(resourceId);
  const key = enabled ? `${resourceType}:${resourceId}` : null;

  const { data: initial } = useQuery({
    queryKey: ["presence", resourceType, resourceId],
    queryFn: async () => {
      const res = await api.get<{ viewers: PresenceViewer[] }>(
        `/api/presence/${resourceType}/${resourceId}/viewers`,
      );
      return res.data.viewers;
    },
    enabled,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const [viewers, setViewers] = useState<PresenceViewer[]>([]);

  useEffect(() => {
    if (!initial) return;
    setViewers(initial);
  }, [initial]);

  // Subscribe / unsubscribe lifecycle
  useEffect(() => {
    if (!key || !enabled) return;

    activePresenceKeys.add(key);
    sendWs({
      type: "presence:subscribe",
      resource_type: resourceType,
      resource_id: resourceId,
    });

    const onMessage = (e: Event) => {
      const detail = (e as CustomEvent<PresenceUpdateEvent>).detail;
      if (!detail || detail.type !== "presence:update") return;
      if (
        detail.resource_type !== resourceType ||
        detail.resource_id !== resourceId
      ) {
        return;
      }
      setViewers(detail.viewers);
    };

    const onReconnect = () => {
      sendWs({
        type: "presence:subscribe",
        resource_type: resourceType,
        resource_id: resourceId,
      });
    };

    const onVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "hidden") {
        sendWs({
          type: "presence:unsubscribe",
          resource_type: resourceType,
          resource_id: resourceId,
        });
      } else if (document.visibilityState === "visible") {
        sendWs({
          type: "presence:subscribe",
          resource_type: resourceType,
          resource_id: resourceId,
        });
      }
    };

    window.addEventListener(PRESENCE_EVENT, onMessage);
    window.addEventListener(WS_OPEN_EVENT, onReconnect);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      activePresenceKeys.delete(key);
      sendWs({
        type: "presence:unsubscribe",
        resource_type: resourceType,
        resource_id: resourceId,
      });
      window.removeEventListener(PRESENCE_EVENT, onMessage);
      window.removeEventListener(WS_OPEN_EVENT, onReconnect);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, key, resourceType, resourceId]);

  // Editing indicator: throttled, tracks last sent state per field
  const lastEditingRef = useRef<Record<string, boolean>>({});
  const editingTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>(
    {},
  );

  const setEditing = useCallback(
    (field: string, active: boolean) => {
      if (!enabled) return;
      // Flush immediately if active==false (user left the field) so others
      // stop seeing the indicator fast; throttle only the "started editing"
      // signal to avoid bursts on focus flicker.
      const send = () => {
        if (lastEditingRef.current[field] === active) return;
        lastEditingRef.current[field] = active;
        sendWs({
          type: "presence:editing",
          resource_type: resourceType,
          resource_id: resourceId,
          field,
          active,
        });
      };

      const pending = editingTimersRef.current[field];
      if (pending) {
        clearTimeout(pending);
        delete editingTimersRef.current[field];
      }

      if (!active) {
        send();
        return;
      }

      editingTimersRef.current[field] = setTimeout(() => {
        delete editingTimersRef.current[field];
        send();
      }, EDITING_THROTTLE_MS);
    },
    [enabled, resourceType, resourceId],
  );

  // Safety net: clear all editing flags on unmount / tab hide / window blur
  useEffect(() => {
    if (!enabled) return;

    const clearAllEditing = () => {
      for (const field of Object.keys(lastEditingRef.current)) {
        if (lastEditingRef.current[field]) {
          lastEditingRef.current[field] = false;
          sendWs({
            type: "presence:editing",
            resource_type: resourceType,
            resource_id: resourceId,
            field,
            active: false,
          });
        }
      }
    };

    const onBlur = () => clearAllEditing();
    const onHidden = () => {
      if (document.visibilityState === "hidden") clearAllEditing();
    };

    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onHidden);

    return () => {
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onHidden);
      clearAllEditing();
      for (const timer of Object.values(editingTimersRef.current)) {
        clearTimeout(timer);
      }
      editingTimersRef.current = {};
    };
  }, [enabled, resourceType, resourceId]);

  return { viewers, setEditing };
}
