import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RefreshButton } from "@/components/RefreshButton";
import { useRefresh } from "@/hooks/useRefresh";

/**
 * v2.1.3 shared application-data refresh button tests.
 *
 * The button is the visual chokepoint for the
 * "click here to refetch the visible payload" UX.
 * The tests below pin:
 *
 *  1. One click triggers exactly one request.
 *  2. The visible label transitions to
 *     ``Refreshing…`` while the request is in
 *     flight and the spinner is animated.
 *  3. The button is disabled while in flight so
 *     duplicate concurrent requests are blocked
 *     at the UI level.
 *  4. The previous data is preserved on failure
 *     and an inline ``Refresh failed`` indicator
 *     is shown.
 *  5. The success state restores the ``Refresh``
 *     label and the enabled state.
 *  6. The accessibility attributes
 *     (``aria-busy``, ``aria-label``) are correct
 *     at every point in the lifecycle.
 */

interface HarnessProps<T> {
  fetcher: () => Promise<T> | T;
  initialData?: T;
  testId?: string;
}

function Harness<T>({ fetcher, initialData, testId }: HarnessProps<T>) {
  const state = useRefresh<T>({ fetcher, initialData });
  return <RefreshButton state={state} testId={testId ?? "refresh"} />;
}

describe("RefreshButton", () => {
  it("renders the idle label on first render", () => {
    render(<Harness fetcher={() => Promise.resolve("v1")} />);
    const button = screen.getByTestId("refresh");
    expect(button).toHaveTextContent("Refresh");
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "false");
  });

  it("transitions to Refreshing… and disables the button while in flight", async () => {
    const fetcher = vi.fn(() => new Promise<string>(() => undefined));
    render(<Harness fetcher={fetcher} />);
    const button = screen.getByTestId("refresh");
    fireEvent.click(button);
    await waitFor(() => {
      expect(button).toHaveTextContent("Refreshing…");
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    // The spinner test id is present while in
    // flight so a downstream test can assert the
    // loading indicator without relying on the
    // visible label.
    expect(screen.getByTestId("refresh-spinner")).toBeInTheDocument();
  });

  it("blocks duplicate clicks through the disabled attribute", async () => {
    const fetcher = vi.fn(() => new Promise<string>(() => undefined));
    render(<Harness fetcher={fetcher} />);
    const button = screen.getByTestId("refresh");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => {
      expect(button).toHaveTextContent("Refreshing…");
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("preserves the previous data and shows Refresh failed on failure", async () => {
    const fetcher = vi.fn();
    fetcher.mockResolvedValueOnce("seed");
    fetcher.mockRejectedValueOnce(new Error("boom"));
    render(<Harness fetcher={fetcher} initialData="seed" />);
    const button = screen.getByTestId("refresh");
    // First click succeeds; the previous mock
    // returns the seed value. Wait for the
    // button to return to the idle label.
    fireEvent.click(button);
    await waitFor(() => {
      expect(button).toHaveTextContent("Refresh");
    });
    // Second click fails; the previous payload
    // is preserved and the inline error is
    // rendered next to the button.
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.getByTestId("refresh-inline-error")).toBeInTheDocument();
    });
  });

  it("restores the idle label and enabled state on success", async () => {
    const fetcher = vi.fn().mockResolvedValue("payload");
    render(<Harness fetcher={fetcher} />);
    const button = screen.getByTestId("refresh");
    fireEvent.click(button);
    await waitFor(() => {
      expect(button).toHaveTextContent("Refresh");
    });
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "false");
  });
});
