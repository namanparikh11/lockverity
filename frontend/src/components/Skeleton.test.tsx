import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Skeleton } from "@/components/Skeleton";

describe("Skeleton", () => {
  it("exposes a progressbar role with busy state", () => {
    render(<Skeleton rows={3} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-busy", "true");
    expect(bar).toHaveAttribute("aria-label", "Loading");
  });

  it("renders one placeholder per row", () => {
    const { container } = render(<Skeleton rows={5} />);
    const placeholders = container.querySelectorAll("[aria-hidden='true']");
    expect(placeholders.length).toBe(5);
  });
});
