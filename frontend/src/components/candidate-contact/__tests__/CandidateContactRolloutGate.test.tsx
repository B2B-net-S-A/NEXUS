import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel";
import { MyContactQueueWidget } from "@/components/candidate-contact/MyContactQueueWidget";
import { candidateContactApi } from "@/lib/candidate-contact";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: vi.fn(),
    showSuccess: vi.fn(),
  }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("candidate contact rollout gates", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not render or fetch the recruiter widget while disabled", () => {
    const queueSpy = vi.spyOn(candidateContactApi, "queue");
    const { container } = render(
      <MyContactQueueWidget featureEnabledOverride={false} />,
      { wrapper },
    );

    expect(container).toBeEmptyDOMElement();
    expect(queueSpy).not.toHaveBeenCalled();
  });

  it("does not render or fetch the oversight panel while disabled", () => {
    const oversightSpy = vi.spyOn(candidateContactApi, "oversight");
    const { container } = render(
      <ContactOversightPanel featureEnabledOverride={false} />,
      { wrapper },
    );

    expect(container).toBeEmptyDOMElement();
    expect(oversightSpy).not.toHaveBeenCalled();
  });
});
