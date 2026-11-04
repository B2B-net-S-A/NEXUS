"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { PanelTransport, PanelView } from "@/lib/api/clientPanel";

interface PanelContextValue {
  token: string;
  transport: PanelTransport;
  view: PanelView | null;
}

const PanelContext = createContext<PanelContextValue | null>(null);

export function PanelContextProvider({
  value,
  children,
}: {
  value: PanelContextValue;
  children: ReactNode;
}) {
  return <PanelContext.Provider value={value}>{children}</PanelContext.Provider>;
}

export function usePanelContext(): PanelContextValue {
  const value = useContext(PanelContext);
  if (!value) throw new Error("usePanelContext poza ClientPanelApp");
  return value;
}
