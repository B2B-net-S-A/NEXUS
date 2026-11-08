import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReturnForFixDialog } from "@/components/v2/recruitment/dl-review/ReturnForFixDialog";

describe("„Wróć do poprawy” z punktami CV (R5, 07.11.2026)", () => {
  it("zaznaczone „CV firmowe” rozwija punkty QC, a wybrane idą do uwagi", async () => {
    const onConfirm = vi.fn();
    render(
      <ReturnForFixDialog
        open
        onOpenChange={() => undefined}
        candidateName="Alan Wronikowski"
        options={[
          { key: "field:availability", label: "Dostępność", group: "terms" },
          { key: "cv", label: "CV firmowe", group: "cv" },
        ]}
        cvPoints={["ETL — nikt nie sprawdził opisu w rolach", "Daty stanowisk jak w oryginale"]}
        onConfirm={onConfirm}
      />,
    );
    expect(screen.queryByRole("group", { name: "Co poprawić w CV" })).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: "CV firmowe" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "ETL — nikt nie sprawdził opisu w rolach" }));
    await userEvent.type(screen.getByLabelText("Uwaga dla rekrutera"), "Klient pyta o Airflow.");
    await userEvent.click(screen.getByRole("button", { name: /Wróć do poprawy/ }));
    expect(onConfirm).toHaveBeenCalledWith({
      fields: ["cv"],
      remark: "Klient pyta o Airflow.\n\nW CV popraw:\n• ETL — nikt nie sprawdził opisu w rolach",
    });
  });
});
