import streamlit as st
import requests
import json
from datetime import datetime
import sys
import os

# --- TENTA IMPORTAR UTILS (Para pegar a senha se der) ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from utils import check_password
    check_password()
except:
    pass # Se falhar, segue sem senha (apenas para teste)

st.set_page_config(page_title="Espião de Conversa", page_icon="🕵️", layout="wide")

st.title("🕵️ Espião de Conversa Intercom")
st.markdown("Cole o ID ou o Link da conversa para ver os dados brutos (JSON) que a API retorna.")

# --- CONFIGURAÇÃO TOKEN ---
try:
    TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    TOKEN = st.text_input("Cole seu Token do Intercom aqui:", type="password")

if not TOKEN:
    st.stop()

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# --- INPUT DO ID ---
input_valor = st.text_input("🆔 Digite o ID da Conversa (ex: 215473091617663):")

if st.button("🔍 Investigar Conversa", type="primary"):
    if not input_valor:
        st.warning("Digite um ID.")
    else:
        # Limpeza básica se a pessoa colar a URL inteira
        conversation_id = input_valor.split("/")[-1]
        
        with st.spinner("Invadindo o sistema do Intercom..."):
            url = f"https://api.intercom.io/conversations/{conversation_id}"
            resp = requests.get(url, headers=HEADERS)
            
            if resp.status_code == 200:
                data = resp.json()
                
                # --- DADOS CRITICOS PARA O FILTRO ---
                st.divider()
                st.subheader("🚨 O que está causando o aparecimento?")
                
                c1, c2, c3 = st.columns(3)
                
                team_id = data.get('team_assignee_id')
                admin_id = data.get('admin_assignee_id')
                state = data.get('state')
                
                c1.metric("ID do Time Atual", team_id, help="Se este ID for 2975006 ou 1972225, ele VAI aparecer no painel.")
                c2.metric("ID do Analista", admin_id)
                c3.metric("Status (State)", state)
                
                st.info(f"💡 **Análise:** O filtro do painel busca: `team_assignee_id` IN [2975006, 1972225]. Se o número ali em cima for um desses, é por isso que está aparecendo.")

                # --- ATRIBUTOS ---
                st.subheader("📋 Atributos Personalizados")
                st.json(data.get('custom_attributes', {}))
                
                # --- DADOS COMPLETOS ---
                with st.expander("Ver JSON Completo (Dados Brutos)"):
                    st.json(data)
                    
            else:
                st.error(f"Erro ao buscar: {resp.status_code}")
                st.write(resp.text)
