import streamlit as st 
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO

# --- IMPORTAÇÃO DO UTILS ---
from utils import check_password, logout_button

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Relatório V2 - Categorias", page_icon="📈", layout="wide")

# --- BLOQUEIO DE SENHA ---
usuario = check_password()

if not usuario:
    st.stop()

if usuario == "analista":
    st.error("⛔ Acesso Negado: Área restrita à gestão.")
    st.stop()

WORKSPACE_ID = "xwvpdtlu"

# --- AUTENTICAÇÃO INTERCOM ---
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password", key="token_v2")

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configure o Token.")
    st.stop()

HEADERS = {"Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES ---

def format_sla_string(seconds):
    if not seconds or pd.isna(seconds) or seconds == 0: return "-"
    seconds = int(seconds)
    days = seconds // 86400
    rem = seconds % 86400
    hours = rem // 3600
    rem %= 3600
    minutes = rem // 60
    secs = rem % 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    if days == 0 and hours == 0: parts.append(f"{secs}s")
    return " ".join(parts) if parts else "< 1s"

@st.cache_data(ttl=3600)
def get_attribute_definitions():
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=3600)
def get_all_admins():
    url = "https://api.intercom.io/admins"
    try:
        r = requests.get(url, headers=HEADERS)
        return {str(a['id']): a['name'] for a in r.json().get('admins', [])}
    except:
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_conversations(start_date, end_date, team_ids=None):
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp())
    
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start},
        {"field": "created_at", "operator": "<", "value": ts_end}
    ]
    if team_ids:
        query_rules.append({"field": "team_assignee_id", "operator": "IN", "value": team_ids})

    payload = {"query": {"operator": "AND", "value": query_rules}, "pagination": {"per_page": 150}}
    
    conversas = []
    has_more = True
    status_text = st.empty()
    
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            status_text.caption(f"📥 Baixando... {len(conversas)} conversas.")
            
            if data.get('pages', {}).get('next'):
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                time.sleep(0.1)
            else:
                has_more = False
        except Exception as e:
            st.error(f"Erro: {e}")
            break
    status_text.empty()
    return conversas

def process_data(conversas, mapping, admin_map):
    rows = []
    for c in conversas:
        link = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{c['id']}"
        admin_id = c.get('admin_assignee_id')
        assignee_name = admin_map.get(str(admin_id), f"ID {admin_id}") if admin_id else "Não atribuído"

        # SLA
        stats = c.get('statistics') or {}
        time_reply_sec = stats.get('time_to_admin_reply') or stats.get('response_time')
        time_close_sec = stats.get('time_to_close')
        if not time_close_sec:
            if stats.get('last_close_at') and c.get('created_at'):
                time_close_sec = stats.get('last_close_at') - c.get('created_at')

        row = {
            "ID": c['id'],
            "timestamp_real": c['created_at'], 
            "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
            "Atendente": assignee_name,
            "Link": link,
            "Tempo Resolução (seg)": time_close_sec,
            "Tempo Resolução": format_sla_string(time_close_sec),
            "CSAT Nota": (c.get('conversation_rating') or {}).get('rating')
        }
        
        attrs = c.get('custom_attributes', {})
        for key, value in attrs.items():
            nome_bonito = mapping.get(key)
            if nome_bonito: row[nome_bonito] = value
            else: row[key] = value
        rows.append(row)
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(by="timestamp_real", ascending=True)
    return df

def gerar_excel_v2(df, colunas_selecionadas):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Aba Base Completa
        cols_fixas = ["Data", "Atendente", "Tempo Resolução", "Link"]
        cols_finais = cols_fixas + colunas_selecionadas
        cols_existentes = [c for c in cols_finais if c in df.columns]
        df[cols_existentes].to_excel(writer, index=False, sheet_name='Base V2')
        writer.sheets['Base V2'].set_column('A:A', 18)
        
        # Abas Individuais
        for col in colunas_selecionadas:
            if col in df.columns:
                try:
                    resumo = df[col].value_counts().reset_index()
                    resumo.columns = [col, 'Qtd']
                    nome_aba = col[:30].replace("/", "-")
                    resumo.to_excel(writer, index=False, sheet_name=nome_aba)
                except: pass
    return output.getvalue()

# --- INTERFACE ---

st.title("📈 Relatório V2: Categorias e Cadastros")

with st.sidebar:
    st.header("Filtros V2")
    if st.button("🧹 Limpar Cache"):
        st.cache_data.clear()
        st.success("Limpo!")

    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    team_input = st.text_input("IDs dos Times:", value="2975006")
    btn_run = st.button("🚀 Gerar Relatório V2", type="primary")
    logout_button()

if btn_run:
    start, end = periodo
    ids_times = [int(x.strip()) for x in team_input.split(",") if x.strip().isdigit()] if team_input else None
    
    with st.spinner("Buscando dados V2..."):
        mapa = get_attribute_definitions()
        admins_map = get_all_admins()
        raw = fetch_conversations(start, end, ids_times)
        
        if raw:
            df = process_data(raw, mapa, admins_map)
            st.session_state['df_v2'] = df
            st.toast(f"✅ {len(df)} conversas.")
        else:
            st.warning("Sem dados.")

if 'df_v2' in st.session_state:
    df = st.session_state['df_v2']
    st.divider()
    
    # --- CONFIGURAÇÃO DOS NOVOS ATRIBUTOS ---
    todas_colunas = list(df.columns)
    
    # Lista de prioridade V2
    sugestao_v2 = [
        "Tipo de Atendimento", 
        "Categoria do sistema", 
        "Cadastros", 
        "Equipe", 
        "Status do atendimento"
    ]
    
    # Filtra apenas os que existem no DataFrame atual
    padrao_existente = [c for c in sugestao_v2 if c in todas_colunas]
    
    cols_usuario = st.multiselect(
        "Atributos para Análise V2:",
        options=[c for c in todas_colunas if c not in ["ID", "Link", "Data", "Atendente", "Tempo Resolução"]],
        default=padrao_existente
    )

    # --- KPIs V2 ---
    st.markdown("### 📌 Resumo V2")
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.metric("Total Conversas", len(df))
    
    # KPI Resolvidos
    resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0] if "Status do atendimento" in df.columns else 0
    k2.metric("Resolvidos", resolvidos)
    
    # KPI Categoria Principal (Substituto do Motivo)
    top_cat = "N/A"
    qtd_cat = 0
    col_kpi_cat = "Categoria do sistema"
    if col_kpi_cat in df.columns:
        counts = df[col_kpi_cat].value_counts()
        if not counts.empty:
            top_cat = counts.index[0]
            qtd_cat = counts.values[0]
    k3.metric("Principal Categoria", str(top_cat)[:20], f"{qtd_cat} casos")

    # KPI Equipe Principal
    top_eq = "N/A"
    col_kpi_eq = "Equipe"
    if col_kpi_eq in df.columns:
        counts_eq = df[col_kpi_eq].value_counts()
        if not counts_eq.empty:
            top_eq = counts_eq.index[0]
    k4.metric("Equipe + Demandada", str(top_eq)[:20])

    # KPI Tempo
    col_tempo = "Tempo Resolução (seg)"
    tempo_med = df[col_tempo].mean() if col_tempo in df.columns else 0
    k5.metric("Tempo Médio", format_sla_string(tempo_med))

    st.divider()

    # --- ABAS ADAPTADAS PARA V2 ---
    tab_graf, tab_cross, tab_detalhe, tab_dados = st.tabs(["📊 Distribuição", "🔀 Categoria x Cadastros", "👥 Por Equipe", "📋 Tabela V2"])

    with tab_graf:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Visualizar por:", cols_usuario)
                df_clean = df[df[graf_sel].notna()]
                contagem = df_clean[graf_sel].value_counts().reset_index()
                contagem.columns = ["Opção", "Qtd"]
                total = contagem["Qtd"].sum()
                contagem["Label"] = contagem["Qtd"].apply(lambda x: f"{x} ({(x/total*100):.1f}%)")
                
                fig = px.bar(contagem, x="Qtd", y="Opção", text="Label", orientation='h', title=f"Distribuição: {graf_sel}")
                fig.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.write("Ranking:")
            if cols_usuario:
                st.dataframe(df[graf_sel].value_counts(), use_container_width=True)

    with tab_cross:
        st.subheader("Relacionamento: Categoria vs Cadastros")
        col_cat = "Categoria do sistema"
        col_cad = "Cadastros"
        
        if col_cat in df.columns and col_cad in df.columns:
            df_cross = df.dropna(subset=[col_cat, col_cad])
            grouped = df_cross.groupby([col_cat, col_cad]).size().reset_index(name='Qtd')
            grouped['Total'] = grouped.groupby(col_cat)['Qtd'].transform('sum')
            grouped['Pct'] = grouped.apply(lambda x: f"{(x['Qtd']/x['Total']*100):.0f}%", axis=1)
            
            fig_cross = px.bar(grouped, y=col_cat, x="Qtd", color=col_cad, text="Pct", orientation='h', title="Cadastros dentro de cada Categoria")
            fig_cross.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_cross, use_container_width=True)
        else:
            st.info(f"Os atributos '{col_cat}' e '{col_cad}' precisam existir nos dados para este gráfico.")

    with tab_detalhe:
        st.subheader("Análise do atributo 'Equipe'")
        if "Equipe" in df.columns:
            df_eq = df.dropna(subset=["Equipe"])
            vol_eq = df_eq["Equipe"].value_counts().reset_index()
            vol_eq.columns = ["Equipe", "Volume"]
            st.plotly_chart(px.pie(vol_eq, names="Equipe", values="Volume", title="Distribuição por Equipe"), use_container_width=True)
            
            st.subheader("Tempo de Resolução por Equipe")
            if "Tempo Resolução (seg)" in df.columns:
                tempo_eq = df_eq.groupby("Equipe")["Tempo Resolução (seg)"].mean().reset_index().sort_values("Tempo Resolução (seg)")
                tempo_eq["Label"] = tempo_eq["Tempo Resolução (seg)"].apply(format_sla_string)
                st.plotly_chart(px.bar(tempo_eq, x="Tempo Resolução (seg)", y="Equipe", text="Label", orientation='h'), use_container_width=True)
        else:
            st.warning("Atributo 'Equipe' não encontrado.")

    with tab_dados:
        c1, c2 = st.columns([3,1])
        with c2:
            excel = gerar_excel_v2(df, cols_usuario)
            st.download_button("📥 Baixar Relatório V2", data=excel, file_name="relatorio_v2.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        
        # Filtros Rápidos na Tabela
        col_filtro = st.selectbox("Filtrar tabela por:", ["(Todos)"] + cols_usuario)
        df_view = df.copy()
        
        if col_filtro != "(Todos)":
            vals = df_view[col_filtro].unique()
            sel_vals = st.multiselect(f"Valores em {col_filtro}:", vals)
            if sel_vals:
                df_view = df_view[df_view[col_filtro].isin(sel_vals)]
        
        st.dataframe(
            df_view[["Data", "Atendente", "Tempo Resolução"] + cols_usuario],
            use_container_width=True,
            column_config={"Link": st.column_config.LinkColumn("Link")}
        )
