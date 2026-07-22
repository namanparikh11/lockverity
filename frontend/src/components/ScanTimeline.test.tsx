import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScanTimeline, PipelineSummary, PipelineFailureAlert } from "@/components/ScanTimeline";
import type { ScanStage } from "@/api/types";

function stage(overrides: Partial<ScanStage> = {}): ScanStage {
  return {
    id: 1,
    scan_run_id: 1,
    stage_type: "repository_intake",
    status: "completed",
    started_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T00:00:10Z",
    provider: null,
    provider_status: null,
    records_processed: 0,
    failure_code: null,
    failure_summary: null,
    message_severity: "none",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:10Z",
    ...overrides,
  };
}

describe("ScanTimeline", () => {
  it("renders nothing useful when stages are empty", () => {
    render(<ScanTimeline stages={[]} />);
    expect(screen.getByText(/no stages recorded/i)).toBeInTheDocument();
  });

  it("renders the human label for each stage", () => {
    render(
      <ScanTimeline
        stages={[
          stage({ id: 1, stage_type: "repository_intake" }),
          stage({ id: 2, stage_type: "vulnerability_query" }),
        ]}
      />
    );
    expect(screen.getByText("Repository intake")).toBeInTheDocument();
    expect(screen.getByText("Vulnerability query")).toBeInTheDocument();
  });

  it("surfaces the failure summary inside a status block", () => {
    render(
      <ScanTimeline
        stages={[
          stage({ id: 1, status: "failed", failure_code: "EBOOM", failure_summary: "Rate limited", message_severity: "error" }),
        ]}
      />
    );
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
    expect(screen.getByText("EBOOM")).toBeInTheDocument();
  });
});

describe("PipelineSummary", () => {
  it("renders an empty-state hint when stages are empty", () => {
    render(<PipelineSummary stages={[]} />);
    expect(screen.getByText(/no stages/i)).toBeInTheDocument();
  });

  it("renders one badge per distinct non-zero status", () => {
    render(
      <PipelineSummary
        stages={[
          stage({ id: 1, status: "completed" }),
          stage({ id: 2, status: "completed" }),
          stage({ id: 3, status: "failed" }),
        ]}
      />
    );
    expect(screen.getByLabelText(/pipeline status counts/i)).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});

describe("PipelineFailureAlert", () => {
  it("renders nothing when no stages are failed", () => {
    const { container } = render(
      <PipelineFailureAlert
        stages={[stage({ id: 1, status: "completed" })]}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a single-stage failure message", () => {
    render(
      <PipelineFailureAlert
        stages={[
          stage({ id: 1, stage_type: "vulnerability_query", status: "failed", failure_summary: "Timeout" }),
        ]}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent(/1 stage failed/i);
    expect(alert).toHaveTextContent("Vulnerability query");
    expect(alert).toHaveTextContent("Timeout");
  });

  it("renders a pluralised message when more than one stage failed", () => {
    render(
      <PipelineFailureAlert
        stages={[
          stage({ id: 1, status: "failed", failure_summary: "A" }),
          stage({ id: 2, stage_type: "vulnerability_query", status: "failed", failure_summary: "B" }),
        ]}
      />
    );
    expect(screen.getByText(/2 stages failed/i)).toBeInTheDocument();
  });
});
