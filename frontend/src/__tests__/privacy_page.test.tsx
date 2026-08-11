import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { PrivacyPage } from "@/pages/PrivacyPage";

describe("privacy page", () => {
  it("distinguishes local processing, required GitHub retrieval, and optional providers", () => {
    render(
      <MemoryRouter>
        <PrivacyPage />
      </MemoryRouter>
    );

    for (const heading of [
      "Local runtime and storage",
      "GitHub repository retrieval",
      "OSV",
      "deps.dev",
      "OpenSSF Scorecard",
      "Archive uploads",
      "Optional GitHub token",
      "Telemetry and analytics",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText(/retrieval is required for GitHub scans/i)).toBeInTheDocument();
    expect(screen.getByText(/does not include product telemetry/i)).toBeInTheDocument();
  });
});
