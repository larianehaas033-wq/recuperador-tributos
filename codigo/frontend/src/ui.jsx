import React from 'react'

export function Icon({ name, className = 'h-4 w-4' }) {
  const p = {
    painel: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z',
    empresas: 'M4 21V5a2 2 0 012-2h7a2 2 0 012 2v16M15 9h3a2 2 0 012 2v10M8 7h3M8 11h3M8 15h3M3 21h18',
    importar: 'M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2',
    lei: 'M12 3v18M5 7h14M7 7l-3 7a3 3 0 006 0L7 7zm10 0l-3 7a3 3 0 006 0l-3-7z',
    config: 'M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 00-2-1.2L14.5 3h-4l-.4 2.6a7.6 7.6 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 002 1.2l.4 2.6h4l.4-2.6a7.6 7.6 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z',
    atualizar: 'M4 4v6h6M20 20v-6h-6M5.6 15A8 8 0 0019 13M18.4 9A8 8 0 005 11',
    excel: 'M4 4h16v16H4zM8 8l8 8M16 8l-8 8',
    pdf: 'M6 2h9l5 5v15H6zM14 2v6h6',
    pasta: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
    arquivo: 'M7 3h7l5 5v13H7zM14 3v5h5',
    lixo: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
    voltar: 'M15 18l-6-6 6-6',
    check: 'M5 12l5 5 9-11',
    x: 'M6 6l12 12M18 6L6 18',
    alerta: 'M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
    play: 'M7 4l13 8-13 8z',
  }[name]
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"><path d={p} /></svg>
  )
}

export function Kpi({ rotulo, valor, detalhe, destaque, tom }) {
  const cor = tom === 'risco' ? 'text-bad' : tom === 'verificar' ? 'text-warn' : 'text-navy'
  return (
    <div className={`card relative overflow-hidden px-5 py-4 ${destaque ? 'ring-1 ring-gold' : ''}`}>
      {destaque && <div className="absolute inset-y-0 left-0 w-1 bg-gold" />}
      <div className="text-xs font-medium text-muted">{rotulo}</div>
      <div className={`num mt-1 text-2xl font-bold ${cor}`}>{valor}</div>
      {detalhe && <div className="mt-1 text-xs text-muted">{detalhe}</div>}
    </div>
  )
}

export function Confianca({ v }) {
  const m = { ALTA: 'bg-green-50 text-ok', MEDIA: 'bg-amber-50 text-warn', BAIXA: 'bg-amber-50 text-warn', CONDICIONAL: 'bg-navy-50 text-navy' }
  const t = { ALTA: 'Comprovado', MEDIA: 'Não comprovado', BAIXA: 'Não comprovado', CONDICIONAL: 'Depende de Ex/destinação' }
  return <span className={`chip ${m[v] || 'bg-navy-50 text-muted'}`}>{t[v] || v}</span>
}

export function Titulo({ children, sub, acoes }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[22px] font-bold text-navy">{children}</h1>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {acoes && <div className="flex flex-wrap gap-2">{acoes}</div>}
    </div>
  )
}

export function Progresso({ job }) {
  if (!job) return null
  return (
    <div className="card p-4">
      <div className="mb-2 flex justify-between text-sm">
        <span className="font-medium">{job.etapa || 'Processando'}</span>
        <span className="num text-muted">{Math.round((job.progresso || 0) * 100)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-navy-100">
        <div className="h-full bg-gold transition-all" style={{ width: `${Math.max(4, (job.progresso || 0) * 100)}%` }} />
      </div>
    </div>
  )
}

export function Aviso({ children, tipo = 'alerta' }) {
  const s = tipo === 'erro' ? 'border-red-200 bg-red-50 text-bad' : tipo === 'ok'
    ? 'border-green-200 bg-green-50 text-ok' : 'border-amber-200 bg-amber-50 text-[#7A4A00]'
  return (
    <div className={`flex gap-3 rounded-md border px-4 py-3 text-sm ${s}`}>
      <Icon name={tipo === 'ok' ? 'check' : 'alerta'} className="mt-0.5 h-4 w-4 flex-none" />
      <div>{children}</div>
    </div>
  )
}

export function Vazio({ titulo, texto, acao }) {
  return (
    <div className="card flex flex-col items-center px-6 py-14 text-center">
      <div className="text-base font-semibold text-navy">{titulo}</div>
      <p className="mt-1 max-w-md text-sm text-muted">{texto}</p>
      {acao && <div className="mt-5">{acao}</div>}
    </div>
  )
}
