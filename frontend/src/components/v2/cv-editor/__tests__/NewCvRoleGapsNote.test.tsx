import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { NewCvRoleGapsNote, gapsSentence } from "../NewCvRoleGapsNote";
import { roleGaps } from "@/lib/cv-new-layout-gaps";

describe("ostrzeżenie o stanowiskach bez dat albo firmy (25.11.2026)", () => {
  it("nic nie pokazuje, gdy wszystko jest", () => {
    const { container } = render(<NewCvRoleGapsNote gaps={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(roleGaps([{ period: "05.2020 – obecnie", company: "Firma" }])).toBeNull();
  });

  it("liczy braki z dokumentu i mówi, czego brakuje", () => {
    const gaps = roleGaps([
      { period: "", company: "" },
      { period: "2019 – 2021", company: "" },
      { period: "currently", company: "Firma" },
    ]);
    expect(gaps).toEqual({ without_dates: 1, without_company: 2 });
    expect(gapsSentence(gaps!)).toBe("Nowe CV nie odczytało dat w 1 stanowisku i firmy w 2 stanowiskach.");
    expect(roleGaps([{ period: "", company: "" }], true)).toEqual({ without_dates: 1, without_company: 0 });
  });

  it("przycisk prowadzi do „Stanowisk”", () => {
    const onFix = vi.fn();
    render(<NewCvRoleGapsNote gaps={{ without_dates: 2, without_company: 0 }} onFix={onFix} />);
    expect(screen.getByTestId("new-cv-role-gaps")).toHaveTextContent("dat w 2 stanowiskach");
    fireEvent.click(screen.getByRole("button", { name: /Popraw w „Stanowiskach”/ }));
    expect(onFix).toHaveBeenCalledOnce();
  });
});
