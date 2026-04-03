import type {
  CategoriesResponse,
  ClearIngestionResponse,
  HealthResponse,
  IngestionResult,
  RecommendationResult,
  StreamChunk,
} from "./types";

export async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
}

export async function parseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }

  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((entry) => (typeof entry?.msg === "string" ? entry.msg : JSON.stringify(entry)))
        .join("; ");
    }
    return JSON.stringify(parsed);
  } catch {
    return text;
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health", { method: "GET" });
}

export async function fetchCategories(): Promise<CategoriesResponse> {
  return requestJson<CategoriesResponse>("/ingest_products/categories", { method: "GET" });
}

export async function ingestWithJson(payload: unknown): Promise<IngestionResult> {
  return requestJson<IngestionResult>("/ingest_products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function ingestWithFile(file: File): Promise<IngestionResult> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/ingest_products", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return (await response.json()) as IngestionResult;
}

export async function clearIngestion(): Promise<ClearIngestionResponse> {
  return requestJson<ClearIngestionResponse>("/ingest_products", { method: "DELETE" });
}

export async function recommend(payload: unknown): Promise<RecommendationResult> {
  return requestJson<RecommendationResult>("/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function recommendStream(
  payload: unknown,
  onChunk: (chunk: StreamChunk) => void
): Promise<void> {
  const response = await fetch("/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  if (!response.body) {
    throw new Error("Streaming is not available in this environment.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }

      try {
        const parsed = JSON.parse(trimmed) as StreamChunk;
        onChunk(parsed);
      } catch {
        // Ignore malformed chunks to keep stream resilient.
      }
    }
  }

  if (buffer.trim()) {
    try {
      onChunk(JSON.parse(buffer) as StreamChunk);
    } catch {
      // Ignore trailing malformed line.
    }
  }
}
