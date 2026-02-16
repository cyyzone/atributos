import streamlit as st
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta

# --- IMPORTAÇÃO DO UTILS (Pega da pasta pai) ---
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from utils import check_password
except ImportError:
    st.error("Erro: utils.py não encontrado.")
    st.stop()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Minhas Metas", page_icon="🎯", layout="wide")

# --- LOGIN ---
if not check_password():
    st.stop()

# --- CONFIGURAÇÕES DO INTERCOM ---
WORKSPACE_ID = "xwvpdtlu"
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.text_input("Intercom Token", type="password")
    if not INTERCOM_ACCESS_TOKEN: st.stop()

HEADERS = {"Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}", "Accept": "application/json"}

# --- FUNÇÕES (Reaproveitadas simplificadas) ---

@st.cache_data(ttl=3600)
def get_admin_list():
    """Busca lista de analistas para o dropdown"""
    url = "https://api.intercom.io/admins"
    try:
        r = requests.get(url, headers=HEADERS)
        admins = r.json().get('admins', [])
        # Cria um dicionario {Nome: ID} e uma lista só de nomes
        mapa = {a['name']: a['id'] for a in admins}
        return mapa
    except:
        return {}

@st.cache_data(ttl=3600)
def get_attribute_definitions():
    """Busca os nomes dos atributos"""
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_my_conversations(start_date, end_date, admin_id):
    """Busca conversas FILTRADAS pelo ID do Analista"""
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp())
    
    # AQUI É O PULO DO GATO: Filtramos direto na API pelo admin_assignee_id
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start},
        {"field": "created_at", "operator": "<", "value": ts_end},
        {"field": "admin_assignee_id", "operator": "=", "value": admin_id} # Só as minhas!
    ]
    
    payload = {
        "query": {"operator": "AND", "value": query_rules},
        "pagination": {"per_page": 150}
    }
    
    conversas = []
    has_more = True
    
    # Barra de progresso visual
    bar = st.progress(0, text="Buscando suas conversas...")
    
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            
            # Atualiza barra (efeito visual apenas)
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
st.markdown("Acompanhe sua meta de classificação diária.")

# 1. Seletor de "Quem sou eu?"
mapa_admins = get_admin_list()
if mapa_admins:
    nomes_ordenados = sorted(list(mapa_admins.keys()))
    col_sel, col_data, col_btn = st.columns([2, 2, 1])
    
    with col_sel:
        # Tenta achar o usuário pelo histórico ou pega o primeiro
        usuario_selecionado = st.selectbox("👤 Quem é você?", nomes_ordenados, key="sel_analista")
    
    with col_data:
        data_hoje = datetime.now()
        periodo = st.date_input("Período de Análise:", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    
    with col_btn:
        st.write("") # Espaço vazio para alinhar
        st.write("") 
        btn_atualizar = st.button("🔄 Atualizar Meus Dados", type="primary")

    # Só roda se tiver usuário selecionado
    if usuario_selecionado:
        admin_id_alvo = mapa_admins[usuario_selecionado]
        start, end = periodo
        
        # Busca dados
        raw = fetch_my_conversations(start, end, admin_id_alvo)
        mapa_attrs = get_attribute_definitions()
        
        if raw:
            # Processamento Rápido
            rows = []
            for c in raw:
                attrs = c.get('custom_attributes', {})
                
                # Tenta pegar Motivo (pelo nome bonito ou feio)
                motivo = None
                # Varre os atributos buscando "Motivo de Contato"
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
            
            # --- CÁLCULO DA META (O Coração do Painel) ---
            total = len(df)
            classificados = len(df[df["Motivo"].notna()])
            pendentes = total - classificados
            taxa = (classificados / total * 100) if total > 0 else 0
            
            st.divider()
            
            # --- KPI CARDS GIGANTES ---
            k1, k2, k3 = st.columns(3)
            
            k1.metric("Total de Conversas", total)
            
            k2.metric(
                "Conversas Pendentes", 
                pendentes, 
                delta="-Zerado!" if pendentes == 0 else f"{pendentes} para fazer",
                delta_color="inverse" # Vermelho se tiver pendencia, verde se zero
            )
            
            # Lógica da cor da meta
            cor_meta = "normal" if taxa >= 90 else "inverse" # Verde se > 90, Vermelho se < 90
            k3.metric(
                "Minha Taxa de Classificação", 
                f"{taxa:.1f}%", 
                delta="Meta: 90%",
                delta_color=cor_meta 
            )

            # Barra de Progresso Visual da Meta
            st.write("Progresso da Meta:")
            
            # Cor da barra muda se bater a meta
            cor_barra = "#28a745" if taxa >= 90 else "#dc3545" # Verde ou Vermelho
            st.markdown(f"""
                <style>
                    .stProgress > div > div > div > div {{
                        background-color: {cor_barra};
                    }}
                </style>""", unsafe_allow_html=True)
            st.progress(min(taxa / 100, 1.0))
            
            if taxa < 90:
                st.warning(f"⚠️ Atenção, {usuario_selecionado}! Você precisa classificar mais **{int((0.9 * total) - classificados) + 1}** conversas para bater a meta hoje.")
            else:
                st.success(f"🎉 Parabéns, {usuario_selecionado}! Meta batida com sucesso!")

            st.divider()

            # --- LISTA DE TAREFAS (Ação) ---
            tab_pendentes, tab_todos = st.tabs(["🚨 Pendências (Fazer Agora)", "📋 Histórico Completo"])
            
            with tab_pendentes:
                df_pendentes = df[df["Status"] == "🚨 Pendente"]
                
                if not df_pendentes.empty:
                    st.write(f"Você tem **{len(df_pendentes)} conversas** sem motivo classificado.")
                    st.info("💡 Clique no link 'Abrir' para ir direto ao Intercom e preencher o motivo.")
                    
                    st.dataframe(
                        df_pendentes[["Data", "ID", "Link"]],
                        use_container_width=True,
                        column_config={
                            "Link": st.column_config.LinkColumn("Link Intercom", display_text="🔗 Abrir Conversa")
                        },
                        hide_index=True
                    )
                else:
                    st.balloons()
                    st.success("Nada pendente! Tudo classificado. 🚀")

            with tab_todos:
                st.dataframe(
                    df[["Data", "ID", "Motivo", "Status", "Link"]],
                    use_container_width=True,
                    column_config={
                        "Link": st.column_config.LinkColumn("Link", display_text="Abrir")
                    },
                    hide_index=True
                )

        else:
            st.info("Nenhuma conversa encontrada neste período para este analista.")
