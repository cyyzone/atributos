# 📊 Painel de Inteligência de Atendimento (Intercom + Streamlit)

> **Status:** 🟢 Em Produção (v2.0)

Uma aplicação de **Business Intelligence (BI)** desenvolvida em Python e Streamlit para monitoramento avançado de operações de suporte via Intercom. O sistema conecta-se à API do Intercom para fornecer métricas de SLA, Qualidade (CSAT/DSAT), Produtividade e Classificação de Tickets.

---

## 🚀 Funcionalidades Principais

### 1. Visão Gerencial (Estratégico)
Focado em líderes e gestores para tomada de decisão baseada em dados.
* **KPIs em Tempo Real:** Volume total, tickets resolvidos, tempo médio de resolução e principais ofensores.
* **Análise de Qualidade (CSAT/DSAT):** Visualização de notas médias e volume de avaliações. Permite focar nas piores notas (DSAT) para planos de ação.
* **Matriz de Eficiência:** Gráfico de dispersão (Scatter Plot) cruzando *Volume de Atendimentos* x *Tempo de Resolução* para identificar alta performance e gargalos na equipe.
* **SLA e Tempos:** Monitoramento de tempo de primeira resposta e tempo total de resolução.
* **Cruzamento de Dados:** Análise multidimensional (ex: *Status por Motivo*, *Tipo de Atendimento por Status*).

### 2. Painel do Analista (Operacional)
Ferramenta tática para o dia a dia do time de suporte.
* **Gamificação de Metas:** Barra de progresso visual para a meta de classificação (Ex: 90%).
* **Gestão de Pendências:** Lista automática de tickets fechados que não foram classificados.
* **Ação Rápida:** Links diretos (`🔗 Abrir`) que levam à conversa específica no Intercom para correção imediata.
* **Filtros Inteligentes:** Ignora automaticamente tickets de *Back-office* para não prejudicar a meta.

### 3. Engenharia e Resiliência
* **Smart Retry (API):** Tratamento automático de erro `429 (Rate Limit)`. O sistema aguarda o tempo exato informado pelo header da API do Intercom antes de tentar novamente.
* **UX Anti-Crash:** O sistema valida dinamicamente se as colunas/atributos existem no período selecionado antes de renderizar os gráficos, evitando quebras de tela.
* **Cache Otimizado:** Uso de `@st.cache_data` para performance, com botão de limpeza manual.

## 📂 Estrutura do Projeto

```text
.
├── 1_📊_Relatorio_Gerencial.py    # (Home) Dashboard principal para gestão
├── pages/
│   ├── 2_🎯_Painel_do_Analista.py # Área logada para o time operacional
│   └── 3_📈_Relatorio_Categorias.py # Relatório V2 focado em cadastros e categorias
├── utils.py                       # Funções core (API, Auth, MongoDB, Slack)
├── requirements.txt               # Dependências do Python
└── .streamlit/
    └── secrets.toml               # (Não versionado) Tokens e Senhas
```
## 🛠️ Instalação e Configuração

### Pré-requisitos
* **Python 3.10+**
* Conta no **Intercom** com Token de Acesso

2. Instalar dependências
Recomenda-se usar um ambiente virtual (venv).
```
pip install -r requirements.txt
```
## 3. Configurar Segredos (secrets.toml)
Crie uma pasta .streamlit na raiz do projeto e, dentro dela, um arquivo chamado secrets.toml. Preencha com suas credenciais:
```
Ini, TOML
# Credenciais do Intercom
INTERCOM_TOKEN = "seu_token_aqui_comeca_com_dsk..."

# Senhas de Acesso ao Painel
SENHA_GESTOR = "senha_de_acesso"
SENHA_TIME = "senha_de_acesso"

# Opcionais (Integrações Extras)
MONGO_URI = "mongodb+srv://..."
SLACK_WEBHOOK = "[https://hooks.slack.com/](https://hooks.slack.com/)..."
```


## 🧠 Detalhes Técnicos
**Calculo do SLA:** O sistema utiliza uma lógica de fallback para garantir precisão no tempo de resolução:
* Busca o campo nativo time_to_close (segundos).
* Se nulo (comum em tickets reabertos), calcula: timestamp_fechamento - timestamp_criacao.

## Proteção de Dados
* Nenhum dado é salvo permanentemente no disco do servidor.
* A exportação para Excel é gerada em memória (BytesIO) e servida diretamente ao navegador.
* O controle de acesso diferencia visualizações de Gestor (acesso total) e Analista (apenas seus dados).
