import streamlit as st
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
import sys
import os

# --- IMPORTAÇÃO DO UTILS ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from utils import check_password
except ImportError:
    st.error("Erro: utils.py não encontrado.")
    st.stop()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Minhas Metas", page_icon="🎯", layout="wide")

# --- LOGIN ---
nivel_acesso = check_password()
if not nivel_acesso:
    st.stop()

# --- CONFIGURAÇÕES DO INTERCOM ---
WORKSPACE_ID = "xwvpdtlu"
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.text_input("Intercom Token", type="password", key="token_analista_manual")
    if not INTERCOM_ACCESS_TOKEN: 
        st.stop()

HEADERS = {"Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}", "Accept": "application/json"}

# --- CONFIGURAÇÃO DE FILTROS FIXOS ---
# Apenas estes times serão considerados na busca
TIMES_PERMITIDOS_IDS = [2975006, 1972225]

# --- FUNÇÕES ---

@st.cache_data(ttl=3600)
def get_teams_list():
    """Busca a lista de times (ID -> Nome)"""
    url = "https://api.intercom.io/teams"
    try:
        r = requests.get(url, headers=HEADERS)
        teams = r.json().get('teams', [])
        return {t['name']: t['id'] for t in teams}
    except:
        return {}

@st.cache_data(ttl=3600)
def get_admin_list():
    """Busca lista de analistas e seus times"""
    url = "https://api.intercom.io/admins"
    try:
        r = requests.get(url, headers=HEADERS)
        admins = r.json().get('admins', [])
        
        dados_admins = {}
        for a in admins:
            dados_admins[a['name']] = {
                'id': a['id'],
                'team_ids': [int(tid) for tid in a.get('team_ids', [])]
            }
        return dados_admins
    except:
        return {}

@st.cache_data(ttl=3600)
def get_attribute_definitions():
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_my_conversations(start_date, end_date, admin_id):
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp())
    
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start},
        {"field": "created_at", "operator": "<", "value": ts_end},
        {"field": "admin_assignee_id", "operator": "=", "value": admin_id},
        {"field": "state", "operator": "=", "value": "closed"},
        # --- AQUI ESTÁ O BLOQUEIO DE BACKOFFICE ---
        # Garante que a conversa pertença EXCLUSIVAMENTE aos times permitidos
        {"field": "team_assignee_id", "operator": "IN", "value": TIMES_PERMITIDOS_IDS}
    ]
    
    payload = {
        "query": {"operator": "AND", "value": query_rules},
        "pagination": {"per_page": 150}
    }
    
    conversas = []
    has_more = True
    
    bar = st.progress(0, text="Buscando conversas fechadas...")
    
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            
            bar.progress(50, text=f"Baixado: {len(conversas)} conversas...")
            
            if data.get('pages', {}).get('next'):
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                time.sleep(0.1)
            else:
                has_more = False
        except:
            break
            
    bar.empty()
    return conversas

# --- INTERFACE DO ANALISTA ---

st.title("🎯 Painel do Analista: Minha Performance")
st.markdown("Acompanhe sua meta de classificação (Apenas conversas **fechadas** dos times de **Suporte**).")

# Carrega dados
dados_admins = get_admin_list()

if dados_admins:
    # --- FILTRAGEM DE ANALISTAS ---
    analistas_filtrados = []
    for nome, dados in dados_admins.items():
        if set(dados['team_ids']) & set(TIMES_PERMITIDOS_IDS):
            analistas_filtrados.append(nome)
            
    analistas_filtrados = sorted(analistas_filtrados)

    if not analistas_filtrados:
        st.error(f"Nenhum analista encontrado nos times {TIMES_PERMITIDOS_IDS}.")
        st.stop()

    col_analista, col_periodo, col_btn = st.columns([2, 2, 1])
    
    with col_analista:
        usuario_selecionado = st.selectbox("👤 Quem é você?", analistas_filtrados, key="sel_analista")
    
    with col_periodo:
        data_hoje = datetime.now()
        periodo = st.date_input("Período:", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    
    with col_btn:
        st.write("") 
        st.write("") 
        btn_atualizar = st.button("🔄 Atualizar", type="primary")

    if usuario_selecionado:
        admin_id_alvo = dados_admins[usuario_selecionado]['id']
        start, end = periodo
        
        with st.spinner("Analisando métricas..."):
            raw = fetch_my_conversations(start, end, admin_id_alvo)
            mapa_attrs = get_attribute_definitions()
        
        if raw:
            rows = []
            for c in raw:
                attrs = c.get('custom_attributes', {})
                
                motivo = None
                for k, v in attrs.items():
                    label = mapa_attrs.get(k, k)
                    if label == "Motivo de Contato":
                        motivo = v
                        break
                
                link = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{c['id']}"
                
                rows.append({
                    "ID": c['id'],
                    "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
                    "Motivo": motivo,
                    "Link": link,
                    "Status": "✅ Classificado" if motivo else "🚨 Pendente"
                })
            
            df = pd.DataFrame(rows)
            
            total = len(df)
            classificados = len(df[df["Motivo"].notna()])
            pendentes = total - classificados
            taxa = (classificados / total * 100) if total > 0 else 0
            
            st.divider()
            
            k1, k2, k3 = st.columns(3)
            
            k1.metric("Conversas de Suporte", total)
            
            k2.metric(
                "Pendentes de Classificação", 
                pendentes, 
                delta="-Zerado!" if pendentes == 0 else f"{pendentes} para fazer",
                delta_color="inverse"
            )
            
            cor_meta = "normal" if taxa >= 90 else "inverse"
            k3.metric(
                "Minha Taxa", 
                f"{taxa:.1f}%", 
                delta="Meta: 90%",
                delta_color=cor_meta 
            )

            st.write("Progresso da Meta:")
            cor_barra = "#28a745" if taxa >= 90 else "#dc3545"
            st.markdown(f"""<style>.stProgress > div > div > div > div {{ background-color: {cor_barra}; }}</style>""", unsafe_allow_html=True)
            st.progress(min(taxa / 100, 1.0))
            
            if taxa < 90:
                st.warning(f"⚠️ Atenção, {usuario_selecionado}! Faltam **{int((0.9 * total) - classificados) + 1}** conversas.")
            else:
                st.success(f"🎉 Parabéns! Meta batida!")

            st.divider()

            tab_pendentes, tab_todos = st.tabs(["🚨 Pendências", "📋 Histórico"])
            
            with tab_pendentes:
                df_pendentes = df[df["Status"] == "🚨 Pendente"]
                if not df_pendentes.empty:
                    st.write(f"Você tem **{len(df_pendentes)} conversas fechadas** sem motivo classificado.")
                    st.dataframe(
                        df_pendentes[["Data", "ID", "Link"]],
                        use_container_width=True,
                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="🔗 Abrir")},
                        hide_index=True
                    )
                else:
                    st.balloons()
                    st.success("Tudo limpo! 🚀")

            with tab_todos:
                st.dataframe(
                    df[["Data", "ID", "Motivo", "Status", "Link"]],
                    use_container_width=True,
                    column_config={"Link": st.column_config.LinkColumn("Link", display_text="Abrir")},
                    hide_index=True
                )

        else:
            st.info("Nenhuma conversa encontrada neste período para os times selecionados.")
