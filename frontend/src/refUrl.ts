import type { Reference } from './types'

function isPaperPage(url: string): boolean {
  if (!/^https?:\/\//.test(url)) return false
  if (url.includes('/search')) return false
  return true
}

/** Exact paper page only — never a search-results listing. */
export function referenceUrl(ref: Reference): string | null {
  const provenanced = ref.provenance?.url
  if (provenanced && isPaperPage(provenanced)) return provenanced
  const doi = ref.csl?.DOI as string | undefined
  if (doi) return `https://doi.org/${doi}`
  const number = String(ref.csl?.number || '')
  if (number.toLowerCase().startsWith('arxiv:')) {
    return `https://arxiv.org/abs/${number.slice(6)}`
  }
  const url = ref.csl?.URL as string | undefined
  if (url && isPaperPage(url)) return url
  return null
}

export function referenceLinkLabel(url: string): string {
  if (url.includes('doi.org')) return 'doi'
  if (url.includes('arxiv.org')) return 'arXiv'
  if (url.includes('semanticscholar.org')) return 'Semantic Scholar'
  if (url.includes('openalex.org')) return 'OpenAlex'
  return 'open paper'
}
