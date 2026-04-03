export type RecommendationFilters = {
  category?: string;
  min_price?: number;
  max_price?: number;
  currency?: string;
  tags?: string[];
};

export type RecommendationItem = {
  external_id: string;
  title: string;
  description: string;
  category?: string | null;
  price?: number | null;
  currency?: string | null;
  tags?: string[];
  score: number;
  reason: string;
};

export type RecommendationResult = {
  query: string;
  recommendations: RecommendationItem[];
  llm_summary?: string | null;
};

export type IngestionResult = {
  received: number;
  indexed: number;
  categories: string[];
};

export type ClearIngestionResponse = {
  deleted: number;
  indexed_products: number;
};

export type HealthResponse = {
  status: string;
  indexed_products: number;
};

export type CategoriesResponse = {
  categories: string[];
};

export type StreamChunk =
  | { event: "recommendation"; data: RecommendationItem }
  | { event: "summary"; data: { text?: string } }
  | { event: "done"; data: { count: number } };
