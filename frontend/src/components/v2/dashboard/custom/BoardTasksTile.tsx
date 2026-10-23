"use client"

// „Czeka na Ciebie” jako kafelek (23.10.2026, decyzja Artura po prośbie Olafa):
// Head of Recruitment i admin przesuwają panel i usuwają go jak inne kafelki.
//
// Kafelek renderuje ten sam `BoardTasksPanel` co pas nad siatką — z tymi samymi
// ustawieniami pulpitu (ukryte listy, kafelek „Do uzupełnienia”, pas „Do
// wysłania do klienta”), które `CustomDashboard` podaje przez kontekst. Gdy
// kafelek stoi na pulpicie, panelu nad siatką nie ma — kafelek albo pas, nigdy
// oba.

import { createContext, useContext, type ReactNode } from "react"

import { BoardTasksPanel, type BoardTasksPanelProps } from "@/components/v2/dashboard/BoardTasksPanel"

const BoardTasksPanelContext = createContext<BoardTasksPanelProps>({})

export function BoardTasksPanelProvider({
  value,
  children,
}: {
  value: BoardTasksPanelProps
  children: ReactNode
}) {
  return <BoardTasksPanelContext.Provider value={value}>{children}</BoardTasksPanelContext.Provider>
}

export function BoardTasksTile() {
  const props = useContext(BoardTasksPanelContext)
  return (
    <BoardTasksPanel {...props} inTile />
  )
}
