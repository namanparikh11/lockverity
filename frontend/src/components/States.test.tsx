import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";

describe("EmptyState", () => {
  it("renders the title and description", () => {
    render(
      <EmptyState
        title="No repositories yet"
        description="Add a public GitHub repository to register it."
      />
    );
    expect(screen.getByText("No repositories yet")).toBeInTheDocument();
    expect(screen.getByText(/add a public github repository/i)).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renders the default title and the error message", () => {
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});

describe("LoadingState", () => {
  it("renders a polite status role with the loading label", () => {
    render(<LoadingState label="Loading scans" />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.textContent).toMatch(/Loading scans/);
  });
});
