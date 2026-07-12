import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DetailsDrawer } from "@/components/DetailsDrawer";

describe("DetailsDrawer", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <DetailsDrawer open={false} title="t" onClose={() => undefined}>
        <p>hidden</p>
      </DetailsDrawer>
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the title and children when open", () => {
    render(
      <DetailsDrawer open title="Details" onClose={() => undefined}>
        <p>Hello</p>
      </DetailsDrawer>
    );
    expect(screen.getByRole("dialog", { name: /details/i })).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("invokes the close handler when the user presses Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <DetailsDrawer open title="Details" onClose={onClose}>
        <p>Body</p>
      </DetailsDrawer>
    );
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("invokes the close handler when the user clicks the close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <DetailsDrawer open title="Details" onClose={onClose}>
        <p>Body</p>
      </DetailsDrawer>
    );
    await user.click(screen.getByRole("button", { name: /close details/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
