/**
 * LockveritySymbol component tests.
 *
 * The component renders the approved standalone product
 * symbol from ``frontend/public/brand/lockverity-symbol.png``.
 * The tests guard the component shape, the accessibility
 * defaults, the size prop, and the data-testid used by the
 * AppShell and About page.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LockveritySymbol } from "@/components/LockveritySymbol";

describe("LockveritySymbol", () => {
  it("renders the approved symbol source PNG with the expected testid", () => {
    render(<LockveritySymbol />);
    const img = screen.getByTestId("lockverity-symbol");
    expect(img).toBeInTheDocument();
    expect(img.tagName).toBe("IMG");
  });

  it("hides the symbol from the accessibility tree when decorative", () => {
    render(<LockveritySymbol decorative />);
    const img = screen.getByTestId("lockverity-symbol");
    expect(img).toHaveAttribute("aria-hidden", "true");
  });

  it("labels the symbol when not decorative", () => {
    render(<LockveritySymbol ariaLabel="Lockverity product symbol" />);
    const img = screen.getByTestId("lockverity-symbol");
    expect(img).toHaveAttribute("aria-label", "Lockverity product symbol");
    expect(img).not.toHaveAttribute("aria-hidden");
  });

  it("renders the configured size as width and height", () => {
    render(<LockveritySymbol size={64} />);
    const img = screen.getByTestId("lockverity-symbol");
    expect(img).toHaveAttribute("width", "64");
    expect(img).toHaveAttribute("height", "64");
  });

  it("references the approved source PNG path", () => {
    render(<LockveritySymbol />);
    const img = screen.getByTestId("lockverity-symbol");
    expect(img.getAttribute("src")).toBe("/brand/lockverity-symbol.png");
  });
});
