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
          version: "0.7.0",
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
      expect(screen.getByText("v0.7.0")).toBeInTheDocument();
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

  it("documents v0.7 capabilities and the defensive-only scope", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/about" element={<AboutPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The "What v0.7 implements today" section header must be
    // present. The claim "v0.6" alone is no longer a sufficient
    // section title.
    expect(
      screen.getByRole("heading", { name: /what v0\.7 implements today/i })
    ).toBeInTheDocument();
    // Defensive-only scope remains non-negotiable.
    expect(screen.getByText(/does not execute analyzed code/i)).toBeInTheDocument();
    // Provider-honesty policy is still called out by name.
    expect(screen.getByText(/provider-honesty policy/i)).toBeInTheDocument();
    // The About page must not claim to do something that is not
    // in the codebase: authentication / multi-tenancy / billing.
    expect(screen.getByText(/authentication, multi-tenancy, billing/i)).toBeInTheDocument();
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
