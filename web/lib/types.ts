/** 与后端 /api 的契约类型，一处定义，全站复用。 */

export type Health = {
  ok: boolean;
  llm: string;
  chunks: number;
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
