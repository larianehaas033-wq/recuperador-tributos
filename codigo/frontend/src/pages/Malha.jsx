import React, { useEffect, useState } from 'react'
import { api, brl, competencia } from '../api'

const COR = { ALTA: 'bg-red-50 text-bad', MEDIA: 'bg-amber-50 text-warn' }

// Quadro de alertas de possível malha fiscal (cruzamentos que o fisco faz com a escrituração do cliente)
export function ResumoMalha({ itens, ir }) {
  const com = itens.filter((m) => m && (m.total > 0 || m.erro))
  if (!com.length) return null
  return (
    <div className="mb-6 rounded-xl border border-red-200 bg-red-50/60 p-5">
      <div className="mb-1 font-semibold text-bad">⚠ Atenção: possível malha fiscal</div>
      <div className="mb-3 text-sm text-ink">
        A escrituração importada tem pontos que o fisco cruza automaticamente (notas x EFD, devoluções, créditos
        vedados, apuração). Corrija ou retifique antes que a SEF ou a Receita intimem o cliente.
      </div>
      {com.map((m) => (
        <div key={m.empresa_id} className="mb-3 rounded-lg bg-white p-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">{m.nome}: {m.alta} alerta(s) de gravidade alta · {m.media} média</div>
            {ir && <button className="btn-ghost !py-1 text-xs" onClick={() => ir('empresa', m.empresa_id)}>Ver todos</button>}
          </div>
          <ul className="mt-2 space-y-1 text-xs">
            {(m.principais || []).map((a, i) => (
              <li key={i}><span className={`mr-2 rounded px-1.5 py-0.5 font-semibold ${COR[a.gravidade]}`}>{a.gravidade === 'ALTA' ? 'Alta' : 'Média'}</span>
                {a.titulo} — {competencia(a.periodo)}{a.operacao ? ` · ${a.operacao}` : ''}{a.numero ? ` · nº ${a.numero}` : ''} · {a.documento}{a.valor != null ? ` · ${brl(a.valor)}` : ''}</li>
            ))}
          </ul>
          {m.erro && <div className="mt-1 text-xs text-bad">Não foi possível concluir a conferência: {m.erro}</div>}
        </div>
      ))}
    </div>
  )
}

export function MalhaEmpresa({ empresaId }) {
  const [d, setD] = useState(null)
  const [aberto, setAberto] = useState(null)
  useEffect(() => { api.get(`/api/empresas/${empresaId}/malha`).then(setD).catch(() => setD(null)) }, [empresaId])
  if (!d) return null
  return (
    <div className={`card mb-6 overflow-hidden ${d.total ? 'border-red-200' : ''}`}>
      <div className="flex items-baseline justify-between px-5 py-4">
        <div className={`font-semibold ${d.total ? 'text-bad' : 'text-navy'}`}>
          {d.total ? `⚠ Possível malha fiscal: ${d.alta} alerta(s) de gravidade alta · ${d.media} média` : 'Malha fiscal: nenhum indício nos arquivos importados'}
        </div>
        <div className="text-xs text-muted">Também na aba "Malha fiscal" do Excel completo</div>
      </div>
      {d.total > 0 && (
        <table className="w-full text-xs">
          <thead><tr className="bg-navy-50 text-left text-muted">
            <th className="px-5 py-2">Gravidade</th><th>Alerta</th><th>Competência</th><th>Entrada/Saída</th><th>Nº da nota</th><th>Documento</th><th className="pr-5 text-right">Valor</th>
          </tr></thead>
          <tbody>
            {d.alertas.map((a, i) => (
              <React.Fragment key={i}>
                <tr className="cursor-pointer border-t border-line hover:bg-navy-50/60" onClick={() => setAberto(aberto === i ? null : i)}>
                  <td className="px-5 py-2"><span className={`rounded px-1.5 py-0.5 font-semibold ${COR[a.gravidade]}`}>{a.gravidade === 'ALTA' ? 'Alta' : 'Média'}</span></td>
                  <td>{a.titulo}</td><td>{competencia(a.periodo)}</td><td>{a.operacao || '—'}</td>
                  <td className="max-w-[160px] truncate" title={a.numero}>{a.numero || '—'}</td><td>{a.documento}</td>
                  <td className="num pr-5 text-right">{a.valor != null ? brl(a.valor) : '—'}</td>
                </tr>
                {aberto === i && (
                  <tr className="bg-navy-50/40"><td colSpan={7} className="px-5 py-3 leading-relaxed">
                    {a.numero && a.numero.includes(',') && <div><b>Notas:</b> {a.numero}</div>}
                    {a.detalhe && <div><b>Detalhe:</b> {a.detalhe}</div>}
                    {a.chave && <div><b>Chave:</b> {a.chave}</div>}
                    <div><b>Fundamento:</b> {a.fundamento}</div>
                    <div><b>Como corrigir:</b> {a.corrigir}</div>
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
