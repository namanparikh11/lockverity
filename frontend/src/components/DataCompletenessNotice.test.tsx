import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";

describe("DataCompletenessNotice", () => {
  it("renders a status role with the title and description", () => {
    render(
      <DataCompletenessNotice
        title="Some data is unavailable"
        description="The vulnerability provider was rate limited."
      />
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/some data is unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/vulnerability provider was rate limited/i)).toBeInTheDocument();
  });

  it("renders extra children below the description", () => {
    render(
      <DataCompletenessNotice title="List">
        <ul>
          <li>item</li>
        </ul>
      </DataCompletenessNotice>
    );
    expect(screen.getByText("item")).toBeInTheDocument();
  });
});
