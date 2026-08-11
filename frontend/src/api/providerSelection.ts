import type {
  ExternalEvidenceProviderSelection,
  ScanRunPayload,
} from "@/api/types";

export function defaultExternalEvidenceProviderSelection(): ExternalEvidenceProviderSelection {
  return { osv: true, deps_dev: true, openssf: true };
}

export function providerSelectionPayload(
  value: ExternalEvidenceProviderSelection
): ScanRunPayload {
  return { external_evidence_providers: { ...value } };
}
