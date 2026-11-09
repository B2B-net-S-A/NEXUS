import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobsHiddenByScopeNotice } from "@/components/v2/jobs/JobsHiddenByScopeNotice";

describe("JobsHiddenByScopeNotice", () => {
  it("mówi, ile rekrutacji schował zakres, i przełącza na wszystkie", () => {
    const onShowAll = vi.fn();
    render(<JobsHiddenByScopeNotice hidden={3} scope="mine" onShowAll={onShowAll} />);
    expect(screen.getByRole("status")).toHaveTextContent("jest ich jeszcze 3");
    expect(screen.getByRole("status")).toHaveTextContent("Moje");
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie" }));
    expect(onShowAll).toHaveBeenCalledOnce();
  });

  it("nie pokazuje się, gdy nic nie jest schowane", () => {
    const { container } = render(
      <JobsHiddenByScopeNotice hidden={0} scope="open" onShowAll={() => undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
