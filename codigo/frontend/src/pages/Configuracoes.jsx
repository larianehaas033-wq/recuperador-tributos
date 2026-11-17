import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Aviso, Icon, Titulo } from '../ui'

export default function Configuracoes({ status }) {
  const [cfg, setCfg] = useState(null)
  const [msg, setMsg] = useState(null)

  useEffect(() => { api.get('/api/configuracoes').then(setCfg) }, [])
  if (!cfg) return null

  const salvar = async (novo) => {
    const r = await api.post('/api/configuracoes', novo)
    setCfg(r)
    setMsg({ tipo: 'ok', texto: 'Configurações salvas.' })
  }

  const agendar = async () => {
    try {
      const r = await api.post('/api/agendar-atualizacao')
      setMsg({ tipo: 'ok', texto: r.mensagem })
    } catch (e) { setMsg({ tipo: 'erro', texto: e.message }) }
  }

  return (
    <>
      <Titulo sub="Como o programa se mantém atualizado e onde guarda os dados.">Configurações</Titulo>
      {msg && <div className="mb-4"><Aviso tipo={msg.tipo}>{msg.texto}</Aviso></div>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-5">
          <div className="font-semibold text-navy">Atualização diária</div>
          <p className="mt-1 text-sm text-muted">Toda atualização baixa a Selic do Banco Central, confere se o texto oficial das leis monitoradas mudou e, se houver endereço configurado, instala a nova versão das regras.</p>
          <label className="mt-4 flex items-center gap-3 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-navy" checked={!!cfg.atualizacao_automatica}
              onChange={(e) => salvar({ atualizacao_automatica: e.target.checked })} />
            Atualizar sozinho ao abrir o programa (se a última foi há mais de 20 horas)
          </label>
          <div className="mt-5 border-t border-line pt-4">
            <div className="text-sm font-medium">Atualizar todo dia, mesmo com o programa fechado</div>
            <p className="mt-1 text-xs text-muted">Cria uma tarefa no Agendador do Windows que roda às 07:30.</p>
            <button className="btn-primary mt-3" onClick={agendar}><Icon name="atualizar" />Agendar no Windows</button>
          </div>
        </div>

        <div className="card p-5">
          <div className="font-semibold text-navy">Pacote de regras</div>
          <p className="mt-1 text-sm text-muted">Endereço de onde o programa baixa novas versões das regras (arquivo JSON). Quando a lei muda, a versão nova publicada nesse endereço é instalada na próxima atualização.</p>
          <input className="input mt-4" placeholder="https://..." defaultValue={cfg.url_regras}
            onBlur={(e) => e.target.value !== cfg.url_regras && salvar({ url_regras: e.target.value.trim() })} />
          <p className="mt-2 text-xs text-muted">Sem endereço, o programa usa as regras que vieram com ele e continua avisando quando uma lei monitorada muda.</p>
        </div>

        <div className="card p-5 lg:col-span-2">
          <div className="font-semibold text-navy">Dados</div>
          <p className="mt-1 text-sm text-muted">Tudo fica no seu computador. Nada é enviado para fora, exceto as consultas de atualização (Banco Central e sites oficiais).</p>
          <div className="mt-3 rounded-md bg-navy-50 px-3 py-2 font-mono text-xs">{status?.pasta_dados}</div>
          <button className="btn-ghost mt-3" onClick={() => api.post('/api/abrir-pasta')}><Icon name="pasta" />Abrir pasta de relatórios</button>
          <div className="mt-4 text-xs text-muted">Versão do programa {status?.versao_programa}</div>
        </div>
      </div>
    </>
  )
}
