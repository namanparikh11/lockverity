import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CodeLocation } from "@/components/CodeLocation";
import { ComponentIdentity, DependencyPathView } from "@/components/DependencyPath";
import type { Component, DependencyPath } from "@/api/types";

function component(overrides: Partial<Component> = {}): Component {
  return {
    id: 1,
    scan_run_id: 1,
    manifest_id: 1,
    ecosystem: "npm",
    package_name: "lodash",
    version: "4.17.21",
    version_source: "manifest",
    package_url: null,
    scope: null,
    relationship: null,
    direct: true,
    development: false,
    optional: false,
    integrity: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CodeLocation", () => {
  it("renders the file path", () => {
    render(<CodeLocation path="src/index.ts" startLine={10} endLine={12} />);
    expect(screen.getByText("src/index.ts")).toBeInTheDocument();
    expect(screen.getByText("L10–L12")).toBeInTheDocument();
  });

  it("renders just the start line when end is missing", () => {
    render(<CodeLocation path="src/index.ts" startLine={10} endLine={null} />);
    expect(screen.getByText("L10")).toBeInTheDocument();
  });

  it("renders no line when path is missing", () => {
    render(<CodeLocation path={null} startLine={null} endLine={null} />);
    expect(screen.getByText(/no file location/i)).toBeInTheDocument();
  });

  it("renders a view-source link when canonicalUrl is provided", () => {
    render(
      <CodeLocation
        path="src/index.ts"
        startLine={1}
        endLine={1}
        canonicalUrl="https://example.com/file"
      />
    );
    const link = screen.getByText(/view source/i);
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe("https://example.com/file");
  });
});

describe("ComponentIdentity", () => {
  it("renders package, ecosystem, and version", () => {
    render(<ComponentIdentity component={component()} />);
    expect(screen.getByText("npm:lodash")).toBeInTheDocument();
    expect(screen.getByText(/4\.17\.21/)).toBeInTheDocument();
  });

  it("renders '(version unknown)' when version is missing", () => {
    render(<ComponentIdentity component={component({ version: null })} />);
    expect(screen.getByText(/version unknown/i)).toBeInTheDocument();
  });
});

describe("DependencyPathView", () => {
  it("returns nothing for a null path by default", () => {
    const { container } = render(<DependencyPathView path={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the fallback when fallbackToSingle is set", () => {
    render(<DependencyPathView path={null} fallbackToSingle />);
    expect(screen.getByText(/no dependency path recorded/i)).toBeInTheDocument();
  });

  it("renders a chain of components in order", () => {
    const path: DependencyPath = {
      components: [component({ id: 1, package_name: "app", direct: true }), component({ id: 2, package_name: "left-pad", direct: false })],
      edges: [],
      truncated: false,
    };
    render(<DependencyPathView path={path} />);
    expect(screen.getByText("npm:app")).toBeInTheDocument();
    expect(screen.getByText("npm:left-pad")).toBeInTheDocument();
  });

  it("surfaces the truncation indicator", () => {
    const path: DependencyPath = {
      components: [component({ id: 1 })],
      edges: [],
      truncated: true,
    };
    render(<DependencyPathView path={path} />);
    expect(screen.getByText(/truncated by the analyzer/i)).toBeInTheDocument();
  });
});
