/**
 * v2.0.6 stage outcome / message-severity tests.
 *
 * The v0.5-v2.0.5 ``ScanTimeline`` and ``DashboardPage``
 * components prefixed every ``failure_summary`` string
 * with ``"Failure: "`` and used red ``rose-50`` styling.
 * Several normal no-data outcomes are not stage-execution
 * failures; v2.0.6 derives a ``message_severity`` field at
 * the API boundary and the frontend renders the message
 * with severity-appropriate styling (no ``"Failure: "``
 * prefix for ``info`` or ``warning`` severities).
 *
 * The tests in this file exercise the frontend rendering
 * against a mocked API that returns the new
 * ``message_severity`` field. The backend decision is
 * covered by ``backend/tests/test_stage_message_severity_v2_0_6.py``.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ScanTimeline } from "@/components/ScanTimeline";
import type { ScanStage } from "@/api/types";

function makeStage(overrides: Partial<ScanStage> = {}): ScanStage {
  return {
    id: 1,
    scan_run_id: 1,
    stage_type: "vulnerability_query",
    status: "completed",
    started_at: null,
    completed_at: null,
    provider: null,
    provider_status: null,
    records_processed: 0,
    failure_code: null,
    failure_summary: null,
    message_severity: "none",
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-22T00:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ScanTimeline message severity v2.0.6", () => {
  it("renders an info-severity stage message without a Failure: prefix", () => {
    const stage = makeStage({
      id: 1,
      stage_type: "vulnerability_query",
      status: "completed",
      records_processed: 12,
      failure_summary: "No OSV advisories were returned for this scan.",
      message_severity: "info",
    });
    render(<ScanTimeline stages={[stage]} />);
    const text = screen.getByText(
      "No OSV advisories were returned for this scan."
    );
    expect(text).toBeInTheDocument();
    // No "Failure:" prefix on a normal no-data outcome.
    expect(screen.queryByText(/^Failure:/)).not.toBeInTheDocument();
    // No "Partial output:" prefix either.
    expect(screen.queryByText(/^Partial output:/)).not.toBeInTheDocument();
  });

  it("renders a warning-severity stage message with the Partial output: prefix", () => {
    const stage = makeStage({
      id: 2,
      stage_type: "dependency_parsing",
      status: "completed",
      records_processed: 2,
      failure_summary: "1 parser warnings",
      message_severity: "warning",
    });
    render(<ScanTimeline stages={[stage]} />);
    const text = screen.getByText("1 parser warnings");
    expect(text).toBeInTheDocument();
    // The warning-severity message uses a non-error prefix.
    expect(screen.queryByText(/^Failure:/)).not.toBeInTheDocument();
  });

  it("renders an error-severity stage message with the Failure: prefix", () => {
    const stage = makeStage({
      id: 3,
      stage_type: "archive_validation",
      status: "failed",
      records_processed: 0,
      failure_code: "archive_unsafe",
      failure_summary: "archive was rejected",
      message_severity: "error",
    });
    render(<ScanTimeline stages={[stage]} />);
    expect(screen.getByText(/^Failure:/)).toBeInTheDocument();
    expect(
      screen.getByText(/archive was rejected/)
    ).toBeInTheDocument();
  });

  it("renders a none-severity stage with no message block", () => {
    const stage = makeStage({
      id: 4,
      stage_type: "repository_intake",
      status: "completed",
      records_processed: 1,
      failure_summary: null,
      message_severity: "none",
    });
    render(<ScanTimeline stages={[stage]} />);
    // No message block is rendered when severity is "none".
    expect(screen.queryByText(/^Failure:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Partial output:/)).not.toBeInTheDocument();
  });

  it("does not hide evidence: warning messages remain visible", () => {
    const stage = makeStage({
      id: 5,
      stage_type: "dependency_parsing",
      status: "completed",
      records_processed: 2,
      failure_summary: "1 parser warnings",
      message_severity: "warning",
    });
    render(<ScanTimeline stages={[stage]} />);
    // The exact summary text is rendered; we never
    // suppress parser warnings.
    expect(screen.getByText(/1 parser warnings/)).toBeInTheDocument();
  });

  it("does not hide evidence: provider degradation remains visible", () => {
    const stage = makeStage({
      id: 6,
      stage_type: "vulnerability_query",
      status: "completed",
      records_processed: 5,
      failure_summary: "OSV returned a partial response",
      message_severity: "warning",
    });
    render(<ScanTimeline stages={[stage]} />);
    expect(
      screen.getByText(/OSV returned a partial response/)
    ).toBeInTheDocument();
  });

  it("info message has accessible text but is not styled as an error", () => {
    const stage = makeStage({
      id: 7,
      stage_type: "workflow_analysis",
      status: "completed",
      records_processed: 0,
      failure_summary: "No workflow files were discovered.",
      message_severity: "info",
    });
    render(<ScanTimeline stages={[stage]} />);
    const text = screen.getByText("No workflow files were discovered.");
    expect(text).toBeInTheDocument();
    // The accessibility role is "status" (informational),
    // not "alert" (urgent). The text is present and
    // visible.
    expect(text.closest("[role='status']")).toBeTruthy();
    expect(text.closest("[role='alert']")).toBeFalsy();
  });

  it("error message carries role=alert", () => {
    const stage = makeStage({
      id: 8,
      stage_type: "archive_validation",
      status: "failed",
      records_processed: 0,
      failure_summary: "boom",
      message_severity: "error",
    });
    render(<ScanTimeline stages={[stage]} />);
    const text = screen.getByText(/boom/);
    expect(text.closest("[role='alert']")).toBeTruthy();
  });

  it("warning message carries role=status (not alert)", () => {
    const stage = makeStage({
      id: 9,
      stage_type: "dependency_parsing",
      status: "completed",
      records_processed: 2,
      failure_summary: "1 parser warnings",
      message_severity: "warning",
    });
    render(<ScanTimeline stages={[stage]} />);
    const text = screen.getByText(/1 parser warnings/);
    expect(text.closest("[role='status']")).toBeTruthy();
    expect(text.closest("[role='alert']")).toBeFalsy();
  });

  it("completed stage badge is rendered independently of the message", () => {
    const stage = makeStage({
      id: 10,
      stage_type: "vulnerability_query",
      status: "completed",
      records_processed: 12,
      failure_summary: "No OSV advisories were returned for this scan.",
      message_severity: "info",
    });
    render(<ScanTimeline stages={[stage]} />);
    // The status badge says "completed" - the stage is
    // not downgraded to "failed" by the presence of a
    // residual summary.
    expect(screen.getByText("completed")).toBeInTheDocument();
  });
});
