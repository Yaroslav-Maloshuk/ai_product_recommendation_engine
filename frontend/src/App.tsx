import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  clearIngestion,
  fetchCategories,
  fetchHealth,
  ingestWithFile,
  ingestWithJson,
  recommend,
  recommendStream,
} from "./lib/api";
import type { RecommendationFilters, RecommendationItem } from "./lib/types";

type ApiState = "loading" | "ok" | "error";

const STREAM_PENDING_SUMMARY = "Collecting streaming output...";

const initialJson = `[
  {
    "title": "Noise Cancelling Headphones",
    "description": "Wireless ANC headphones with 30h battery life",
    "category": "audio",
    "price": 199.99,
    "currency": "USD",
    "tags": ["wireless", "anc", "travel"]
  }
]`;

function parseOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const num = Number(trimmed);
  return Number.isFinite(num) ? num : undefined;
}

function toTagArray(raw: string): string[] | undefined {
  const tags = raw
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  return tags.length ? tags : undefined;
}

function toProfileValue(raw: string): Record<string, unknown> | undefined {
  const trimmed = raw.trim();
  if (!trimmed) {
    return undefined;
  }

  const looksLikeJson = trimmed.startsWith("{") || trimmed.startsWith("[");
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return { profile_text: trimmed };
  } catch {
    if (looksLikeJson) {
      throw new Error("User profile JSON is invalid.");
    }
    return { profile_text: trimmed };
  }
}

function formatPrice(price?: number | null, currency?: string | null): string {
  if (typeof price !== "number") {
    return "price unknown";
  }
  return currency ? `${price.toFixed(2)} ${currency}` : price.toFixed(2);
}

export default function App() {
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [apiMessage, setApiMessage] = useState(
    import.meta.env.DEV ? "API check is manual in dev mode." : "Checking API..."
  );

  const [productsJson, setProductsJson] = useState(initialJson);
  const [file, setFile] = useState<File | null>(null);
  const [ingestionMessage, setIngestionMessage] = useState("No ingestion yet.");

  const [query, setQuery] = useState("Travel-friendly over-ear headphones under 250 USD");
  const [userProfile, setUserProfile] = useState("");
  const [topK, setTopK] = useState("5");
  const [category, setCategory] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [currency, setCurrency] = useState("");
  const [tags, setTags] = useState("");
  const [streamMode, setStreamMode] = useState(false);

  const [categories, setCategories] = useState<string[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const [summary, setSummary] = useState("No summary yet.");
  const [resultMeta, setResultMeta] = useState("Awaiting request...");
  const [items, setItems] = useState<RecommendationItem[]>([]);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const statusTone = useMemo(() => {
    if (apiState === "ok") {
      return "bg-moss/10 text-moss border-moss/30";
    }
    if (apiState === "error") {
      return "bg-red-50 text-red-700 border-red-300";
    }
    return "bg-white/70 text-ink border-ink/20";
  }, [apiState]);

  async function refreshHealthAndCategories(): Promise<void> {
    try {
      const health = await fetchHealth();
      setApiState("ok");
      setApiMessage(`API online • indexed products: ${health.indexed_products}`);
      try {
        const categoriesResponse = await fetchCategories();
        setCategories(categoriesResponse.categories.filter((item) => item.trim()));
      } catch {
        setCategories([]);
      }
    } catch (error) {
      setApiState("error");
      setApiMessage("API unavailable");
      if (error instanceof Error) {
        setErrorText(error.message);
      }
    }
  }

  useEffect(() => {
    if (import.meta.env.DEV) {
      return;
    }
    void refreshHealthAndCategories();
  }, []);

  async function onIngestJson(): Promise<void> {
    setErrorText(null);
    setIsBusy(true);
    try {
      const parsed = JSON.parse(productsJson);
      const result = await ingestWithJson(parsed);
      setIngestionMessage(`Ingested: received ${result.received}, indexed ${result.indexed}.`);
      setCategories(result.categories);
      await refreshHealthAndCategories();
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "Could not ingest JSON.");
    } finally {
      setIsBusy(false);
    }
  }

  async function onIngestFile(): Promise<void> {
    setErrorText(null);
    if (!file) {
      setErrorText("Select a .json or .csv file first.");
      return;
    }

    setIsBusy(true);
    try {
      const result = await ingestWithFile(file);
      setIngestionMessage(`Ingested from file: received ${result.received}, indexed ${result.indexed}.`);
      setCategories(result.categories);
      await refreshHealthAndCategories();
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "Could not ingest file.");
    } finally {
      setIsBusy(false);
    }
  }

  async function onClearIngestion(): Promise<void> {
    setErrorText(null);
    setIsBusy(true);
    try {
      const result = await clearIngestion();
      setIngestionMessage(`Cleared ingestion: deleted ${result.deleted}, indexed ${result.indexed_products}.`);
      setCategories([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      setFile(null);
      await refreshHealthAndCategories();
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "Could not clear ingestion.");
    } finally {
      setIsBusy(false);
    }
  }

  async function onRecommend(): Promise<void> {
    setErrorText(null);
    setIsBusy(true);
    setItems([]);
    setSummary("No summary yet.");
    setResultMeta("Processing...");

    try {
      const queryTrimmed = query.trim();
      const profileValue = toProfileValue(userProfile);

      if (!queryTrimmed && !profileValue) {
        throw new Error("Provide query or user profile.");
      }

      const filters: RecommendationFilters = {
        category: category || undefined,
        min_price: parseOptionalNumber(minPrice),
        max_price: parseOptionalNumber(maxPrice),
        currency: currency || undefined,
        tags: toTagArray(tags),
      };

      const payload = {
        query: queryTrimmed || undefined,
        user_profile: profileValue,
        top_k: parseOptionalNumber(topK) ?? 5,
        filters,
        stream: streamMode,
      };

      if (streamMode) {
        setSummary(STREAM_PENDING_SUMMARY);
        await recommendStream(payload, (chunk) => {
          if (chunk.event === "recommendation") {
            setItems((prev) => [...prev, chunk.data]);
            return;
          }
          if (chunk.event === "summary") {
            setSummary(chunk.data.text || "Summary is unavailable.");
            return;
          }
          if (chunk.event === "done") {
            setResultMeta(`Returned ${chunk.data.count} recommendation(s).`);
          }
        });
      } else {
        const result = await recommend(payload);
        setItems(result.recommendations);
        setSummary(result.llm_summary || "No summary was generated.");
        setResultMeta(`Returned ${result.recommendations.length} recommendation(s).`);
      }
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "Could not fetch recommendations.");
      setResultMeta("Request failed.");
    } finally {
      setIsBusy(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden px-4 pb-12 pt-8 sm:px-6 lg:px-10">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(rgba(16,42,49,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(16,42,49,0.04)_1px,transparent_1px)] bg-[size:36px_36px] [mask-image:radial-gradient(circle_at_center,rgba(0,0,0,0.9),transparent_78%)]" />

      <main className="mx-auto max-w-7xl">
        <header className="animate-rise space-y-4">
          <h1 className="font-display text-4xl leading-tight text-ink sm:text-5xl">AI Product Recommendation Engine</h1>
          <p className="max-w-3xl text-sm leading-6 text-ink/75 sm:text-base">
            Ingest your product catalog, describe user intent, and generate grounded recommendations with semantic
            ranking and LLM explanations.
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <div className={`inline-flex rounded-full border px-4 py-2 text-sm font-semibold ${statusTone}`}>
              {apiMessage}
            </div>
          </div>
          {errorText ? <p className="text-sm font-medium text-red-700">{errorText}</p> : null}
        </header>

        <section className="mt-6 grid gap-5 lg:grid-cols-2">
          <article className="glass-panel animate-rise [animation-delay:80ms]">
            <h2 className="font-display text-2xl text-ink">1. Ingest Catalog</h2>
            <p className="mt-2 text-sm text-ink/70">Paste a JSON payload or upload a `.json` / `.csv` file.</p>

            <label className="mt-4 block text-xs font-bold uppercase tracking-wide text-ink/70">Products JSON</label>
            <textarea
              className="form-input mt-2 min-h-44 resize-y"
              value={productsJson}
              onChange={(event) => setProductsJson(event.target.value)}
            />

            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn-primary" type="button" onClick={() => void onIngestJson()} disabled={isBusy}>
                Ingest JSON
              </button>
              <button
                className="btn-ghost"
                type="button"
                onClick={() => setProductsJson("")}
                disabled={isBusy}
              >
                Clear JSON
              </button>
            </div>

            <label className="mt-5 block text-xs font-bold uppercase tracking-wide text-ink/70">Upload file</label>
            <input
              ref={fileInputRef}
              className="form-input mt-2"
              type="file"
              accept=".json,.csv"
              onChange={onFileChange}
            />

            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn-secondary" type="button" onClick={() => void onIngestFile()} disabled={isBusy}>
                Ingest File
              </button>
              <button
                className="btn-ghost"
                type="button"
                onClick={() => {
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  }
                  setFile(null);
                }}
                disabled={isBusy}
              >
                Clear File
              </button>
              <button className="btn-ghost" type="button" onClick={() => void onClearIngestion()} disabled={isBusy}>
                Clear Ingestion
              </button>
            </div>

            <div className="mt-4 rounded-2xl border border-ink/15 bg-white/60 p-3 text-sm text-ink/75">
              {ingestionMessage}
            </div>
          </article>

          <article className="glass-panel animate-rise [animation-delay:160ms]">
            <h2 className="font-display text-2xl text-ink">2. Build Recommendation Request</h2>

            <label className="mt-4 block text-xs font-bold uppercase tracking-wide text-ink/70">Search query</label>
            <textarea
              className="form-input mt-2 min-h-24"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />

            <label className="mt-4 block text-xs font-bold uppercase tracking-wide text-ink/70">User profile</label>
            <textarea
              className="form-input mt-2 min-h-24"
              value={userProfile}
              onChange={(event) => setUserProfile(event.target.value)}
              placeholder='{"preferred_brands":["SonicWave"],"budget":250}'
            />

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold uppercase tracking-wide text-ink/70">
                Top K
                <input
                  className="form-input mt-2"
                  type="number"
                  min={1}
                  max={25}
                  value={topK}
                  onChange={(event) => setTopK(event.target.value)}
                />
              </label>

              <label className="text-xs font-bold uppercase tracking-wide text-ink/70">
                Category
                <select
                  className="form-input mt-2"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="">Any category</option>
                  {categories.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <label className="text-xs font-bold uppercase tracking-wide text-ink/70">
                Min price
                <input
                  className="form-input mt-2"
                  type="number"
                  min={0}
                  step="0.01"
                  value={minPrice}
                  onChange={(event) => setMinPrice(event.target.value)}
                />
              </label>

              <label className="text-xs font-bold uppercase tracking-wide text-ink/70">
                Max price
                <input
                  className="form-input mt-2"
                  type="number"
                  min={0}
                  step="0.01"
                  value={maxPrice}
                  onChange={(event) => setMaxPrice(event.target.value)}
                />
              </label>

              <label className="text-xs font-bold uppercase tracking-wide text-ink/70">
                Currency
                <select
                  className="form-input mt-2"
                  value={currency}
                  onChange={(event) => setCurrency(event.target.value)}
                >
                  <option value="">Any currency</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                  <option value="GBP">GBP</option>
                </select>
              </label>
            </div>

            <label className="mt-4 block text-xs font-bold uppercase tracking-wide text-ink/70">Tags</label>
            <input
              className="form-input mt-2"
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder="wireless, anc, travel"
            />

            <label className="mt-4 inline-flex items-center gap-2 text-sm text-ink/75">
              <input
                type="checkbox"
                checked={streamMode}
                onChange={(event) => setStreamMode(event.target.checked)}
              />
              Enable streaming mode (NDJSON)
            </label>

            <div className="mt-4">
              <button className="btn-primary" type="button" onClick={() => void onRecommend()} disabled={isBusy}>
                Get Recommendations
              </button>
            </div>
          </article>
        </section>

        <section className="glass-panel mt-5 animate-rise [animation-delay:240ms]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-2xl text-ink">3. Results</h2>
            <span className="rounded-full border border-ink/20 bg-white/60 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-ink/70">
              {resultMeta}
            </span>
          </div>

          <div className="mt-4 rounded-2xl border border-calm/20 bg-calm/5 p-4 text-sm leading-6 text-ink/80">
            {summary}
          </div>

          <div className="mt-4 grid gap-3">
            {items.length === 0 ? (
              <p className="text-sm text-ink/70">No recommendations yet.</p>
            ) : (
              items.map((item) => (
                <article key={item.external_id} className="rounded-2xl border border-ink/15 bg-white/65 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="font-display text-xl text-ink">{item.title || "Untitled product"}</h3>
                    <p className="text-xs font-bold uppercase tracking-wide text-calm">
                      Similarity {Number(item.score || 0).toFixed(4)}
                    </p>
                  </div>

                  <p className="mt-2 text-sm text-ink/75">{item.description}</p>
                  <p className="mt-2 text-xs text-ink/65">
                    ID: {item.external_id || "-"} · Category: {item.category || "uncategorized"} · Price:{" "}
                    {formatPrice(item.price, item.currency)}
                  </p>
                  <p className="mt-1 text-xs text-ink/65">Tags: {(item.tags || []).join(", ") || "none"}</p>

                  <p className="mt-3 rounded-xl bg-white/80 p-3 text-sm text-ink/90">{item.reason || "No reason provided."}</p>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
