import React, { useRef, useState } from 'react'
import { aguardar, api, competencia } from '../api'
import { Aviso, Icon, Progresso, Titulo } from '../ui'
import { ResumoMalha } from './Malha'

const TIPO = { EFD_CONTRIB: 'EFD-Contribuições', EFD_ICMS_IPI: 'EFD ICMS/IPI', XML_NFE: 'XMLs NF-e/NFC-e' }
const ST = {
  IMPORTADO: ['Importado', 'bg-green-50 text-ok'],
  JA_IMPORTADO: ['Já estava importado', 'bg-navy-50 text-muted'],
  IGNORADO: ['Ignorado', 'bg-amber-50 text-warn'],
  ERRO: ['Erro', 'bg-red-50 text-bad'],
}

export default function Importar({ ir }) {
  const [job, setJob] = useState(null)
  const [res, setRes] = useState(null)
  const [erro, setErro] = useState(null)
  const [arrastando, setArrastando] = useState(false)
  const input = useRef()

  const rodar = async (promessa) => {
    setErro(null); setRes(null)
    try {
      const { job: id } = await promessa
      setJob({ etapa: 'Iniciando', progresso: 0 })
      setRes(await aguardar(id, setJob))
    } catch (e) { setErro(e.message) } finally { setJob(null) }
  }

  const escolher = async (tipo) => {
    const { caminhos } = await api.post(`/api/selecionar?tipo=${tipo}`)
    if (caminhos.length) rodar(api.post('/api/importar', { caminhos }))
  }

  const enviar = (files) => {
    if (!files.length) return
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    rodar(api.upload('/api/upload', fd))
  }

  const empresas = res ? [...new Set(res.flatMap((r) => r.empresa_id ? [r.empresa_id] : r.empresas || []))] : []

  return (
    <>
      <Titulo sub="Arquivos dos últimos 60 meses. Pode mandar tudo junto: o programa separa por tipo e por empresa (CNPJ).">
        Importar arquivos
      </Titulo>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="card p-5 md:col-span-2">
          <div
            onDragOver={(e) => { e.preventDefault(); setArrastando(true) }}
            onDragLeave={() => setArrastando(false)}
            onDrop={(e) => { e.preventDefault(); setArrastando(false); enviar(e.dataTransfer.files) }}
            className={`flex flex-col items-center rounded-lg border-2 border-dashed px-6 py-12 text-center transition ${arrastando ? 'border-gold bg-gold-100/40' : 'border-line'}`}>
            <Icon name="importar" className="h-8 w-8 text-navy-600" />
            <div className="mt-3 font-semibold text-navy">Arraste os arquivos aqui</div>
            <div className="mt-1 text-sm text-muted">SPED (.txt), XMLs (.xml), pacotes .zip com XMLs ou planilha de itens do DF-e (.xlsx)</div>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <button className="btn-primary" disabled={!!job} onClick={() => escolher('pasta')}><Icon name="pasta" />Escolher pasta</button>
              <button className="btn-ghost" disabled={!!job} onClick={() => escolher('arquivos')}><Icon name="arquivo" />Escolher arquivos</button>
              <input ref={input} type="file" multiple className="hidden" onChange={(e) => enviar(e.target.files)} />
            </div>
          </div>
        </div>
        <div className="card p-5 text-sm">
          <div className="mb-3 font-semibold text-navy">O que importar</div>
          <ul className="space-y-3 text-muted">
            <li><b className="text-ink">EFD-Contribuições</b> de cada mês: base de PIS/COFINS, créditos e valor recolhido.</li>
            <li><b className="text-ink">EFD ICMS/IPI</b> de cada mês: compras com ST, créditos de ICMS e notas escrituradas.</li>
            <li><b className="text-ink">XMLs</b> de compra e venda (NF-e e NFC-e): necessários para as teses de ICMS e para cruzar com o SPED.</li>
            <li><b className="text-ink">Planilha de itens do DF-e</b> (SAT/SEF, "Excel Itens das notas NF-es"): substitui os XMLs de compra no cruzamento do crédito de ICMS. A planilha só de notas não serve.</li>
          </ul>
          <p className="mt-4 text-xs text-muted">Se importar a retificadora de um mês, ela substitui a original. O mesmo arquivo nunca entra duas vezes.</p>
        </div>
      </div>

      <div className="mt-6 space-y-4">
        {job && <Progresso job={job} />}
        {erro && <Aviso tipo="erro">{erro}</Aviso>}
        {res && <ResumoMalha ir={ir} itens={Object.values(Object.fromEntries(res.filter((r) => r.malha).map((r) => [r.malha.empresa_id, r.malha])))} />}
        {res && (
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4">
              <div className="font-semibold text-navy">Resultado da importação</div>
              <div className="flex gap-2">
                {empresas.map((id) => (
                  <button key={id} className="btn-gold" onClick={() => ir('empresa', id)}>Ver empresa e analisar</button>
                ))}
              </div>
            </div>
            <table className="w-full">
              <thead className="bg-navy-50"><tr>
                <th className="th">Arquivo</th><th className="th">Tipo</th><th className="th">Empresa</th>
                <th className="th">Competência</th><th className="th">Registros</th><th className="th">Situação</th>
              </tr></thead>
              <tbody>
                {res.map((r, i) => (
                  <tr key={i}>
                    <td className="td font-medium">{r.arquivo}</td>
                    <td className="td">{TIPO[r.tipo] || '—'}</td>
                    <td className="td">{r.nome || (r.tipo === 'XML_NFE' ? <>{r.importadas} notas novas{r.criadas?.length > 0 && <div className="mt-1 text-xs text-muted">Empresa cadastrada pelos XMLs: {r.criadas.join(', ')}</div>}</> : '—')}</td>
                    <td className="td num">{r.periodo ? competencia(r.periodo) : '—'}{r.finalidade === 'retificadora' && <span className="chip ml-2 bg-navy-100 text-navy">retificadora</span>}</td>
                    <td className="td num text-muted">{r.itens != null ? `${r.notas} notas · ${r.itens} itens` : r.lidas != null ? `${r.lidas} lidas · ${r.repetidas} repetidas · ${r.sem_empresa} de outros CNPJs` : ''}</td>
                    <td className="td">
                      <span className={`chip ${ST[r.status]?.[1]}`}>{ST[r.status]?.[0] || r.status}</span>
                      {(r.motivo || r.substituiu) && <div className="mt-1 text-xs text-muted">{r.motivo || `Substituiu ${r.substituiu}`}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
