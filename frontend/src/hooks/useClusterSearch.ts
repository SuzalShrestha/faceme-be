import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";

export type ClusterSummary = {
  id: number;
  label: string | null;
  face_count: number;
  representative_url?: string | null;
};

async function fetchClusters(search: string, signal?: AbortSignal): Promise<ClusterSummary[]> {
  const params = search ? `?search=${encodeURIComponent(search)}` : "";
  const response = await fetch(`/api/clusters${params}`, {
    credentials: "include",
    signal,
  });
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(message || `Failed to fetch clusters (${response.status})`);
  }
  return response.json();
}

function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

export function useClusterSearch(initialSearch = ""): UseQueryResult<ClusterSummary[]> & {
  search: string;
  setSearch: (next: string) => void;
  debouncedSearch: string;
} {
  const [search, setSearch] = useState(initialSearch);
  const debouncedSearch = useDebouncedValue(search, 350);

  const normalizedSearch = useMemo(() => debouncedSearch.trim(), [debouncedSearch]);

  const query = useQuery({
    queryKey: ["clusters", normalizedSearch.toLowerCase()],
    queryFn: ({ signal }) => fetchClusters(normalizedSearch, signal),
    staleTime: 30_000,
    gcTime: 300_000,
    placeholderData: keepPreviousData,
  });

  return {
    ...query,
    search,
    setSearch,
    debouncedSearch: normalizedSearch,
  };
}
