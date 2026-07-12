/**
 * Centralised helpers for the scan stage timeline. Kept in a
 * non-component module so the timeline component module only
 * exports components, which keeps fast refresh and tree
 * shaking happy.
 */

import type { StageStatus, StageType } from "@/api/types";

/**
 * Stable, human-readable label for a stage type. Centralised so
 * the dashboard, scan detail, and exports can all share the same
 * vocabulary.
 */
export function stageTypeLabel(stage: StageType): string {
  switch (stage) {
    case "repository_intake":
      return "Repository intake";
    case "archive_validation":
      return "Archive validation";
    case "manifest_discovery":
      return "Manifest discovery";
    case "dependency_parsing":
      return "Dependency parsing";
    case "dependency_enrichment":
      return "Dependency enrichment";
    case "vulnerability_query":
      return "Vulnerability query";
    case "workflow_analysis":
      return "Workflow analysis";
    case "repository_posture":
      return "Repository posture";
    case "finding_reconciliation":
      return "Finding reconciliation";
    case "export_generation":
      return "Export generation";
    default:
      return stage;
  }
}

/**
 * Helper used on the dashboard: given a list of stages, return
 * the affected "downstream" stage types that were not run
 * because an earlier stage failed. The function is a best
 * effort - if the backend does not encode the pipeline order,
 * the caller should still display the raw `stages` list.
 */
export function downstreamStagesAffected(
  stages: { stage_type: StageType; status: StageStatus }[],
  failedStageType: StageType
): StageType[] {
  const order: StageType[] = [
    "repository_intake",
    "archive_validation",
    "manifest_discovery",
    "dependency_parsing",
    "dependency_enrichment",
    "vulnerability_query",
    "workflow_analysis",
    "repository_posture",
    "finding_reconciliation",
    "export_generation",
  ];
  const failedIndex = order.indexOf(failedStageType);
  if (failedIndex < 0) return [];
  const downstream = order.slice(failedIndex + 1);
  const skipped = new Set<StageType>();
  for (const stage of stages) {
    if (stage.status === "skipped") skipped.add(stage.stage_type);
  }
  return downstream.filter((s) => skipped.has(s));
}
