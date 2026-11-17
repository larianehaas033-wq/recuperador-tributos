async function req(method, url, body) {
  const opts = { method, headers: {} }
  if (body instanceof FormData) opts.body = body
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const r = await fetch(url, opts)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || `Erro ${r.status}`)
  return data
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b) => req('POST', u, b ?? {}),
  del: (u) => req('DELETE', u),
  upload: (u, fd) => req('POST', u, fd),
}

/** Acompanha uma tarefa em segundo plano até terminar. */
export async function aguardar(jobId, onProgress) {
  for (;;) {
    const j = await api.get(`/api/jobs/${jobId}`)
    onProgress?.(j)
    if (j.status === 'CONCLUIDO') return j.resultado
    if (j.status === 'ERRO') throw new Error(j.erro)
    await new Promise((r) => setTimeout(r, 400))
  }
}

export const brl = (v) =>
  (v ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 })

export const cnpj = (c) =>
  c && c.length === 14 ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : c || ''

export const competencia = (p) => {
  if (!p) return '-'
  const m = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
  return `${m[Number(p.slice(5, 7)) - 1]}/${p.slice(2, 4)}`
}

export const dataHora = (s) => {
  if (!s) return '-'
  const d = new Date(s.includes('T') ? s : s.replace(' ', 'T') + 'Z')
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export const VIA = {
  ADMINISTRATIVO_FEDERAL: 'Receita Federal',
  ADMINISTRATIVO_ESTADUAL: 'Sefaz da UF',
  JUDICIAL: 'Judicial',
}
export const NATUREZA = {
  RESTITUICAO: 'Restituição',
  CREDITO_EXTEMPORANEO: 'Crédito a aproveitar',
  RISCO: 'Risco',
}
export const REGIME = {
  LUCRO_REAL: 'Lucro Real',
  LUCRO_PRESUMIDO: 'Lucro Presumido',
  MISTO: 'Lucro Real (misto)',
  SIMPLES: 'Simples Nacional',
}
