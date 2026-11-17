# Recuperador de Tributos: arquitetura (versão 1.0)

Sistema local para auditoria de arquivos fiscais e identificação de créditos de PIS, COFINS e ICMS
pagos a maior ou não aproveitados nos últimos 60 meses. Roda inteiro no computador da usuária, sem
servidor externo.

## 1. Decisões de arquitetura

| Proposta original | Adotado | Motivo |
|---|---|---|
| Backend Python (FastAPI) | FastAPI | Mantido. API local em 127.0.0.1. |
| Pandas/Polars | Polars | Agrupamentos e filtros em grandes volumes. |
| PostgreSQL | SQLite | Banco embutido no programa: nada para instalar, backup é copiar um arquivo. O esquema é o mesmo (ver `sistema/app/schema.sql`). |
| Redis + Celery | Fila interna (ThreadPoolExecutor) | Um usuário só; importações e análises rodam em segundo plano sem serviço extra. |
| React/Next.js + Tailwind + Recharts | React + Vite + Tailwind + Recharts | Next.js exige servidor Node; Vite gera arquivos estáticos servidos pelo próprio FastAPI. |
| Excel e PDF | openpyxl e fpdf2 | Excel com memória de cálculo completa; PDF de resumo para o cliente. |

Janela própria: o programa abre no Microsoft Edge em modo aplicativo (sem barra de endereço), que
já vem em todo Windows 10/11. Python 3.12 portátil vai junto na pasta, então não há instalação.

## 2. Estrutura de pastas

```
RecuperadorTributos/
├── python/                         Python 3.12 portátil + bibliotecas (Lib/site-packages)
├── sistema/
│   ├── launcher.py                 sobe a API, abre a janela, atualiza a base ao abrir
│   ├── frontend_dist/              interface (React compilado)
│   └── app/
│       ├── main.py                 rotas da API
│       ├── config.py, db.py, schema.sql
│       ├── importador.py           grava SPED e XML no banco (sem duplicar, retificadora substitui original)
│       ├── updater.py              Selic (BCB), pacote de regras, monitoramento de leis
│       ├── parsers/
│       │   ├── sped_common.py      leitura de linhas, números, datas, tipo do arquivo
│       │   ├── efd.py              EFD-Contribuições e EFD ICMS/IPI
│       │   └── nfe_xml.py          NF-e/NFC-e, eventos de cancelamento, pastas e .zip
│       ├── engine/
│       │   ├── comum.py            Credito, prazo de 5 anos, Selic
│       │   ├── pis_cofins.py       MotorPisCofins
│       │   ├── icms.py             MotorIcms (inclui cruzamento XML x SPED)
│       │   └── runner.py           orquestra, aplica limites e grava
│       ├── rules/
│       │   ├── regras_base.json    NCMs, CFOPs, teses, fundamentos, roteiros
│       │   ├── fontes_oficiais.json
│       │   └── loader.py
│       └── reports/relatorios.py   Excel e PDF
├── atualizar_base.py               usado pela tarefa diária do Windows
├── Abrir Recuperador de Tributos.vbs
└── Criar atalho na Area de Trabalho.vbs
```

Dados do usuário: `%LOCALAPPDATA%\RecuperadorTributos` (banco, relatórios, regras atualizadas, log).

## 3. Modelo de dados

Tabelas principais (DDL completo em `sistema/app/schema.sql`):

- `empresas`: CNPJ, raiz do CNPJ (agrupa filiais), UF, regime (lido do registro 0110), atividade.
- `arquivos_sped`: cada arquivo importado, com hash SHA-256 (evita duplicidade) e finalidade.
- `notas_fiscais`: cabeçalho de documento (C100 do SPED ou XML), com chave e situação de cancelamento.
- `itens_nota`: itens com NCM, CFOP, CST de ICMS/PIS/COFINS, bases e valores (C170, C181/C185, C191/C195, XML).
- `apuracoes`: M200/M600 (PIS/COFINS a recolher) e E110 (ICMS).
- `tabela_ncm_regras`: espelho da base de regras (o arquivo JSON é a fonte).
- `analises` e `creditos_identificados`: resultado, com valor apurado, parte restituível, saldo credor,
  valor corrigido, natureza, via, fundamento, confiança e prazo.
- `revisoes_ncm`: decisões da usuária (confirmar/descartar NCM por tese e cliente).
- `selic`, `atualizacoes`, `fontes_monitoradas`: atualização diária e trilha de auditoria.

## 4. Regras implementadas

PIS/COFINS (EFD-Contribuições):
1. Revenda de monofásico com CST tributado (deveria ser 04). Leis 10.147/2000, 10.485/2002, 13.097/2015, 9.718/1998.
2. Venda de alíquota zero com CST tributado (deveria ser 06). Leis 10.865/2004 e 10.925/2004.
3. ICMS destacado na base das saídas (Tema 69 do STF; Pareceres SEI 7.698/2021 e 14.483/2021).
   Quando a EFD está consolidada (C180/C181), estima pelos XMLs.
4. Compras para revenda/insumo sem crédito (CST 70, 98, 99; e 73 quando o NCM não é de alíquota zero).
   Exclui monofásicos para revenda (STJ, Tema 1.093) e compras de pessoa física. Desde 05/2023 a base
   do crédito exclui o ICMS (Lei 14.592/2023).
5. Riscos: crédito sobre monofásico, ICMS na base do crédito após 05/2023, CST 04/06 sem regra.

ICMS (EFD ICMS/IPI + XMLs):
1. Produto que entrou com ST (CST 10/30/60/70 ou CSOSN 201/202/203/500) e saiu com ICMS próprio destacado.
2. Venda a consumidor abaixo da base presumida da ST (STF, Tema 201), por produto e mês, com unidade conferida.
3. Alíquota aplicada acima da interna da UF.
4. Cruzamento XML x SPED: ICMS destacado maior que o escriturado, nota de compra não escriturada,
   nota de venda não escriturada (risco).

Cálculo:
- Limite do recolhido: em PIS/COFINS, o que reduz a contribuição só vira restituição até o valor do
  campo 13 do M200/M600; débito indevido é alocado antes do crédito extemporâneo; o resto é saldo credor.
- Selic: acumulada do mês seguinte ao pagamento até o mês anterior à análise, mais 1%
  (Lei 9.250/1995, art. 39, § 4º). Créditos escriturais não são corrigidos.
- Prazo de 5 anos: do pagamento (restituição) ou da emissão (crédito). CTN, art. 168.
- Confiança: ALTA (regra objetiva), MEDIA (enquadramento ou destinação a confirmar), BAIXA (indício).
  Totais principais só somam ALTA e MEDIA.

## 5. Cadastro tributário sugerido (versão 1.2)

Para cada produto do cliente (cadastro 0200 e itens vendidos), o programa sugere e compara com o que o
cliente usa hoje:
- CST de PIS/COFINS (01, 04 ou 06), pelas mesmas regras e provas das teses de recuperação;
- CST de ICMS (regime normal) e CSOSN (Simples Nacional): 060/500 quando há compra do produto com ST,
  000/102 nos demais casos; a origem vem do CST das compras;
- CST de IBS/CBS e cClassTrib, pela tabela oficial (Informe Técnico 2025.002 v1.71) e pelos anexos da
  LC 214/2025 com as alterações da LC 227/2026: Anexo I (200003), XV (200014), VII (200034), VIII (200035),
  IV (200030), XII (200004), XIII (200007), saúde menstrual art. 147 (200013), medicamentos art. 133
  (200032) e soros/vacinas (200053); sem enquadramento, 000001;
- NBS: só para serviços.
Divergências entre o uso atual (XMLs de venda e EFD) e o sugerido aparecem em destaque.

## 6. Atualização da base

- Ao abrir o programa (se a última atualização tem mais de 20 h), pelo botão "Atualizar agora" e por
  tarefa diária do Agendador do Windows (07:30).
- Selic: API do Banco Central, série SGS 4390.
- Leis monitoradas: o texto oficial (Planalto, Sefaz/SC) é baixado e comparado com a versão anterior;
  mudança gera alerta "revisar regras" e entra como aviso em toda análise até ser marcada como revisada.
- Pacote de regras: se um endereço for configurado, a versão nova do JSON é validada e instalada.
- Cada análise registra a versão das regras, a data da última atualização e a Selic usada.

## 7. Testes

`backend/tests/test_motor.py` monta EFD-Contribuições, EFD ICMS/IPI e XMLs com valores conhecidos e
confere cada tese, o limite do recolhido, a Selic e a não duplicidade de importação.
