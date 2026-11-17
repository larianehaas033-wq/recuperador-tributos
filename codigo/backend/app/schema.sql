-- Recuperador de Tributos - modelo de dados (SQLite)
-- Equivalente ao modelo PostgreSQL do projeto; SQLite foi escolhido por rodar
-- dentro do próprio programa, sem servidor de banco de dados.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS empresas (
    regime_manual TEXT,                          -- regime informado pelo usuário (sem EFD-Contribuições)
    id            INTEGER PRIMARY KEY,
    cnpj          TEXT NOT NULL UNIQUE,      -- CNPJ do estabelecimento principal (14 dígitos)
    raiz_cnpj     TEXT NOT NULL,             -- 8 primeiros dígitos (agrupa filiais)
    nome          TEXT,
    uf            TEXT,
    regime        TEXT,                      -- LUCRO_REAL, LUCRO_PRESUMIDO, SIMPLES, MISTO
    ind_ativ      TEXT,                      -- 0 industrial, 1 serviços, 2 comércio... (0000 EFD-Contribuições)
    criado_em     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS arquivos_sped (
    id            INTEGER PRIMARY KEY,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    tipo          TEXT NOT NULL,             -- EFD_CONTRIB, EFD_ICMS_IPI, XML_NFE
    nome          TEXT,
    caminho       TEXT,
    hash          TEXT NOT NULL UNIQUE,      -- SHA-256 do conteúdo (evita importar o mesmo arquivo 2x)
    periodo_ini   TEXT,
    periodo_fim   TEXT,
    finalidade    TEXT,                      -- original / retificadora
    regime        TEXT,                      -- EFD-Contribuições: regime do período (registro 0110)
    qtd_registros INTEGER,
    importado_em  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notas_fiscais (
    id            INTEGER PRIMARY KEY,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    arquivo_id    INTEGER NOT NULL REFERENCES arquivos_sped(id) ON DELETE CASCADE,
    origem        TEXT NOT NULL,             -- SPED_CONTRIB, SPED_ICMS, XML
    chave         TEXT,
    modelo        TEXT,
    serie         TEXT,
    numero        TEXT,
    data          TEXT,
    periodo       TEXT,                      -- AAAA-MM
    ind_oper      TEXT,                      -- 0 entrada, 1 saída
    ind_emit      TEXT,                      -- 0 emissão própria, 1 terceiros
    cnpj_emit     TEXT,
    cnpj_part     TEXT,
    crt_emit      TEXT,                      -- XML: regime tributário do emitente (1/2/4 = Simples Nacional)
    cod_sit       TEXT,
    cancelada     INTEGER DEFAULT 0,
    vl_doc        REAL,
    vl_icms       REAL,
    vl_icms_st    REAL,
    vl_pis        REAL,
    vl_cofins     REAL
);
CREATE INDEX IF NOT EXISTS ix_nf_chave ON notas_fiscais(chave);
CREATE INDEX IF NOT EXISTS ix_nf_emp ON notas_fiscais(empresa_id, origem, periodo);

CREATE TABLE IF NOT EXISTS itens_nota (
    id            INTEGER PRIMARY KEY,
    nota_id       INTEGER REFERENCES notas_fiscais(id) ON DELETE CASCADE,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    arquivo_id    INTEGER NOT NULL REFERENCES arquivos_sped(id) ON DELETE CASCADE,
    origem        TEXT NOT NULL,             -- registro de origem: C170, C181, C185, C191, C195, XML
    periodo       TEXT,
    data          TEXT,
    chave         TEXT,
    num_doc       TEXT,
    ind_oper      TEXT,
    cnpj_part     TEXT,
    num_item      TEXT,
    cod_item      TEXT,
    descricao     TEXT,
    ncm           TEXT,
    cfop          TEXT,
    unidade       TEXT,
    qtd           REAL,
    vl_item       REAL,
    vl_desc       REAL,
    cst_icms      TEXT,
    vl_bc_icms    REAL,
    aliq_icms     REAL,
    vl_icms       REAL,
    vl_bc_icms_st REAL,
    vl_icms_st    REAL,
    vl_ipi        REAL,
    cst_pis       TEXT,
    vl_bc_pis     REAL,
    aliq_pis      REAL,
    vl_pis        REAL,
    cst_cofins    TEXT,
    vl_bc_cofins  REAL,
    aliq_cofins   REAL,
    vl_cofins     REAL,
    cst_ibscbs    TEXT,
    cclasstrib    TEXT
);
CREATE INDEX IF NOT EXISTS ix_itens_emp ON itens_nota(empresa_id, origem, periodo);
CREATE INDEX IF NOT EXISTS ix_itens_chave ON itens_nota(chave);

CREATE TABLE IF NOT EXISTS produtos (
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    cod_item      TEXT NOT NULL,
    descricao     TEXT,
    ncm           TEXT,
    tipo_item     TEXT,                      -- 0200 TIPO_ITEM: 00 revenda, 01 matéria-prima, 07 uso e consumo...
    unidade       TEXT,
    PRIMARY KEY (empresa_id, cod_item)
);

CREATE TABLE IF NOT EXISTS apuracoes (
    id            INTEGER PRIMARY KEY,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    arquivo_id    INTEGER NOT NULL REFERENCES arquivos_sped(id) ON DELETE CASCADE,
    periodo       TEXT NOT NULL,
    tributo       TEXT NOT NULL,             -- PIS, COFINS, ICMS
    debitos       REAL,
    creditos      REAL,
    valor_recolher REAL,
    saldo_credor  REAL,
    UNIQUE (empresa_id, periodo, tributo)
);

CREATE TABLE IF NOT EXISTS tabela_ncm_regras (
    codigo        TEXT PRIMARY KEY,          -- identificador estável da regra
    tipo          TEXT NOT NULL,             -- MONOFASICO, ALIQ_ZERO, ICMS_ALIQ_UF
    grupo         TEXT,
    ncm_prefixos  TEXT NOT NULL,             -- JSON: lista de prefixos de NCM (só dígitos)
    excecoes      TEXT,                      -- JSON: prefixos excluídos
    uf            TEXT,
    valor         REAL,
    vigencia_ini  TEXT,
    vigencia_fim  TEXT,
    fundamento    TEXT NOT NULL,
    confianca     TEXT NOT NULL,             -- ALTA, MEDIA, BAIXA
    observacao    TEXT,
    versao_base   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analises (
    desatualizada INTEGER DEFAULT 0,             -- arquivos da empresa mudaram depois desta análise
    id            INTEGER PRIMARY KEY,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    criado_em     TEXT DEFAULT CURRENT_TIMESTAMP,
    periodo_ini   TEXT,
    periodo_fim   TEXT,
    versao_regras TEXT,
    base_atualizada_em TEXT,
    selic_ate     TEXT,
    data_corte_prescricao TEXT,
    status        TEXT,
    resumo_json   TEXT,
    avisos_json   TEXT
);

CREATE TABLE IF NOT EXISTS creditos_identificados (
    id            INTEGER PRIMARY KEY,
    analise_id    INTEGER NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
    modulo        TEXT,                      -- PIS_COFINS, ICMS, CRUZAMENTO
    tese          TEXT NOT NULL,
    tributo       TEXT NOT NULL,             -- PIS, COFINS, ICMS
    periodo       TEXT,
    data          TEXT,
    chave         TEXT,
    num_doc       TEXT,
    num_item      TEXT,                      -- número do item na nota (C170 / det nItem)
    cod_item      TEXT,
    descricao     TEXT,
    ncm           TEXT,
    cfop          TEXT,
    cst_escriturado TEXT,
    cst_correto   TEXT,
    base_original REAL,
    base_correta  REAL,
    valor_pago    REAL,
    valor_recuperar REAL,                    -- valor apurado da tese (antes de limites)
    valor_restituivel REAL,                  -- parte que vira dinheiro/compensação
    valor_saldo_credor REAL,                 -- parte que só vira saldo credor
    valor_corrigido REAL,                    -- restituível + Selic
    natureza      TEXT,                      -- RESTITUICAO, CREDITO_EXTEMPORANEO, RISCO
    via           TEXT,                      -- ADMINISTRATIVO_FEDERAL, ADMINISTRATIVO_ESTADUAL, JUDICIAL
    fundamento    TEXT,
    confianca     TEXT,
    regra_codigo  TEXT,
    prescrito     INTEGER DEFAULT 0,
    excluido      INTEGER DEFAULT 0,
    observacao    TEXT
);
CREATE INDEX IF NOT EXISTS ix_cred_analise ON creditos_identificados(analise_id, tese);
-- EFD ICMS/IPI: registro analítico do documento (C190), por CST/CFOP/alíquota. É o único detalhe das vendas
-- em NFC-e e NF-e própria no SPED Fiscal.
CREATE TABLE IF NOT EXISTS analitico_icms (
    id            INTEGER PRIMARY KEY,
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    arquivo_id    INTEGER NOT NULL REFERENCES arquivos_sped(id) ON DELETE CASCADE,
    nota_id       INTEGER REFERENCES notas_fiscais(id) ON DELETE CASCADE,
    cst_icms      TEXT,
    cfop          TEXT,
    aliq_icms     REAL,
    vl_opr        REAL,
    vl_bc_icms    REAL,
    vl_icms       REAL,
    vl_bc_icms_st REAL,
    vl_icms_st    REAL
);
CREATE INDEX IF NOT EXISTS ix_c190_emp ON analitico_icms(empresa_id);
CREATE INDEX IF NOT EXISTS ix_c190_nota ON analitico_icms(nota_id);
CREATE INDEX IF NOT EXISTS ix_c190_arq ON analitico_icms(arquivo_id);
-- chaves estrangeiras indexadas: exclusão de empresa/arquivo e consultas por nota ficam rápidas
CREATE INDEX IF NOT EXISTS ix_itens_nota ON itens_nota(nota_id);
CREATE INDEX IF NOT EXISTS ix_itens_arquivo ON itens_nota(arquivo_id);
CREATE INDEX IF NOT EXISTS ix_nf_arquivo ON notas_fiscais(arquivo_id);
CREATE INDEX IF NOT EXISTS ix_arq_empresa ON arquivos_sped(empresa_id);
CREATE INDEX IF NOT EXISTS ix_analises_empresa ON analises(empresa_id);

CREATE TABLE IF NOT EXISTS revisoes_ncm (
    empresa_id    INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    ncm           TEXT NOT NULL,
    tese          TEXT NOT NULL,
    decisao       TEXT NOT NULL,             -- CONFIRMADO, DESCARTADO
    revisado_em   TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (empresa_id, ncm, tese)
);

CREATE TABLE IF NOT EXISTS selic (
    competencia   TEXT PRIMARY KEY,          -- AAAA-MM
    taxa          REAL NOT NULL,             -- % no mês (BCB, série SGS 4390)
    atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS atualizacoes (
    id            INTEGER PRIMARY KEY,
    executado_em  TEXT DEFAULT CURRENT_TIMESTAMP,
    fonte         TEXT,
    status        TEXT,                      -- OK, ALTERADA, ERRO, SEM_MUDANCA
    detalhe       TEXT
);

CREATE TABLE IF NOT EXISTS fontes_monitoradas (
    url           TEXT PRIMARY KEY,
    nome          TEXT,
    hash          TEXT,
    verificado_em TEXT,
    alterado_em   TEXT,
    pendente_revisao INTEGER DEFAULT 0
);
