import React, { useCallback, useEffect, useState } from 'react'
import { aguardar, api, dataHora } from './api'
import { Icon } from './ui'
import Painel from './pages/Painel'
import Importar from './pages/Importar'
import Empresa from './pages/Empresa'
import Analise from './pages/Analise'
import BaseLegal from './pages/BaseLegal'
import Configuracoes from './pages/Configuracoes'

function lerRota() {
  const [view = 'painel', id] = window.location.hash.replace(/^#\/?/, '').split('/')
  return { view, id: id ? Number(id) : null }
}

export default function App() {
  const [rota, setRota] = useState(lerRota())
  const [status, setStatus] = useState(null)
  const [atualizando, setAtualizando] = useState(false)
  const [versao, setVersao] = useState(null)
  const [baixando, setBaixando] = useState(false)
  const carregarVersao = useCallback(() => api.get('/api/versao').then(setVersao).catch(() => {}), [])
  useEffect(() => { carregarVersao() }, [carregarVersao])

  const atualizarPrograma = async () => {
    setBaixando(true)
    try {
      const { job } = await api.post('/api/atualizar-programa')
      const r = await aguardar(job)
      alert(r.mensagem)
    } catch (e) {
      alert('Não foi possível atualizar: ' + e.message)
    } finally {
      setBaixando(false)
      carregarVersao()
    }
  }

  useEffect(() => {
    const f = () => setRota(lerRota())
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])

  const carregarStatus = useCallback(() => api.get('/api/status').then(setStatus).catch(() => {}), [])
  useEffect(() => {
    carregarStatus()
    const t = setInterval(carregarStatus, 60000)
    return () => clearInterval(t)
  }, [carregarStatus])

  const ir = (view, id) => { window.location.hash = id ? `/${view}/${id}` : `/${view}` }

  const atualizar = async () => {
    setAtualizando(true)
    try {
      const { job } = await api.post('/api/atualizar')
      await aguardar(job)
    } catch (e) {
      alert('Falha na atualização: ' + e.message)
    } finally {
      setAtualizando(false)
      carregarStatus()
      carregarVersao()
    }
  }

  const menu = [
    ['painel', 'Painel', 'painel'],
    ['importar', 'Importar arquivos', 'importar'],
    ['base', 'Base legal e atualizações', 'lei'],
    ['config', 'Configurações', 'config'],
  ]
  const ativo = rota.view === 'empresa' || rota.view === 'analise' ? 'painel' : rota.view

  const desatualizada = status?.base_desatualizada
  const pendentes = status?.fontes_pendentes?.length || 0

  let pagina
  if (rota.view === 'importar') pagina = <Importar ir={ir} />
  else if (rota.view === 'empresa') pagina = <Empresa id={rota.id} ir={ir} />
  else if (rota.view === 'analise') pagina = <Analise id={rota.id} ir={ir} status={status} />
  else if (rota.view === 'base') pagina = <BaseLegal status={status} onAtualizar={atualizar} atualizando={atualizando} recarregar={carregarStatus} />
  else if (rota.view === 'config') pagina = <Configuracoes status={status} />
  else pagina = <Painel ir={ir} status={status} />

  return (
    <div className="flex h-full">
      <aside className="flex w-60 flex-none flex-col bg-navy text-white">
        <div className="px-5 pb-6 pt-6">
          <div className="flex items-center gap-2.5">
            <img src="./icone.png" alt="" className="h-9 w-9 rounded-md ring-1 ring-white/10" />
            <div className="leading-tight">
              <div className="text-[15px] font-bold">Recuperador</div>
              <div className="text-[11px] text-white/60">de Tributos</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {menu.map(([k, nome, ic]) => (
            <button key={k} onClick={() => ir(k)}
              className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${ativo === k ? 'bg-white/10 font-semibold text-white' : 'text-white/70 hover:bg-white/5 hover:text-white'}`}>
              <Icon name={ic} />{nome}
              {k === 'base' && pendentes > 0 && <span className="ml-auto rounded bg-gold px-1.5 text-[10px] font-bold text-navy">{pendentes}</span>}
            </button>
          ))}
        </nav>
        {versao?.nova && (
          <div className="mx-3 rounded-md border border-gold/60 bg-gold/10 p-3 text-xs">
            <div className="font-semibold text-gold">Nova versão {versao.disponivel}</div>
            {versao.baixada ? (
              <div className="mt-1 text-white/80">Já baixada. Feche e abra o programa para usar.</div>
            ) : (
              <>
                {versao.notas?.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-4 text-white/70">{versao.notas.slice(0, 3).map((n, i) => <li key={i}>{n}</li>)}</ul>}
                <button onClick={atualizarPrograma} disabled={baixando}
                  className="mt-2 w-full rounded bg-white py-1.5 font-semibold text-navy hover:bg-gold-100 disabled:opacity-60">
                  {baixando ? 'Baixando...' : 'Atualizar programa'}
                </button>
              </>
            )}
          </div>
        )}
        <div className="m-3 rounded-md bg-white/5 p-3 text-xs">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${desatualizada ? 'bg-amber-400' : 'bg-emerald-400'}`} />
            <span className="font-semibold">{desatualizada ? 'Base desatualizada' : 'Base atualizada'}</span>
          </div>
          <div className="mt-1 text-white/60">
            {status?.ultima_atualizacao ? dataHora(status.ultima_atualizacao.executado_em) : 'Nunca atualizada'}
          </div>
          <div className="mt-0.5 text-white/60">Regras {status?.regras?.versao || '-'}</div>
          <button onClick={atualizar} disabled={atualizando}
            className="mt-2.5 flex w-full items-center justify-center gap-2 rounded bg-gold py-1.5 font-semibold text-navy hover:bg-gold-100 disabled:opacity-60">
            <Icon name="atualizar" className={`h-3.5 w-3.5 ${atualizando ? 'animate-spin' : ''}`} />
            {atualizando ? 'Atualizando...' : 'Atualizar agora'}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1280px] px-8 py-8">{pagina}</div>
      </main>
    </div>
  )
}
