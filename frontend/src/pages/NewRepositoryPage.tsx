import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/api";
import { ApiClientError } from "@/api/client";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";

export function NewRepositoryPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const repo = await api.createRepository(url.trim());
      navigate(`/repositories/${repo.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Add repository"
        description="Register a public GitHub repository for analysis. The URL is normalized to a canonical form and no code is fetched or executed."
        breadcrumbs={[
          { label: "Repositories", to: "/repositories" },
          { label: "New" },
        ]}
      />
      <form
        onSubmit={handleSubmit}
        className="card max-w-2xl space-y-4"
        aria-label="Add repository form"
      >
        <div>
          <label htmlFor="canonical_url" className="label">
            Public GitHub URL
          </label>
          <input
            id="canonical_url"
            name="canonical_url"
            type="url"
            required
            inputMode="url"
            placeholder="https://github.com/owner/repository"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="input mt-1"
            autoComplete="off"
            aria-describedby="url-help"
          />
          <p id="url-help" className="mt-1 text-xs text-ink-500">
            Only <code>https://github.com/owner/name</code> and the
            <code> .git</code> variant are accepted. Credentials, extra path
            segments, fragments, and query strings are rejected.
          </p>
        </div>
        {error ? (
          <div role="alert">
            {error instanceof ApiClientError ? (
              <ErrorState
                error={error}
                title={`Could not add repository (${error.apiError.code})`}
              />
            ) : (
              <ErrorState error={error} title="Could not add repository" />
            )}
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => navigate("/repositories")}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={submitting || !url.trim()}
          >
            {submitting ? "Adding..." : "Add repository"}
          </button>
        </div>
      </form>
      <div className="mt-4 max-w-2xl">
        <DataCompletenessNotice
          title="What happens next"
          description="A repository is a database record. Lockverity v0.1 does not download code, does not run providers, and does not produce findings. The scan lifecycle endpoints exist for future integration."
        />
      </div>
    </>
  );
}
