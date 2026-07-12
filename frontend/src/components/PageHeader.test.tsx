import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "@/components/PageHeader";

describe("PageHeader", () => {
  it("renders the title as a heading", () => {
    render(<PageHeader title="Repositories" />);
    expect(screen.getByRole("heading", { name: "Repositories" })).toBeInTheDocument();
  });

  it("renders breadcrumbs with the last crumb as text", () => {
    render(
      <PageHeader
        title="Add repository"
        breadcrumbs={[
          { label: "Repositories", to: "/repositories" },
          { label: "New" },
        ]}
      />
    );
    const nav = screen.getByRole("navigation", { name: /breadcrumb/i });
    expect(nav).toBeInTheDocument();
    const newCrumb = screen.getByText("New");
    expect(newCrumb.tagName).toBe("SPAN");
  });

  it("renders description and actions when provided", () => {
    render(
      <PageHeader
        title="Scans"
        description="Recent scans across all repositories."
        actions={<button type="button">Queue scan</button>}
      />
    );
    expect(screen.getByText(/recent scans across all repositories/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /queue scan/i })).toBeInTheDocument();
  });
});
