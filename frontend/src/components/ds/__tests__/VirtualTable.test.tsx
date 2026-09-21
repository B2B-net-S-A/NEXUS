import * as React from "react"
import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"

import {
  VirtualTable,
  type VirtualTableColumn,
  type VirtualTableKey,
  type VirtualTableProps,
  type VirtualTableSort,
} from "@/components/ds/VirtualTable"

interface Person {
  id: number
  name: string
  stage: string
}

const PEOPLE: Person[] = [
  { id: 1, name: "Anna Kowalska", stage: "new" },
  { id: 2, name: "Piotr Zieliński", stage: "new" },
  { id: 3, name: "Marta Nowak", stage: "cv" },
  { id: 4, name: "Tomasz Lis", stage: "cv" },
  { id: 5, name: "Ewa Bąk", stage: "cv" },
]

const COLUMNS: VirtualTableColumn<Person>[] = [
  { key: "name", header: "Kandydat", width: "minmax(0,1.2fr)", render: (p) => p.name, sortKey: "name" },
  {
    key: "note",
    header: "Notatka",
    width: "160px",
    render: (p) => <input aria-label={`Notatka ${p.name}`} defaultValue="" />,
  },
  { key: "stage", header: "Etap", width: "124px", align: "right", render: (p) => p.stage },
]

const getRowKey = (p: Person) => p.id
const getRowLabel = (p: Person) => p.name

/** Rodzic kontrolujący stan — tak tabela będzie używana na ekranie. */
function Harness(props: Partial<VirtualTableProps<Person>> & { initialActive?: VirtualTableKey | null }) {
  const { initialActive = null, ...rest } = props
  const [selected, setSelected] = React.useState<Set<VirtualTableKey>>(new Set())
  const [active, setActive] = React.useState<VirtualTableKey | null>(initialActive)
  const [sort, setSort] = React.useState<VirtualTableSort | null>(null)
  return (
    <>
      <VirtualTable<Person>
        aria-label="Kandydaci"
        columns={COLUMNS}
        rows={PEOPLE}
        getRowKey={getRowKey}
        getRowLabel={getRowLabel}
        selectedKeys={selected}
        onSelectionChange={setSelected}
        activeKey={active}
        onActiveChange={(key) => setActive(key)}
        sort={sort}
        onSortChange={setSort}
        // jsdom nie ma layoutu → wirtualizer zwróciłby zero wierszy.
        virtualize={false}
        {...rest}
      />
      <output data-testid="selected">{[...selected].sort().join(",")}</output>
      <output data-testid="active">{active === null ? "" : String(active)}</output>
    </>
  )
}

const grid = () => screen.getByRole("grid", { name: "Kandydaci" })
const dataRows = () => grid().querySelectorAll("[data-row-key]")
const checkbox = (name: string) => screen.getByRole("checkbox", { name: `Zaznacz: ${name}` })

describe("VirtualTable", () => {
  it("renderuje wiersze, nagłówki i atrybuty siatki", () => {
    render(<Harness />)
    expect(dataRows()).toHaveLength(5)
    expect(screen.getAllByRole("columnheader")).toHaveLength(4) // checkbox + 3 kolumny
    expect(grid()).toHaveAttribute("aria-rowcount", "6")
    expect(screen.getByText("Anna Kowalska").closest("[role=row]")).toHaveAttribute("aria-rowindex", "2")
    expect(screen.getByText("Anna Kowalska").closest("[role=row]")).toHaveAttribute("aria-selected", "false")
  })

  it("renderuje wiersze pod grupami w kolejności grup, a zwinięta grupa pokazuje sam nagłówek", () => {
    const onToggleGroup = vi.fn()
    render(
      <Harness
        onToggleGroup={onToggleGroup}
        groups={[
          { key: "cv", label: "CV wysłane", rowKeys: [3, 4, 5], hint: "2 po terminie" },
          { key: "new", label: "Nowi", rowKeys: [1, 2], collapsed: true },
        ]}
      />,
    )
    const names = Array.from(dataRows()).map((el) => el.getAttribute("data-row-key"))
    expect(names).toEqual(["3", "4", "5"])
    expect(screen.queryByText("Anna Kowalska")).not.toBeInTheDocument()

    const open = screen.getByRole("button", { name: /CV wysłane/ })
    expect(open).toHaveAttribute("aria-expanded", "true")
    expect(within(open).getByText("3")).toBeInTheDocument()
    expect(within(open).getByText("2 po terminie")).toBeInTheDocument()

    const closed = screen.getByRole("button", { name: /Nowi/ })
    expect(closed).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(closed)
    expect(onToggleGroup).toHaveBeenCalledWith("new")
  })

  it("nie gubi po cichu wiersza spoza grup", () => {
    render(<Harness groups={[{ key: "cv", label: "CV", rowKeys: [3] }]} />)
    expect(dataRows()).toHaveLength(5)
  })

  it("checkbox nagłówka: indeterminate przy części, zaznacza i odznacza wszystko", () => {
    render(<Harness />)
    const all = screen.getByRole("checkbox", { name: "Zaznacz wszystkie" }) as HTMLInputElement
    expect(all.indeterminate).toBe(false)

    fireEvent.click(checkbox("Marta Nowak"))
    expect(all.indeterminate).toBe(true)
    expect(all.checked).toBe(false)

    fireEvent.click(all)
    expect(screen.getByTestId("selected")).toHaveTextContent("1,2,3,4,5")
    expect(all.indeterminate).toBe(false)
    expect(all.checked).toBe(true)

    fireEvent.click(all)
    expect(screen.getByTestId("selected")).toHaveTextContent("")
  })

  it("shift-klik zaznacza zakres i nie ustawia aktywnego wiersza", () => {
    render(<Harness />)
    fireEvent.click(checkbox("Piotr Zieliński"))
    fireEvent.click(checkbox("Ewa Bąk"), { shiftKey: true })
    expect(screen.getByTestId("selected")).toHaveTextContent("2,3,4,5")
    expect(screen.getByTestId("active")).toHaveTextContent("")
  })

  it("klik w wiersz ustawia aktywny, strzałki go przesuwają, spacja zaznacza, Enter aktywuje", () => {
    const onRowActivate = vi.fn()
    render(<Harness onRowActivate={onRowActivate} />)
    fireEvent.click(screen.getByText("Piotr Zieliński"))
    expect(screen.getByTestId("active")).toHaveTextContent("2")
    expect(screen.getByText("Piotr Zieliński").closest("[role=row]")).toHaveAttribute("aria-current", "true")

    fireEvent.keyDown(grid(), { key: "ArrowDown" })
    expect(screen.getByTestId("active")).toHaveTextContent("3")
    fireEvent.keyDown(grid(), { key: "ArrowUp" })
    fireEvent.keyDown(grid(), { key: "ArrowUp" })
    fireEvent.keyDown(grid(), { key: "ArrowUp" }) // zatrzymuje się na pierwszym
    expect(screen.getByTestId("active")).toHaveTextContent("1")

    fireEvent.keyDown(grid(), { key: " " })
    expect(screen.getByTestId("selected")).toHaveTextContent("1")

    fireEvent.keyDown(grid(), { key: "Enter" })
    expect(onRowActivate).toHaveBeenCalledWith(PEOPLE[0])
  })

  it("strzałki pomijają wiersze zwiniętej grupy", () => {
    render(
      <Harness
        initialActive={2}
        groups={[
          { key: "new", label: "Nowi", rowKeys: [1, 2] },
          { key: "cv", label: "CV", rowKeys: [3, 4], collapsed: true },
          { key: "x", label: "Inne", rowKeys: [5] },
        ]}
      />,
    )
    fireEvent.keyDown(grid(), { key: "ArrowDown" })
    expect(screen.getByTestId("active")).toHaveTextContent("5")
  })

  it("ignoruje klawiaturę podczas pisania w polu w wierszu oraz z modyfikatorem", () => {
    const onKeyCommand = vi.fn()
    const onRowActivate = vi.fn()
    render(
      <Harness initialActive={2} keyCommands={["e"]} onKeyCommand={onKeyCommand} onRowActivate={onRowActivate} />,
    )
    const input = screen.getByRole("textbox", { name: "Notatka Piotr Zieliński" })
    for (const key of ["ArrowDown", " ", "Enter", "e"]) {
      const notPrevented = fireEvent.keyDown(input, { key })
      expect(notPrevented).toBe(true) // preventDefault NIE został wywołany
    }
    expect(screen.getByTestId("active")).toHaveTextContent("2")
    expect(screen.getByTestId("selected")).toHaveTextContent("")
    expect(onKeyCommand).not.toHaveBeenCalled()
    expect(onRowActivate).not.toHaveBeenCalled()

    fireEvent.keyDown(grid(), { key: "e", metaKey: true })
    fireEvent.keyDown(grid(), { key: "ArrowDown", ctrlKey: true })
    expect(onKeyCommand).not.toHaveBeenCalled()
    expect(screen.getByTestId("active")).toHaveTextContent("2")
  })

  it("ignoruje klawiaturę w contenteditable", () => {
    const columns: VirtualTableColumn<Person>[] = [
      { key: "name", header: "Kandydat", width: "1fr", render: (p) => <div contentEditable suppressContentEditableWarning data-testid={`ce-${p.id}`}>{p.name}</div> },
    ]
    render(<Harness columns={columns} initialActive={1} />)
    fireEvent.keyDown(screen.getByTestId("ce-1"), { key: "ArrowDown" })
    expect(screen.getByTestId("active")).toHaveTextContent("1")
  })

  it("deleguje wyłącznie klawisze z allowlisty, dla aktywnego wiersza", () => {
    const onKeyCommand = vi.fn()
    render(<Harness initialActive={3} keyCommands={["e", "n"]} onKeyCommand={onKeyCommand} />)
    fireEvent.keyDown(grid(), { key: "E" })
    fireEvent.keyDown(grid(), { key: "x" })
    expect(onKeyCommand).toHaveBeenCalledTimes(1)
    expect(onKeyCommand).toHaveBeenCalledWith("e", PEOPLE[2])
  })

  it("nagłówek sortowania przełącza asc → desc → brak i ustawia aria-sort", () => {
    render(<Harness />)
    const header = screen.getByRole("columnheader", { name: /Kandydat/ })
    const button = within(header).getByRole("button")
    expect(header).toHaveAttribute("aria-sort", "none")
    fireEvent.click(button)
    expect(header).toHaveAttribute("aria-sort", "ascending")
    fireEvent.click(button)
    expect(header).toHaveAttribute("aria-sort", "descending")
    fireEvent.click(button)
    expect(header).toHaveAttribute("aria-sort", "none")
    // kolumna bez sortKey nie jest przyciskiem
    expect(within(screen.getByRole("columnheader", { name: "Etap" })).queryByRole("button")).toBeNull()
  })

  it("pokazuje stan pusty, szkielety ładowania i stopkę", () => {
    const { rerender } = render(<Harness rows={[]} empty="Nikogo tu nie ma" footer={<div>Pasek akcji</div>} />)
    expect(screen.getByText("Nikogo tu nie ma")).toBeInTheDocument()
    expect(screen.getByText("Pasek akcji")).toBeInTheDocument()

    rerender(<Harness rows={[]} loading empty="Nikogo tu nie ma" />)
    expect(screen.queryByText("Nikogo tu nie ma")).not.toBeInTheDocument()
    expect(screen.getByTestId("virtual-table-loading")).toBeInTheDocument()
    expect(grid()).toHaveAttribute("aria-busy", "true")
  })
})
