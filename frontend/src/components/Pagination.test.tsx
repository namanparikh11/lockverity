import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Pagination } from "@/components/Pagination";

const META = { page: 2, page_size: 10, total: 30, total_pages: 3 };

describe("Pagination", () => {
  it("renders nothing when total is zero", () => {
    const { container } = render(
      <Pagination
        meta={{ page: 1, page_size: 10, total: 0, total_pages: 0 }}
        onPageChange={() => undefined}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the current page indicator", () => {
    render(<Pagination meta={META} onPageChange={() => undefined} />);
    const nav = screen.getByRole("navigation", { name: /pagination/i });
    expect(nav).toHaveTextContent(/Page\s*2\s*of\s*3/);
    expect(nav).toHaveTextContent(/30\s*items/);
  });

  it("disables the previous button on the first page", () => {
    render(
      <Pagination
        meta={{ ...META, page: 1 }}
        onPageChange={() => undefined}
      />
    );
    expect(
      screen.getByRole("button", { name: /previous page/i })
    ).toBeDisabled();
  });

  it("disables the next button on the last page", () => {
    render(
      <Pagination
        meta={{ ...META, page: 3 }}
        onPageChange={() => undefined}
      />
    );
    expect(
      screen.getByRole("button", { name: /next page/i })
    ).toBeDisabled();
  });

  it("invokes onPageChange with the next page number", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<Pagination meta={META} onPageChange={onPageChange} />);
    await user.click(screen.getByRole("button", { name: /next page/i }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });
});
