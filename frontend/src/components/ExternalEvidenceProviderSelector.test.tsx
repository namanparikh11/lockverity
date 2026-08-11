import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ExternalEvidenceProviderSelection } from "@/api/types";
import {
  defaultExternalEvidenceProviderSelection,
  providerSelectionPayload,
} from "@/api/providerSelection";
import { ExternalEvidenceProviderSelector } from "@/components/ExternalEvidenceProviderSelector";

function SelectorHarness({ openssfApplicable = true }: { openssfApplicable?: boolean }) {
  const [selection, setSelection] = useState<ExternalEvidenceProviderSelection>(
    defaultExternalEvidenceProviderSelection
  );
  return (
    <MemoryRouter>
      <ExternalEvidenceProviderSelector
        idPrefix="test-provider"
        value={selection}
        onChange={setSelection}
        openssfApplicable={openssfApplicable}
      />
      <output data-testid="selection">{JSON.stringify(providerSelectionPayload(selection))}</output>
    </MemoryRouter>
  );
}

describe("ExternalEvidenceProviderSelector", () => {
  it("defaults all applicable providers on and maps each checkbox to one field", () => {
    render(<SelectorHarness />);

    const osv = screen.getByRole("checkbox", { name: /OSV/i });
    const depsDev = screen.getByRole("checkbox", { name: /deps\.dev/i });
    const openssf = screen.getByRole("checkbox", { name: /OpenSSF Scorecard/i });
    expect(osv).toBeChecked();
    expect(depsDev).toBeChecked();
    expect(openssf).toBeChecked();

    fireEvent.click(osv);
    expect(screen.getByTestId("selection")).toHaveTextContent(
      JSON.stringify({
        external_evidence_providers: { osv: false, deps_dev: true, openssf: true },
      })
    );

    fireEvent.click(depsDev);
    expect(screen.getByTestId("selection")).toHaveTextContent(
      JSON.stringify({
        external_evidence_providers: { osv: false, deps_dev: false, openssf: true },
      })
    );

    fireEvent.click(openssf);
    expect(screen.getByTestId("selection")).toHaveTextContent(
      JSON.stringify({
        external_evidence_providers: { osv: false, deps_dev: false, openssf: false },
      })
    );
  });

  it("marks OpenSSF not applicable for archives and exposes the privacy disclosure", () => {
    render(<SelectorHarness openssfApplicable={false} />);

    const openssf = screen.getByRole("checkbox", { name: /OpenSSF Scorecard/i });
    expect(openssf).toBeDisabled();
    expect(screen.getByText(/Not applicable to archive uploads/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Running this scan sends the documented repository\/package coordinates to the selected providers/i
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Privacy policy/i })).toHaveAttribute(
      "href",
      "/privacy"
    );
  });

  it("returns a fresh default selection for each execution surface", () => {
    const first = defaultExternalEvidenceProviderSelection();
    const second = defaultExternalEvidenceProviderSelection();
    first.osv = false;
    expect(second).toEqual({ osv: true, deps_dev: true, openssf: true });
    expect(vi.isMockFunction(defaultExternalEvidenceProviderSelection)).toBe(false);
  });
});
