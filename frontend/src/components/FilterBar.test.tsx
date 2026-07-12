import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterBar, SelectFilter } from "@/components/FilterBar";

describe("FilterBar", () => {
  it("renders the search input and notifies the caller on changes", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    render(
      <FilterBar
        search=""
        onSearchChange={onSearch}
        searchPlaceholder="Search…"
      />
    );
    const input = screen.getByPlaceholderText(/search/i);
    await user.type(input, "x");
    expect(onSearch).toHaveBeenCalled();
  });

  it("renders a result count when provided", () => {
    render(
      <FilterBar
        search=""
        onSearchChange={() => undefined}
        resultCount={42}
        resultLabel="results"
      />
    );
    expect(screen.getByText(/42 results/)).toBeInTheDocument();
  });

  it("renders a clear button only when onClear is set", () => {
    const onClear = vi.fn();
    render(
      <FilterBar
        search="something"
        onSearchChange={() => undefined}
        onClear={onClear}
      />
    );
    expect(screen.getByRole("button", { name: /clear filters/i })).toBeInTheDocument();
  });

  it("does not render a clear button when onClear is not set", () => {
    render(<FilterBar search="" onSearchChange={() => undefined} />);
    expect(screen.queryByRole("button", { name: /clear filters/i })).not.toBeInTheDocument();
  });
});

describe("SelectFilter", () => {
  it("renders a labelled select and notifies on change", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SelectFilter
        id="severity"
        label="Severity"
        value="all"
        onChange={onChange}
        options={[
          { value: "all", label: "All" },
          { value: "high", label: "High" },
        ]}
      />
    );
    const select = screen.getByLabelText(/severity/i);
    expect(select).toBeInTheDocument();
    await user.selectOptions(select, "high");
    expect(onChange).toHaveBeenCalledWith("high");
  });
});
