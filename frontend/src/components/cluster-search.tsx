import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useClusterSearch } from "../hooks/useClusterSearch";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 300_000,
      refetchOnWindowFocus: false,
    },
  },
});

function ClusterSearchBody() {
  const { search, setSearch, data, isFetching, error } = useClusterSearch();

  return (
    <div style={{ display: "grid", gap: "0.5rem", maxWidth: 480 }}>
      <label htmlFor="cluster-search">Search clusters</label>
      <input
        id="cluster-search"
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Type a name…"
        style={{ padding: "0.5rem 0.75rem", borderRadius: 8, border: "1px solid #ccc" }}
      />
      {error ? (
        <div role="alert" style={{ color: "#b91c1c" }}>
          {(error as Error).message}
        </div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {(data ?? []).map((cluster) => (
            <li key={cluster.id} style={{ padding: "0.35rem 0", borderBottom: "1px solid #eee" }}>
              <div style={{ fontWeight: 600 }}>{cluster.label || "Untitled cluster"}</div>
              <div style={{ fontSize: "0.85rem", color: "#555" }}>
                {cluster.face_count} face{cluster.face_count === 1 ? "" : "s"}
              </div>
            </li>
          ))}
          {!isFetching && (data ?? []).length === 0 && (
            <li style={{ color: "#555" }}>No clusters match that search.</li>
          )}
        </ul>
      )}
      {isFetching && <div style={{ fontSize: "0.85rem", color: "#555" }}>Loading…</div>}
    </div>
  );
}

export function ClusterSearch() {
  return (
    <QueryClientProvider client={queryClient}>
      <ClusterSearchBody />
    </QueryClientProvider>
  );
}
