import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Notification } from "@/components/Notification";

describe("Notification", () => {
  it("renders an alert role for danger notifications", () => {
    render(
      <Notification
        tone="danger"
        title="Could not load"
        description="boom"
        dismissible={false}
      />
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Could not load")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("renders a status role for ok notifications", () => {
    render(
      <Notification tone="ok" title="Saved" dismissible={false} />
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("includes a screen-reader-only tone label", () => {
    render(<Notification tone="warn" title="Heads up" dismissible={false} />);
    expect(screen.getByText(/warning:/i)).toBeInTheDocument();
  });

  it("renders a dismiss button when dismissible", () => {
    render(<Notification tone="info" title="Heads up" onDismiss={() => undefined} />);
    expect(screen.getByRole("button", { name: /dismiss notification/i })).toBeInTheDocument();
  });
});
