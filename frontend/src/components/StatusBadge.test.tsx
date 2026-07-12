import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/StatusBadge";

describe("StatusBadge", () => {
  it("renders the status text on screen", () => {
    render(<StatusBadge status="available" />);
    expect(screen.getByText("available")).toBeInTheDocument();
  });

  it("uses an aria-label that includes the status word", () => {
    render(<StatusBadge status="unavailable" />);
    expect(screen.getByLabelText(/unavailable/i)).toBeInTheDocument();
  });

  it("falls back to the status word when no children are passed", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("queued")).toBeInTheDocument();
  });

  it("renders children instead of the status when provided", () => {
    render(<StatusBadge status="completed">Done</StatusBadge>);
    expect(screen.getByText("Done")).toBeInTheDocument();
  });
});
