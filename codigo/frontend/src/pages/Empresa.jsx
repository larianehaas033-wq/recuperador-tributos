import React, { useEffect, useMemo, useState } from 'react'
import { aguardar, api, brl, cnpj, competencia, dataHora, REGIME } from '../api'
import { Aviso, Icon, Progresso, Titulo } from '../ui'

function meses60() {
  const out = []
  const d = new Date()
  d.setDate(1)
  for (let i = 0; i < 60; i++) {
    d.setMonth(d.getMonth() - 1)
    out.unshift(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  return out
}

export default function Empresa({ id, ir }) {
  const [d, setD] = useState(null)
  const [job, setJob] = useState(null)
  const [erro, setErro] = useState(null)
  const [excluindo, setExcluindo] = useState(false)

  const carregar = () => api.get(`/api/empresas/${id}`).then(setD)
  useEffect(() => { carregar() }, [id])

  const cobertura = useMemo(() => {
    if (!d) return {}
    const c = {}
    for (const x of d.cobertura) (c[x.periodo] ||= new Set()).add(x.tipo)
    for (const x of d.xml) if (x.periodo) (c[x.periodo] ||= new Set()).add('XML_NFE')
    return c
  }, [d])

  if (!d) return null
  const e = d.empresa

  const analisar = async () => {
    setErro(null)
    try {
      const { job: j } = await api.post(`/api/empresas/${id}/analisar`)
      const aid = await aguardar(j, setJob)
      ir('analise', aid)
    } catch (err) { setErro(err.message) } finally { setJob(null) }
  }

  const excluirArquivo = async (a) => {
    if (!confirm(`Remover ${a.nome}? Os dados desse arquivo saem da base.`)) return
    try { await api.del(`/api/arquivos/${a.id}`) } catch (err) { alert(err.message) }
    carregar()
  }

  const excluirEmpresa = async () => {
    if (!confirm(`Excluir ${e.nome} e todos os arquivos e análises dela?`)) return
    setExcluindo(true)
    try {
      await api.del(`/api/empresas/${id}`)
      ir('painel')
    } catch (err) {
      alert(err.message)
    } finally { setExcluindo(false) }
  }

  const mudarRegime = async (ev) => {
    try { await api.post(`/api/empresas/${id}/regime`, { regime: ev.target.value || null }) } catch (err) { alert(err.message) }
    carregar()
  }

  const meses = meses60()
  const linhas = [['EFD_CONTRIB', 'EFD-Contribuições'], ['EFD_ICMS_IPI', 'EFD ICMS/IPI'], ['XML_NFE', 'XMLs']]

  return (
    <>
      <button className="mb-3 flex items-center gap-1 text-sm text-muted hover:text-navy" onClick={() => ir('painel')}><Icon name="voltar" />Painel</button>
      <Titulo sub={`${cnpj(e.cnpj)} · ${e.uf || ''} · ${REGIME[e.regime] || 'regime não identificado'}${e.ind_ativ === '0' ? ' · industrial' : ''}`}
        acoes={<>
          <label className="flex items-center gap-2 text-sm text-muted" title="Usado nos meses sem EFD-Contribuições. Quando a EFD-Contribuições existe, vale o regime informado nela.">
            Regime
            <select className="input !w-auto !py-1.5" value={e.regime_manual || ''} onChange={mudarRegime}>
              <option value="">Automático (pelos arquivos)</option>
              <option value="LUCRO_REAL">Lucro Real</option>
              <option value="LUCRO_PRESUMIDO">Lucro Presumido</option>
              <option value="SIMPLES_NACIONAL">Simples Nacional</option>
            </select>
          </label>
          <button className="btn-ghost" onClick={() => ir('importar')}><Icon name="importar" />Importar mais</button>
          <button className="btn-gold" disabled={!!job} onClick={analisar}><Icon name="play" />Analisar agora</button>
        </>}>
        {e.nome}
      </Titulo>

      {job && <div className="mb-4"><Progresso job={job} /></div>}
      {erro && <div className="mb-4"><Aviso tipo="erro">{erro}</Aviso></div>}

      <div className="card mb-6 p-5">
        <div className="mb-3 flex items-baseline justify-between">
          <div className="font-semibold text-navy">Cobertura dos últimos 60 meses</div>
          <div className="text-xs text-muted">Meses sem arquivo não entram na análise</div>
        </div>
        <div className="overflow-x-auto">
          <table className="text-[10px]">
            <tbody>
              {linhas.map(([k, nome]) => (
                <tr key={k}>
                  <td className="whitespace-nowrap pr-3 text-xs text-muted">{nome}</td>
                  {meses.map((m) => (
                    <td key={m} className="p-[1.5px]">
                      <div title={`${competencia(m)}: ${cobertura[m]?.has(k) ? 'importado' : 'faltando'}`}
                        className={`h-4 w-3 rounded-sm ${cobertura[m]?.has(k) ? 'bg-navy' : 'bg-navy-100'}`} />
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td />
                {meses.filter((_, i) => i % 6 === 0).map((m) => (
                  <td key={m} colSpan={6} className="pt-1 text-left text-muted">{competencia(m)}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="card overflow-hidden lg:col-span-2">
          <div className="px-5 py-4 font-semibold text-navy">Análises</div>
          {d.analises.length === 0 && <div className="px-5 pb-5 text-sm text-muted">Nenhuma análise ainda. Clique em <b>Analisar agora</b>.</div>}
          {d.analises.map((a) => (
            <button key={a.id} onClick={() => ir('analise', a.id)}
              className="flex w-full items-center justify-between border-t border-line px-5 py-3 text-left hover:bg-navy-50/60">
              <div>
                <div className="text-sm font-semibold">Análise #{a.id}{a.desatualizada ? <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">desatualizada</span> : ''}</div>
                <div className="text-xs text-muted">{dataHora(a.criado_em)} · regras {a.versao_regras?.split(' ')[0]}</div>
              </div>
              <div className="num text-right text-sm font-semibold text-navy">
                {brl((a.resumo.total_corrigido || 0) + (a.resumo.total_saldo_credor || 0))}
              </div>
            </button>
          ))}
        </div>
        <div className="card overflow-hidden lg:col-span-3">
          <div className="flex items-center justify-between px-5 py-4">
            <div className="font-semibold text-navy">Arquivos importados ({d.arquivos.length})</div>
            <button className="btn-danger !py-1 text-xs" onClick={excluirEmpresa} disabled={excluindo}><Icon name="lixo" className="h-3.5 w-3.5" />{excluindo ? 'Excluindo...' : 'Excluir empresa'}</button>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full">
              <tbody>
                {d.arquivos.map((a) => (
                  <tr key={a.id}>
                    <td className="td"><div className="font-medium">{a.nome}</div><div className="text-xs text-muted">{a.tipo.replace('_', ' ')}{a.finalidade === 'retificadora' ? ' · retificadora' : ''}</div></td>
                    <td className="td num text-muted">{a.periodo_ini ? competencia(a.periodo_ini.slice(0, 7)) : ''}</td>
                    <td className="td text-right"><button className="text-muted hover:text-bad" onClick={() => excluirArquivo(a)}><Icon name="lixo" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}
