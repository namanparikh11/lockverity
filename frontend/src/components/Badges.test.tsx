import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { ProviderStatusBadge } from "@/components/ProviderStatusBadge";
import { SeverityBadge } from "@/components/SeverityBadge";

describe("SeverityBadge", () => {
  it("renders each severity without relying on colour", () => {
    const severities = ["informational", "low", "medium", "high", "critical", "unknown"];
    for (const severity of severities) {
      render(<SeverityBadge severity={severity} />);
      expect(screen.getByText(severity)).toBeInTheDocument();
    }
  });

  it("keeps unknown visible as text", () => {
    render(<SeverityBadge severity="unknown" />);
    expect(screen.getByLabelText(/unknown/i)).toBeInTheDocument();
  });
});

describe("ConfidenceBadge", () => {
  it("renders each confidence value", () => {
    const confidences = ["low", "medium", "high", "confirmed", "unknown"];
    for (const confidence of confidences) {
      render(<ConfidenceBadge confidence={confidence} />);
      expect(screen.getByText(confidence)).toBeInTheDocument();
    }
  });
});

describe("ProviderStatusBadge", () => {
  it("renders each provider status", () => {
    const statuses = [
      "available",
      "partial",
      "rate_limited",
      "unavailable",
      "not_requested",
      "cached",
      "unknown",
    ];
    for (const status of statuses) {
      render(<ProviderStatusBadge status={status} />);
      expect(screen.getByText(status)).toBeInTheDocument();
    }
  });
});
