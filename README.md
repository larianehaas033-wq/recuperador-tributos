# Recuperador de Tributos

Repositório de atualizações do Recuperador de Tributos (HGL).

| Arquivo | Para que serve |
|---|---|
| `versao.json` | Versão mais recente, notas e assinatura (SHA-256) do pacote. O programa consulta todo dia. |
| `atualizacoes/sistema-X.Y.Z.zip` | Pacote baixado pelo botão **Atualizar programa**. |
| `regras/regras.json` | Base de regras (NCM, teses, cClassTrib). Baixada na atualização diária. |
| `codigo/` | Código-fonte (backend Python/FastAPI, interface React, scripts de montagem). |

Nenhum dado de cliente fica neste repositório: tudo o que o programa importa e calcula fica só no
computador onde ele roda (`%LOCALAPPDATA%\RecuperadorTributos`).
