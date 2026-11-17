import React, { useEffect, useState } from 'react'
import { api, brl, cnpj, competencia, REGIME } from '../api'
import { Aviso, Icon, Kpi, Titulo, Vazio } from '../ui'

export default function Painel({ ir, status }) {
  const [empresas, setEmpresas] = useState(null)
  const [resumos, setResumos] = useState({})

  useEffect(() => {
    api.get('/api/empresas').then(async (es) => {
      setEmpresas(es)
      const r = {}
      await Promise.all(es.filter((e) => e.ultima_analise).map(async (e) => {
        const a = await api.get(`/api/analises/${e.ultima_analise}`)
        r[e.id] = a.analise.resumo
      }))
      setResumos(r)
    })
  }, [])

  const tot = Object.values(resumos).reduce(
    (acc, r) => ({
      ident: acc.ident + (r.total_corrigido || 0) + (r.total_saldo_credor || 0),
      ver: acc.ver + (r.a_verificar || 0),
      risco: acc.risco + (r.riscos || 0),
    }),
    { ident: 0, ver: 0, risco: 0 },
  )

  return (
    <>
      <Titulo sub="Visão geral das empresas analisadas e da base legal."
        acoes={<button className="btn-primary" onClick={() => ir('importar')}><Icon name="importar" />Importar arquivos</button>}>
        Painel
      </Titulo>

      {status?.base_desatualizada && (
        <div className="mb-4"><Aviso>A base não foi atualizada nas últimas 24 horas. Clique em <b>Atualizar agora</b> (menu à esquerda) antes de gerar relatórios para clientes.</Aviso></div>
      )}
      {status?.fontes_pendentes?.length > 0 && (
        <div className="mb-4"><Aviso>{status.fontes_pendentes.length} fonte(s) oficial(is) mudaram desde a última verificação. Revise em <a className="font-semibold underline" href="#/base">Base legal</a>.</Aviso></div>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-4">
        <Kpi rotulo="Identificado (todas as empresas)" valor={brl(tot.ident)} detalhe="Última análise de cada empresa" destaque />
        <Kpi rotulo="Não comprovado" valor={brl(tot.ver)} tom="verificar" detalhe="Fora dos totais" />
        <Kpi rotulo="Riscos encontrados" valor={brl(tot.risco)} tom="risco" detalhe="Valores que podem ser cobrados" />
        <Kpi rotulo="Selic carregada até" valor={status?.selic?.ate ? competencia(status.selic.ate) : '—'}
          detalhe={status?.selic?.meses ? `${status.selic.meses} meses na tabela` : 'Atualize a base com internet'} />
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Empresas</h2>
      {empresas && empresas.length === 0 && (
        <Vazio titulo="Nenhuma empresa ainda"
          texto="Importe os arquivos SPED (EFD-Contribuições e EFD ICMS/IPI) e os XMLs. A empresa é criada automaticamente pelo CNPJ."
          acao={<button className="btn-primary" onClick={() => ir('importar')}>Importar arquivos</button>} />
      )}
      {empresas && empresas.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead className="bg-navy-50"><tr>
              <th className="th">Empresa</th><th className="th">Regime</th><th className="th">Arquivos</th>
              <th className="th">Período</th><th className="th text-right">Identificado</th><th className="th text-right">Riscos</th><th className="th" />
            </tr></thead>
            <tbody>
              {empresas.map((e) => {
                const r = resumos[e.id]
                return (
                  <tr key={e.id} className="cursor-pointer hover:bg-navy-50/60" onClick={() => ir('empresa', e.id)}>
                    <td className="td"><div className="font-semibold text-navy">{e.nome}</div><div className="text-xs text-muted">{cnpj(e.cnpj)} · {e.uf}</div></td>
                    <td className="td">{REGIME[e.regime] || <span className="text-muted">não identificado</span>}</td>
                    <td className="td num">{e.arquivos}</td>
                    <td className="td num text-muted">{e.ini ? `${competencia(e.ini.slice(0, 7))} a ${competencia(e.fim.slice(0, 7))}` : '—'}</td>
                    <td className="td num text-right font-semibold">{r ? brl((r.total_corrigido || 0) + (r.total_saldo_credor || 0)) : <span className="text-muted">sem análise</span>}{r && e.analise_desatualizada ? <div className="text-[10px] font-semibold text-amber-700">arquivos mudaram: analise de novo</div> : ''}</td>
                    <td className="td num text-right text-bad">{r ? brl(r.riscos) : ''}</td>
                    <td className="td text-right text-muted">›</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
