import { useEffect, useState } from "react";

import { api } from "@/api/api";
import type { ProviderName, ProviderObservation } from "@/api/types";

export function useProviderObservation(
  scanId: number,
  provider: ProviderName
): ProviderObservation | null {
  const [observation, setObservation] = useState<ProviderObservation | null>(null);

  useEffect(() => {
    if (!Number.isFinite(scanId)) return;
    const controller = new AbortController();
    setObservation(null);
    api
      .listProviderObservations(scanId, {
        page: 1,
        page_size: 200,
        provider,
      })
      .then((response) => {
        if (controller.signal.aborted) return;
        setObservation(response.items.at(-1) ?? null);
      })
      .catch(() => {
        if (!controller.signal.aborted) setObservation(null);
      });
    return () => controller.abort();
  }, [provider, scanId]);

  return observation;
}

export function providerWasDisabledByOperator(
  observation: ProviderObservation | null
): boolean {
  return (
    observation?.status === "not_requested" &&
    observation.error_code === "disabled_by_operator"
  );
}
