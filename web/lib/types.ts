/** 与后端 /api 的契约类型，一处定义，全站复用。 */

export type Health = {
  ok: boolean;
  llm: string;
  chunks: number;
};

export type GraphNode = {
  data: {
    id: string;
    label: string;
    year: number;
    pagerank: number;
    betweenness: number;
    sustained: number;
    foundational: number;
    community: number;
    size: number;
    is_foundational: boolean;
  };
};

export type GraphEdge = {
  data: { id: string; source: string; target: string; weight: number };
};

export type GraphPayload = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: {
    nodes: number;
    edges: number;
    matched_refs: number;
    total_refs: number;
    density: number;
  };
  foundational: GraphStat[];
  derivative: GraphStat[];
  communities: number[];
};

export type GraphStat = {
  key: string;
  title: string;
  year: number;
  pagerank: number;
  sustained: number;
  foundational: number;
  betweenness: number;
  community: number;
  members: string[];
};

export type ReviewPayload = {
  reviews: {
    community: number;
    theme: string;
    year_range: string;
    members: string[];
    summary: string;
    method: string;
  }[];
  open_ideas: {
    id: string;
    paper_id: string;
    year: number;
    page: number;
    text: string;
    status: string;
    score: number;
    mentions: number;
  }[];
  total_ideas: number;
};

export type Discovery = {
  id: string;
  title: string;
  summary: string;
  authors: string;
  published: string;
  categories: string;
  relevance: number;
  reproducibility: number;
  score: number;
  reason: string;
  repo: string;
  repo_stars: number;
  cited_by: number;
};

export type Paragraph = {
  id: string;
  page: number;
  bbox: number[];
  section: string;
  text: string;
  order: number;
};

export type OutlineItem = {
  text: string;
  level: number;
  page: number;
  bbox: number[];
  number: string;
  path: string;
  block_id: string;
};

export type Paper = {
  id: string;
  title: string;
  filename: string | null;
  pages: number;
  arxiv_id: string | null;
  chunks: number;
};

export type Box = {
  page: number;
  bbox: number[];
};

export type Anchor = {
  label: string;
  paper_id: string;
  page: number;
  bbox: number[];
  /** 逐段 bbox，用于在 PDF 上画精确高亮 */
  boxes: Box[];
  chunk_id: string;
};

export type Citation = {
  marker: string;
  anchor: Anchor;
  snippet: string;
  score: number | null;
};

export type AskResponse = {
  question: string;
  answer: string;
  grounded: boolean;
  insufficient: boolean;
  repaired: boolean;
  invalid_markers: number[];
  citations: Citation[];
  confidence: number;
};

/** 阅读器里的「就本篇提问」复用同一个返回结构。 */
export type AnswerResult = AskResponse;
