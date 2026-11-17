import React, { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { aguardar, api, brl, cnpj, competencia, dataHora, NATUREZA, VIA } from '../api'
import { Aviso, Confianca, Icon, Kpi, Progresso, Titulo } from '../ui'

const CORES = { PIS: '#0B1F3A', COFINS: '#4E6A93', ICMS: '#C9A24B' }

function Itens({ id, filtroInicial, teses, operacao }) {
  const [f, setF] = useState({ tese: '', tributo: '', natureza: '', confianca: '', busca: '', ...filtroInicial })
  const [pag, setPag] = useState(1)
  const [d, setD] = useState({ total: 0, itens: [] })

  useEffect(() => { setF((x) => ({ ...x, ...filtroInicial })); setPag(1) }, [filtroInicial])
  useEffect(() => {
    const q = new URLSearchParams({ pagina: pag, por_pagina: 50 })
    Object.entries(f).forEach(([k, v]) => v && q.set(k, v))
    if (operacao) q.set('operacao', operacao)
    api.get(`/api/analises/${id}/creditos?${q}`).then(setD)
  }, [id, f, pag, operacao])

  const set = (k) => (e) => { setPag(1); setF({ ...f, [k]: e.target.value }) }
  const paginas = Math.max(1, Math.ceil(d.total / 50))

  return (
    <div className="card overflow-hidden">
      <div className="grid gap-2 border-b border-line p-4 md:grid-cols-5">
        <select className="input" value={f.tese} onChange={set('tese')}>
          <option value="">Todas as teses</option>
          {Object.entries(teses).map(([k, v]) => <option key={k} value={k}>{v.nome}</option>)}
        </select>
        <select className="input" value={f.tributo} onChange={set('tributo')}>
          <option value="">Todos os tributos</option><option>PIS</option><option>COFINS</option><option>ICMS</option>
        </select>
        <select className="input" value={f.natureza} onChange={set('natureza')}>
          <option value="">Toda natureza</option>
          {Object.entries(NATUREZA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="input" value={f.confianca} onChange={set('confianca')}>
          <option value="">Comprovados e não comprovados</option><option value="ALTA">Comprovados</option><option value="BAIXA">Não comprovados</option>
        </select>
        <input className="input" placeholder="Buscar chave, NCM, produto" value={f.busca} onChange={set('busca')} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap">
          <thead className="bg-navy-50"><tr>
            <th className="th">Nota (chave, número e item) / Data</th><th className="th">Produto</th><th className="th">NCM</th><th className="th">CFOP</th>
            <th className="th">CST</th><th className="th text-right">Base original</th><th className="th text-right">Valor pago</th>
            <th className="th text-right">A recuperar</th><th className="th text-right">Corrigido</th><th className="th">Tese</th><th className="th">Situação</th>
          </tr></thead>
          <tbody>
            {d.itens.map((c) => (
              <tr key={c.id} className={c.prescrito || c.excluido ? 'opacity-50' : ''} title={c.observacao || ''}>
                <td className="td"><div className="font-mono text-[11px]">{c.chave || '(consolidado)'}</div><div className="text-xs text-muted">{c.num_doc ? `Nota ${c.num_doc}${c.num_item ? ` · item ${Number(c.num_item) || c.num_item}` : ''} · ` : ''}{c.data} · {c.tributo}</div></td>
                <td className="td max-w-[220px] truncate">{c.descricao || '—'}<div className="text-xs text-muted">{c.cod_item}</div></td>
                <td className="td num">{c.ncm || '—'}</td>
                <td className="td num">{c.cfop || '—'}</td>
                <td className="td num">{c.cst_escriturado || '—'}{c.cst_correto && c.cst_correto !== c.cst_escriturado ? <span className="text-ok"> → {c.cst_correto}</span> : ''}</td>
                <td className="td num text-right">{brl(c.base_original)}</td>
                <td className="td num text-right">{brl(c.valor_pago)}</td>
                <td className={`td num text-right font-semibold ${c.natureza === 'RISCO' ? 'text-bad' : ''}`}>{brl(c.valor_recuperar)}</td>
                <td className="td num text-right">{c.natureza === 'RISCO' ? '—' : brl(c.valor_corrigido + c.valor_saldo_credor)}</td>
                <td className="td text-xs">{teses[c.tese]?.nome || c.tese}{c.prescrito ? <span className="chip ml-1 bg-red-50 text-bad">prescrito</span> : ''}</td>
                <td className="td"><Confianca v={c.confianca === 'ALTA' ? 'ALTA' : 'BAIXA'} />{c.confianca !== 'ALTA' && c.observacao && <div className="mt-1 max-w-[260px] whitespace-normal text-[11px] text-muted">{c.observacao}</div>}</td>
              </tr>
            ))}
            {d.itens.length === 0 && <tr><td className="td py-8 text-center text-muted" colSpan={11}>Nenhum item com esses filtros.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted">
        <span className="num">{d.total} itens</span>
        <div className="flex items-center gap-2">
          <button className="btn-ghost !py-1" disabled={pag <= 1} onClick={() => setPag(pag - 1)}>Anterior</button>
          <span className="num">{pag} / {paginas}</span>
          <button className="btn-ghost !py-1" disabled={pag >= paginas} onClick={() => setPag(pag + 1)}>Próxima</button>
        </div>
      </div>
    </div>
  )
}

function Operacao({ id, op, dados, teses }) {
  const saida = op === 'SAIDA'
  if (!dados) return <Aviso tipo="info">Analise de novo para ver este painel.</Aviso>
  return (
    <div className="space-y-4">
      {saida && dados.notas_sem_produtos > 0 && (
        <Aviso tipo="erro">
          {dados.notas_sem_produtos} notas de venda ({brl(dados.valor_sem_produtos)}) estão só resumidas na EFD-Contribuições (NFC-e, registro C175), sem os produtos. Importe os XMLs dessas NFC-e e analise de novo: o valor a recuperar vai mudar.
        </Aviso>
      )}
      <div className="grid gap-3 md:grid-cols-4">
        <Kpi rotulo={saida ? 'Vendas examinadas' : 'Compras examinadas'} valor={brl(dados.valor_operacoes)}
          detalhe={`${dados.notas} notas · ${dados.itens} itens`} />
        <Kpi rotulo="A recuperar comprovado" valor={brl(dados.recuperar_corrigido)} detalhe="Corrigido pela Selic" destaque />
        <Kpi rotulo="Não comprovado" valor={brl(dados.nao_comprovado)} detalhe="Fora dos totais" tom="verificar" />
        <Kpi rotulo="Riscos comprovados" valor={brl(dados.riscos)} detalhe="Podem ser cobrados" tom="risco" />
      </div>
      <Itens id={id} filtroInicial={{}} teses={teses} operacao={op} />
    </div>
  )
}

function RevisaoNcm({ id, ncms, teses, onMudou }) {
  const [job, setJob] = useState(null)
  const decidir = async (n, decisao) => {
    const { job: j } = await api.post(`/api/analises/${id}/revisao`, { ncm: n.ncm, tese: n.tese, decisao })
    await aguardar(j, setJob)
    setJob(null)
    onMudou()
  }
  return (
    <div className="space-y-3">
      <Aviso tipo="ok">Esta conferência é opcional. O programa já confere cada NCM pela lista legal, pela descrição do produto e pelos XMLs de compra. Use os botões só se quiser corrigir um caso específico: <b>Confirmar</b> leva o NCM para os totais, <b>Descartar</b> tira o NCM desta tese para este cliente.</Aviso>
      {job && <Progresso job={job} />}
      <div className="card overflow-hidden">
        <table className="w-full">
          <thead className="bg-navy-50"><tr>
            <th className="th">NCM</th><th className="th">Produto (exemplo)</th><th className="th">Tese</th><th className="th">Itens</th>
            <th className="th text-right">Valor</th><th className="th">Situação</th><th className="th text-right">Ajuste manual</th>
          </tr></thead>
          <tbody>
            {ncms.map((n) => (
              <tr key={n.ncm + n.tese}>
                <td className="td num font-semibold">{n.ncm}</td>
                <td className="td max-w-[260px] truncate">{n.descricao}</td>
                <td className="td text-xs">{teses[n.tese]?.nome}</td>
                <td className="td num">{n.itens}</td>
                <td className="td num text-right">{brl(n.valor)}</td>
                <td className="td"><Confianca v={n.decisao === 'CONFIRMADO' ? 'ALTA' : (n.confianca === 'ALTA' ? 'ALTA' : 'BAIXA')} /></td>
                <td className="td text-right">
                  {n.decisao ? (
                    <span className="inline-flex items-center gap-2 text-xs">
                      <span className={n.decisao === 'CONFIRMADO' ? 'font-semibold text-ok' : 'font-semibold text-bad'}>{n.decisao === 'CONFIRMADO' ? 'Confirmado' : 'Descartado'}</span>
                      <button className="text-muted underline" disabled={!!job} onClick={() => decidir(n, 'LIMPAR')}>desfazer</button>
                    </span>
                  ) : (
                    <span className="inline-flex gap-1">
                      <button className="btn-ghost !px-2 !py-1 text-xs text-ok" disabled={!!job} onClick={() => decidir(n, 'CONFIRMADO')}><Icon name="check" className="h-3.5 w-3.5" />Confirmar</button>
                      <button className="btn-ghost !px-2 !py-1 text-xs text-bad" disabled={!!job} onClick={() => decidir(n, 'DESCARTADO')}><Icon name="x" className="h-3.5 w-3.5" />Descartar</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {ncms.length === 0 && <tr><td className="td py-8 text-center text-muted" colSpan={7}>Nada a revisar.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ArquivoGerado({ arquivo }) {
  if (arquivo.erro) return <Aviso tipo="erro">Não foi possível gerar o arquivo: {arquivo.erro}</Aviso>
  return (
    <Aviso tipo="ok">
      <b>{arquivo.nome}</b> {arquivo.aberto ? 'foi aberto.' : 'foi salvo.'} Fica guardado em {arquivo.caminho}.{' '}
      <button className="font-semibold underline" onClick={() => api.post('/api/abrir-pasta')}>Abrir pasta</button>
    </Aviso>
  )
}

function Cadastro({ empresaId }) {
  const [d, setD] = useState(null)
  const [so, setSo] = useState(true)
  const [busca, setBusca] = useState('')
  const [pag, setPag] = useState(1)
  const [gerando, setGerando] = useState(false)
  const [arquivo, setArquivo] = useState(null)
  useEffect(() => { setD(null); api.get(`/api/empresas/${empresaId}/cadastro`).then(setD) }, [empresaId])
  const baixar = async () => {
    setGerando(true); setArquivo(null)
    try { setArquivo(await api.post(`/api/empresas/${empresaId}/cadastro/abrir`)) }
    catch (err) { setArquivo({ erro: err.message }) }
    finally { setGerando(false) }
  }
  if (!d) return <div className="card p-6 text-sm text-muted">Montando o cadastro dos produtos...</div>
  const q = busca.trim().toUpperCase()
  const linhas = d.linhas.filter((l) => (!so || l.divergencias.length) &&
    (!q || `${l.cod_item} ${l.descricao} ${l.ncm}`.toUpperCase().includes(q)))
  const vis = linhas.slice((pag - 1) * 50, pag * 50)
  const paginas = Math.max(1, Math.ceil(linhas.length / 50))
  const Cel = ({ atual, novo }) => (
    <span className="num">{atual && atual !== novo ? <><span className="text-bad line-through">{atual}</span> <span className="font-semibold text-ok">{novo}</span></> : novo}</span>
  )
  return (
    <div className="space-y-3">
      {arquivo && <ArquivoGerado arquivo={arquivo} />}
      <div className="grid gap-3 md:grid-cols-4">
        <Kpi rotulo="Produtos" valor={String(d.resumo.produtos)} />
        <Kpi rotulo="Com divergência" valor={String(d.resumo.com_divergencia)} tom="risco" detalhe="Cadastro atual diferente do sugerido" />
        <Kpi rotulo="Não comprovados" valor={String(d.resumo.nao_comprovados)} tom="verificar" detalhe="Motivo na linha" />
        <Kpi rotulo="Tabela cClassTrib" valor="v1.71" detalhe={d.resumo.tabela_cclasstrib} />
      </div>
      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-navy" checked={so} onChange={(e) => { setSo(e.target.checked); setPag(1) }} />Só produtos com divergência</label>
          <input className="input max-w-xs" placeholder="Buscar código, descrição ou NCM" value={busca} onChange={(e) => { setBusca(e.target.value); setPag(1) }} />
          <button className="btn-primary ml-auto" disabled={gerando} onClick={baixar}><Icon name="excel" />{gerando ? 'Gerando...' : 'Abrir cadastro em Excel'}</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full whitespace-nowrap">
            <thead className="bg-navy-50"><tr>
              <th className="th">Produto</th><th className="th">NCM</th><th className="th">CST PIS/COFINS</th><th className="th">CST ICMS</th>
              <th className="th">CSOSN</th><th className="th">CST IBS/CBS</th><th className="th">cClassTrib</th><th className="th">Redução</th>
              <th className="th">NBS</th><th className="th">Situação</th>
            </tr></thead>
            <tbody>
              {vis.map((l) => (
                <tr key={l.cod_item} className="align-top" title={l.observacao}>
                  <td className="td max-w-[260px]"><div className="truncate font-medium">{l.descricao || '—'}</div><div className="text-xs text-muted">{l.cod_item} · {l.tipo_item}</div>
                    {l.divergencias.length > 0 && <div className="mt-1 whitespace-normal text-[11px] font-semibold text-bad">{l.divergencias.join(' · ')}</div>}</td>
                  <td className="td num">{l.ncm || '—'}</td>
                  <td className="td"><Cel atual={l.atual_cst_pis_cofins} novo={l.cst_pis_cofins} /><div className="max-w-[160px] truncate text-[11px] text-muted">{l.grupo_pis_cofins}</div></td>
                  <td className="td"><Cel atual={l.atual_cst_icms && l.atual_cst_icms.length === 3 ? l.atual_cst_icms : null} novo={l.cst_icms} /></td>
                  <td className="td num">{l.csosn}</td>
                  <td className="td num">{l.cst_ibscbs}</td>
                  <td className="td"><Cel atual={l.atual_cclasstrib} novo={l.cclasstrib} /><div className="max-w-[200px] truncate text-[11px] text-muted">{l.grupo_ibscbs}</div></td>
                  <td className="td num">{l.reducao_ibscbs == null ? '—' : `${l.reducao_ibscbs}%`}</td>
                  <td className="td text-xs text-muted">{l.nbs}</td>
                  <td className="td">{l.comprovacao === 'Revisar NCM' ? <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800">Revisar NCM</span> : <Confianca v={l.comprovacao === 'ALTA' ? 'ALTA' : 'BAIXA'} />}{l.comprovacao !== 'ALTA' && <div className="mt-1 max-w-[240px] whitespace-normal text-[11px] text-muted">{l.observacao}</div>}</td>
                </tr>
              ))}
              {vis.length === 0 && <tr><td className="td py-8 text-center text-muted" colSpan={10}>{so ? 'Nenhum produto com divergência.' : 'Nenhum produto.'}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-muted">
          <span className="num">{linhas.length} produtos</span>
          <div className="flex items-center gap-2">
            <button className="btn-ghost !py-1" disabled={pag <= 1} onClick={() => setPag(pag - 1)}>Anterior</button>
            <span className="num">{pag} / {paginas}</span>
            <button className="btn-ghost !py-1" disabled={pag >= paginas} onClick={() => setPag(pag + 1)}>Próxima</button>
          </div>
        </div>
      </div>
      <p className="text-xs text-muted">CST ICMS para empresas do regime normal; CSOSN para empresas do Simples Nacional. NBS só se aplica a serviços. cClassTrib conforme a tabela oficial da NF-e e os anexos da LC 214/2025 (texto com as alterações da LC 227/2026).</p>
    </div>
  )
}

export default function Analise({ id, ir }) {
  const [d, setD] = useState(null)
  const [aba, setAba] = useState('teses')
  const [filtro, setFiltro] = useState({})
  const [job, setJob] = useState(null)
  const [gerando, setGerando] = useState(null)
  const [arquivo, setArquivo] = useState(null)

  const abrir = async (tipo) => {
    setGerando(tipo); setArquivo(null)
    try {
      setArquivo(await api.post(`/api/analises/${id}/abrir`, { tipo }))
    } catch (err) {
      setArquivo({ erro: err.message })
    } finally { setGerando(null) }
  }

  const carregar = () => api.get(`/api/analises/${id}`).then(setD)
  useEffect(() => { carregar() }, [id])
  if (!d) return null
  const a = d.analise
  const r = a.resumo
  const e = d.empresa
  const teses = a.teses_info

  const reanalisar = async () => {
    const { job: j } = await api.post(`/api/empresas/${e.id}/analisar`)
    const nova = await aguardar(j, setJob)
    setJob(null)
    ir('analise', nova)
  }

  const verItens = (tese) => { setFiltro({ tese }); setAba('itens') }

  return (
    <>
      <button className="mb-3 flex items-center gap-1 text-sm text-muted hover:text-navy" onClick={() => ir('empresa', e.id)}><Icon name="voltar" />{e.nome}</button>
      <Titulo sub={`${cnpj(e.cnpj)} · ${competencia(a.periodo_ini)} a ${competencia(a.periodo_fim)} · análise de ${dataHora(a.criado_em)} · regras ${a.versao_regras}`}
        acoes={<>
          <button className="btn-ghost" disabled={!!job} onClick={reanalisar}><Icon name="atualizar" />Analisar de novo</button>
          <button className="btn-ghost" disabled={!!gerando} onClick={() => abrir('pdf')}><Icon name="pdf" />{gerando === 'pdf' ? 'Gerando...' : 'PDF para o cliente'}</button>
          <button className="btn-primary" disabled={!!gerando} onClick={() => abrir('excel')}><Icon name="excel" />{gerando === 'excel' ? 'Gerando...' : 'Excel completo'}</button>
        </>}>
        Análise #{a.id}
      </Titulo>

      {job && <div className="mb-4"><Progresso job={job} /></div>}
      {arquivo && <div className="mb-4"><ArquivoGerado arquivo={arquivo} /></div>}
      {a.avisos?.length > 0 && <div className="mb-5 space-y-2">{a.avisos.map((t, i) => <Aviso key={i}>{t}</Aviso>)}</div>}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Kpi rotulo="Restituível corrigido (Selic)" valor={brl(r.total_corrigido)} detalhe={`Sem correção: ${brl(r.total_restituivel)}`} destaque />
        <Kpi rotulo="Créditos a aproveitar" valor={brl(r.total_saldo_credor)} detalhe="Saldo credor / crédito extemporâneo" />
        <Kpi rotulo="Não comprovado" valor={brl(r.a_verificar)} tom="verificar" detalhe="Fora dos totais; motivo em cada item" />
        <Kpi rotulo="Riscos" valor={brl(r.riscos)} tom="risco" detalhe="Podem ser cobrados da empresa" />
        <Kpi rotulo="Perdido pelo prazo" valor={brl(r.prescrito)} detalhe={`Corte: ${a.data_corte_prescricao}`} />
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-2">
          <div className="mb-2 font-semibold text-navy">Valores por competência</div>
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={(r.serie || []).map((s) => ({ ...s, nome: competencia(s.periodo) }))} margin={{ left: 10 }}>
                <CartesianGrid vertical={false} stroke="#E1E5EB" />
                <XAxis dataKey="nome" tick={{ fontSize: 11, fill: '#5D6878' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#5D6878' }} axisLine={false} tickLine={false}
                  tickFormatter={(v) => v.toLocaleString('pt-BR', { notation: 'compact' })} />
                <Tooltip formatter={(v) => brl(v)} cursor={{ fill: '#F3F6FA' }} />
                <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />
                {['PIS', 'COFINS', 'ICMS'].map((t) => <Bar key={t} dataKey={t} stackId="a" fill={CORES[t]} maxBarSize={28} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card p-5">
          <div className="mb-3 font-semibold text-navy">Por tributo</div>
          {['PIS', 'COFINS', 'ICMS'].map((t) => (
            <div key={t} className="flex items-center justify-between border-b border-line py-2.5 text-sm last:border-0">
              <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CORES[t] }} />{t}</span>
              <span className="num font-semibold">{brl(r.por_tributo?.[t])}</span>
            </div>
          ))}
          <div className="mt-3 text-xs text-muted">Selic até {a.selic_ate ? competencia(a.selic_ate) : 'não carregada'}. Só entram valores comprovados automaticamente pela lei e pelos arquivos do cliente. Riscos ficam fora.</div>
        </div>
      </div>

      <div className="mb-4 flex gap-1 border-b border-line">
        {[['teses', 'Por tese'], ['saidas', 'Saídas auditadas'], ['entradas', 'Entradas auditadas'], ['cadastro', 'Cadastro tributário'], ['itens', 'Todos os itens'], ['ncm', `Revisão de NCM (${d.ncms.length})`], ['roteiro', 'Como recuperar']].map(([k, n]) => (
          <button key={k} onClick={() => { setAba(k); if (k === 'itens') setFiltro({}) }}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold ${aba === k ? 'border-gold text-navy' : 'border-transparent text-muted hover:text-navy'}`}>{n}</button>
        ))}
      </div>

      {aba === 'teses' && (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead className="bg-navy-50"><tr>
              <th className="th">Tese</th><th className="th">Via</th><th className="th">Itens</th>
              <th className="th text-right">Restituível corrigido</th><th className="th text-right">Crédito a aproveitar</th>
              <th className="th text-right">Não comprovado</th><th className="th text-right">Risco</th><th className="th" />
            </tr></thead>
            <tbody>
              {r.teses.map((t) => (
                <tr key={t.tese} className="cursor-pointer hover:bg-navy-50/60" onClick={() => verItens(t.tese)}>
                  <td className="td font-medium">{t.nome}</td>
                  <td className="td text-muted">{VIA[t.via]}</td>
                  <td className="td num">{t.qtd}</td>
                  <td className="td num text-right font-semibold">{t.corrigido ? brl(t.corrigido) : '—'}</td>
                  <td className="td num text-right">{t.saldo_credor ? brl(t.saldo_credor) : '—'}</td>
                  <td className="td num text-right text-warn">{t.baixa ? brl(t.baixa) : '—'}</td>
                  <td className="td num text-right text-bad">{t.risco ? brl(t.risco) : '—'}</td>
                  <td className="td text-right text-muted">›</td>
                </tr>
              ))}
              {r.teses.length === 0 && <tr><td className="td py-8 text-center text-muted" colSpan={8}>Nenhuma oportunidade ou risco encontrado nos arquivos importados.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {aba === 'saidas' && <Operacao id={id} op="SAIDA" dados={r.operacoes?.SAIDA} teses={teses} />}
      {aba === 'entradas' && <Operacao id={id} op="ENTRADA" dados={r.operacoes?.ENTRADA} teses={teses} />}
      {aba === 'cadastro' && <Cadastro empresaId={e.id} />}
      {aba === 'ncm' && <RevisaoNcm id={id} ncms={d.ncms} teses={teses} onMudou={carregar} />}
      {aba === 'itens' && <Itens id={id} filtroInicial={filtro} teses={teses} />}
      {aba === 'roteiro' && (
        <div className="space-y-4">
          {r.teses.map((t) => {
            const info = teses[t.tese] || {}
            return (
              <div key={t.tese} className="card p-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="font-semibold text-navy">{info.nome}</div>
                  <span className="chip bg-navy-50 text-navy">{VIA[info.via]}</span>
                </div>
                <p className="mt-2 text-sm text-muted">{info.fundamento}</p>
                <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm">
                  {(info.roteiro || []).map((p, i) => <li key={i}>{p}</li>)}
                </ol>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
