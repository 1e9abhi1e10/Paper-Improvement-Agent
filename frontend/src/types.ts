export interface Provenance {
  source: 'openalex' | 'semanticscholar' | 'pdf'
  external_id: string
  url: string
  abstract: string
}

/** CSL-JSON item: the fields this app reads, plus whatever else came along. */
export interface CslItem {
  id?: string
  type?: string
  title?: string
  author?: { family?: string; given?: string; literal?: string }[]
  issued?: { 'date-parts'?: (number | string)[][] }
  'container-title'?: string
  DOI?: string
  URL?: string
  number?: string
  [key: string]: unknown
}

export interface Reference {
  id: string
  raw: string
  csl: CslItem
  parse_status: 'parsed' | 'partial' | 'failed'
  provenance: Provenance | null
  added_by_edit: boolean
  resolution_status?: 'verified' | 'low-confidence' | 'unverified'
  resolution_note?: string
}

export interface InTextCitation {
  id: string
  raw: string
  section_id: string
  ref_ids: string[]
  resolved: boolean
}

export interface Section {
  id: string
  title: string
  level: number
  text: string
}

export interface Diagnostic {
  stage: string
  severity: 'info' | 'warning' | 'error'
  message: string
}

export interface BibEntry {
  ref_id: string
  entry: string
  inline: string
  parse_status: 'parsed' | 'partial' | 'failed'
}

export const PARSE_STATUS_LABEL: Record<Reference['parse_status'], string> = {
  parsed: 'parsed',
  partial: 'partial',
  failed: 'unparsed',
}

export const RESOLUTION_LABEL: Record<
  NonNullable<Reference['resolution_status']>,
  string
> = {
  verified: 'verified',
  'low-confidence': 'low confidence',
  unverified: 'unverified',
}

export interface Paper {
  id: string
  filename: string
  title: string
  abstract: string
  page_count?: number
  layout?: string
  year?: string
  sections: Section[]
  references: Reference[]
  intext: InTextCitation[]
  style: string
  style_detected: boolean
  diagnostics: Diagnostic[]
  rendered: {
    bibliography: BibEntry[]
  }
  findings?: Finding[] | null
  proposals?: EditProposal[]
}

export interface Finding {
  id: string
  kind: 'missing_citation' | 'citation_mismatch' | 'unverifiable' | 'uncited_claim' | 'redundant_citation' | 'info'
  section_id: string
  claim: string
  verdict: string
  rationale: string
  confidence: 'high' | 'medium' | 'low'
  ref_id: string
  candidate_csl: CslItem
  candidate_provenance: Provenance | null
}

export interface SectionDiff {
  section_id: string
  old_text: string
  new_text: string
  notes: string[]
}

export interface ChatSource {
  section_id: string
  section_title: string
  quote: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  answered?: boolean
  sources?: ChatSource[]
  cited_refs?: string[]
  warning?: string
}

export interface EditProposal {
  id: string
  command: string
  summary: string
  diffs: SectionDiff[]
  new_references: Reference[]
  warnings: string[]
  status: 'pending' | 'applied' | 'rejected' | 'failed' | 'undone'
  created_at: string
  applied_at: string
}
