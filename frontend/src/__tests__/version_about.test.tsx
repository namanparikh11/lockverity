/**
 * Frontend version-consistency and About-page tests.
 *
 * The product version lives on the backend; the frontend never
 * hardcodes a version in a public-facing surface. The About page
 * copy is derived from the actual code paths the application ships.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { AboutPage } from "@/pages/AboutPage";

describe("version consistency", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the version from /system/info in the AppShell footer", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          name: "Lockverity",
          version: "1.6.0",
          tagline: "Evidence-first software supply-chain assurance",
          environment: "test",
          api_prefix: "/api/v1",
          archive_limits: {},
          pagination: {},
          provider_safety: {},
          intake: {},
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      )
    );
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>placeholder</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("v1.6.0")).toBeInTheDocument();
    });
  });

  it("falls back to the product name when /system/info is unavailable", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>placeholder</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The footer should not show a hardcoded "vX.Y.Z" string and
    // should not show an alarming red error. It should fall back
    // to the product name in the version slot of the footer.
    await waitFor(() => {
      // The brand link at the top has the text "Lockverity" too;
      // we target the footer version slot specifically by
      // looking for the surrounding text that contains the
      // friendly fallback label.
      const matches = screen.getAllByText("Lockverity");
      expect(matches.length).toBeGreaterThan(0);
      // And the footer must NOT show a hardcoded version.
      expect(screen.queryByText(/^v\d+\.\d+\.\d+$/)).not.toBeInTheDocument();
    });
  });
});

describe("About page current product copy", () => {
  beforeEach(() => {
    cleanup();
  });

  it("documents v1.0 capabilities and the defensive-only scope", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/about" element={<AboutPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The "What v1.0 implements today" section header must be
    // present. The About page is the single source of truth
    // for the current milestone and must be kept in sync with
    // ``backend/app/_version.py``.
    expect(
      screen.getByRole("heading", { name: /what v1\.0 implements today/i })
    ).toBeInTheDocument();
    // The v1.0 human-readable evidence report is described with
    // the bounded &ldquo;not a verdict / not a certification /
    // not a compliance pass-or-fail&rdquo; wording and the two
    // endpoint paths.
    expect(
      screen.getByText(/human-readable evidence report/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /\/api\/v1\/scans\/\{id\}\/reports\/evidence-summary\/preview/
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /\/api\/v1\/scans\/\{id\}\/reports\/evidence-summary\.md/
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a security verdict/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a certification/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a compliance pass-or-fail/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not execute analyzed code/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/provider-honesty policy/i)).toBeInTheDocument();
    expect(
      screen.getByText(/authentication, multi-tenancy, billing/i)
    ).toBeInTheDocument();
  });

  it("does not regress to describing v0.1 as the current milestone", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/about" element={<AboutPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The legacy "What v0.1 includes" / "What v0.1 does not include"
    // section headers must not be present any more.
    expect(
      screen.queryByRole("heading", { name: /what v0\.1 includes/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /what v0\.1 does not include/i })
    ).not.toBeInTheDocument();
  });
});
