import React, { useEffect, useState } from 'react'
import { api, competencia, dataHora } from '../api'
import { Aviso, Confianca, Icon, Kpi, Titulo } from '../ui'

const ST = { OK: 'text-ok', SEM_MUDANCA: 'text-muted', ALTERADA: 'text-warn', ERRO: 'text-bad' }

export default function BaseLegal({ status, onAtualizar, atualizando, recarregar }) {
  const [regras, setRegras] = useState(null)
  const [hist, setHist] = useState([])
  const [fontes, setFontes] = useState([])
  const [aba, setAba] = useState('regras')

  const carregar = () => {
    api.get('/api/regras').then(setRegras)
    api.get('/api/atualizacoes').then(setHist)
    api.get('/api/fontes').then(setFontes)
  }
  useEffect(() => { carregar() }, [status?.ultima_atualizacao?.executado_em])

  const revisada = async (url) => {
    await api.post('/api/fontes/revisada', { url })
    carregar(); recarregar()
  }

  return (
    <>
      <Titulo sub="Regras usadas nas análises, fontes oficiais monitoradas e histórico de atualizações."
        acoes={<button className="btn-gold" disabled={atualizando} onClick={onAtualizar}><Icon name="atualizar" className={`h-4 w-4 ${atualizando ? 'animate-spin' : ''}`} />{atualizando ? 'Atualizando...' : 'Atualizar agora'}</button>}>
        Base legal e atualizações
      </Titulo>

      <div className="mb-6 grid gap-4 md:grid-cols-4">
        <Kpi rotulo="Versão das regras" valor={regras?.versao || '—'} detalhe={regras ? `${regras.regras.length} regras · ${regras.origem}` : ''} />
        <Kpi rotulo="Última atualização" valor={status?.ultima_atualizacao ? dataHora(status.ultima_atualizacao.executado_em).split(' ')[0] : '—'} detalhe={status?.ultima_atualizacao ? dataHora(status.ultima_atualizacao.executado_em) : 'Nunca'} />
        <Kpi rotulo="Selic até" valor={status?.selic?.ate ? competencia(status.selic.ate) : '—'} detalhe="Banco Central, série 4390" />
        <Kpi rotulo="Fontes a revisar" valor={String(status?.fontes_pendentes?.length || 0)} tom={status?.fontes_pendentes?.length ? 'verificar' : undefined} detalhe={`${fontes.length} fontes monitoradas`} />
      </div>

      {status?.fontes_pendentes?.length > 0 && (
        <div className="mb-5 space-y-2">
          {status.fontes_pendentes.map((f) => (
            <Aviso key={f.url}>
              <b>{f.nome}</b> mudou em {dataHora(f.alterado_em)}. Leia a alteração e confira se alguma regra precisa mudar.{' '}
              <a className="underline" href={f.url} target="_blank" rel="noreferrer">Abrir texto oficial</a>{' · '}
              <button className="font-semibold underline" onClick={() => revisada(f.url)}>Marcar como revisada</button>
            </Aviso>
          ))}
        </div>
      )}

      <div className="mb-4 flex gap-1 border-b border-line">
        {[['regras', 'Regras de NCM'], ['teses', 'Teses'], ['fontes', 'Fontes oficiais'], ['hist', 'Histórico']].map(([k, n]) => (
          <button key={k} onClick={() => setAba(k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold ${aba === k ? 'border-gold text-navy' : 'border-transparent text-muted hover:text-navy'}`}>{n}</button>
        ))}
      </div>

      {aba === 'regras' && regras && (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead className="bg-navy-50"><tr><th className="th">Grupo</th><th className="th">Tipo</th><th className="th">NCMs (prefixos)</th><th className="th">Fundamento</th><th className="th">Confiança</th></tr></thead>
            <tbody>
              {regras.regras.map((r) => (
                <tr key={r.codigo} className="align-top">
                  <td className="td font-medium">{r.grupo}<div className="text-xs text-muted">{r.vigencia}</div></td>
                  <td className="td"><span className="chip bg-navy-50 text-navy">{r.tipo === 'MONOFASICO' ? 'Monofásico · CST 04' : 'Alíquota zero · CST 06'}</span></td>
                  <td className="td max-w-[260px] font-mono text-[11px] leading-5">{r.prefixos.join(', ')}{r.excecoes.length ? <div className="text-bad">exceto {r.excecoes.join(', ')}</div> : null}</td>
                  <td className="td max-w-[420px] text-xs">{r.fundamento}{r.observacao && <div className="mt-1 text-muted">{r.observacao}</div>}</td>
                  <td className="td"><Confianca v={r.confianca} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {aba === 'teses' && regras && (
        <div className="grid gap-4 md:grid-cols-2">
          {Object.entries(regras.teses).map(([k, t]) => (
            <div key={k} className="card p-5">
              <div className="font-semibold text-navy">{t.nome}</div>
              <p className="mt-2 text-xs text-muted">{t.fundamento}</p>
            </div>
          ))}
        </div>
      )}
      {aba === 'fontes' && (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead className="bg-navy-50"><tr><th className="th">Fonte</th><th className="th">Verificada em</th><th className="th">Última alteração</th><th className="th" /></tr></thead>
            <tbody>
              {fontes.map((f) => (
                <tr key={f.url}>
                  <td className="td"><a className="font-medium text-navy hover:underline" href={f.url} target="_blank" rel="noreferrer">{f.nome}</a></td>
                  <td className="td text-muted">{dataHora(f.verificado_em)}</td>
                  <td className="td text-muted">{f.alterado_em ? dataHora(f.alterado_em) : '—'}</td>
                  <td className="td text-right">{f.pendente_revisao ? <button className="btn-ghost !py-1 text-xs" onClick={() => revisada(f.url)}>Marcar como revisada</button> : <span className="text-xs text-ok">em dia</span>}</td>
                </tr>
              ))}
              {fontes.length === 0 && <tr><td className="td py-8 text-center text-muted" colSpan={4}>As fontes são registradas na primeira atualização com internet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {aba === 'hist' && (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead className="bg-navy-50"><tr><th className="th">Quando</th><th className="th">Fonte</th><th className="th">Situação</th><th className="th">Detalhe</th></tr></thead>
            <tbody>
              {hist.map((h) => (
                <tr key={h.id}>
                  <td className="td whitespace-nowrap text-muted">{dataHora(h.executado_em)}</td>
                  <td className="td">{h.fonte}</td>
                  <td className={`td text-xs font-semibold ${ST[h.status] || ''}`}>{h.status}</td>
                  <td className="td text-xs text-muted">{h.detalhe}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
