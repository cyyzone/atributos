import streamlit as st 
import pandas as pd
import requests
import time
import plotly.express as px
from datetime import datetime, timedelta
from io import BytesIO

# --- IMPORTAÇÃO DO UTILS ---
try:
    from utils import check_password
except ImportError:
    st.error("Arquivo utils.py não encontrado. Certifique-se de que ele está na mesma pasta.")
    st.stop()

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Relatório de Atributos Intercom", page_icon="📊", layout="wide")

# --- BLOQUEIO DE SENHA ---
if not check_password():
    st.stop()

WORKSPACE_ID = "xwvpdtlu"

# --- AUTENTICAÇÃO INTERCOM ---
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input(
        "Intercom Token", 
        type="password", 
        key="meu_token_fixo"
    )

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configure o Token para continuar.")
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}",
    "Accept": "application/json"
}

# --- FUNÇÕES ---

def format_sla_string(seconds):
    """
    Converte segundos em formato legível.
    - Se for longo: 1d 2h 30m
    - Se for curto (menos de 1h): 15m 30s
    """
    if not seconds or pd.isna(seconds) or seconds == 0:
        return "-"
    
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
    
    # Exibe segundos apenas se for menos de 1 hora
    if days == 0 and hours == 0:
        parts.append(f"{secs}s")
    
    if not parts: return "< 1s"
    return " ".join(parts)

@st.cache_data(ttl=3600)
def get_attribute_definitions():
    """Busca os nomes bonitos dos atributos"""
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

@st.cache_data(ttl=3600)
def get_all_admins():
    """Busca a lista de todos os agentes (ID -> Nome)"""
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

    payload = {
        "query": {"operator": "AND", "value": query_rules},
        "pagination": {"per_page": 150}
    }
    
    conversas = []
    has_more = True
    status_text = st.empty()
    
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            status_text.caption(f"📥 Baixando... {len(conversas)} conversas encontradas.")
            
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
        
        # Pega nome do atendente
        admin_id = c.get('admin_assignee_id')
        if admin_id:
            assignee_name = admin_map.get(str(admin_id), f"ID {admin_id}")
        else:
            assignee_name = "Não atribuído"

        # --- CAPTURA DO CSAT ---
        rating_data = c.get('conversation_rating') or {}
        csat_score = rating_data.get('rating') 
        csat_comment = rating_data.get('remark')
        
        # --- CÁLCULO DE TEMPOS (SLA) ---
        stats = c.get('statistics') or {}
        
        # 1. Tempo para primeira resposta (segundos)
        time_reply_sec = stats.get('time_to_admin_reply') or stats.get('response_time')
        
        # 2. Tempo total para resolução (segundos)
        time_close_sec = stats.get('time_to_close')
        
        # Fallback
        if not time_close_sec:
            last_close_at = stats.get('last_close_at')
            created_at = c.get('created_at')
            if last_close_at and created_at:
                time_close_sec = last_close_at - created_at
        
        # Strings formatadas
        sla_resolucao_str = format_sla_string(time_close_sec)
        sla_resposta_str = format_sla_string(time_reply_sec)

        row = {
            "ID": c['id'],
            "timestamp_real": c['created_at'], 
            "Data": datetime.fromtimestamp(c['created_at']).strftime("%d/%m/%Y %H:%M"),
            "Data_Dia": datetime.fromtimestamp(c['created_at']).strftime("%Y-%m-%d"),
            "Atendente": assignee_name,
            "Link": link,
            "CSAT Nota": csat_score,
            "CSAT Comentario": csat_comment,
            "Tempo Resposta (seg)": time_reply_sec,   # Numérico
            "Tempo Resolução (seg)": time_close_sec,  # Numérico
            "Tempo Resposta": sla_resposta_str,       # Texto
            "Tempo Resolução": sla_resolucao_str      # Texto
        }
        
        attrs = c.get('custom_attributes', {})
        for key, value in attrs.items():
            nome_bonito = mapping.get(key)
            if nome_bonito:
                row[nome_bonito] = value
            else:
                row[key] = value
        rows.append(row)
    
    df = pd.DataFrame(rows)
    
    coluna_teimosa = "Motivo 2 (Se houver)"
    if not df.empty and coluna_teimosa not in df.columns:
        df[coluna_teimosa] = None 

    if not df.empty:
        df = df.sort_values(by="timestamp_real", ascending=True)
        df = df.reset_index(drop=True)
        
    return df

def gerar_excel_multias(df, colunas_selecionadas):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        
        # 1. Abas de Totais
        for col in colunas_selecionadas:
            if col in df.columns and col not in ["Data", "Link", "ID", "Qtd. Atributos"]:
                try:
                    resumo = df[col].value_counts().reset_index()
                    resumo.columns = [col, 'Quantidade']
                    nome_aba = col[:30].replace(":", "").replace("/", "-").replace("?", "").replace("*", "").replace("(", "").replace(")", "")
                    resumo.to_excel(writer, index=False, sheet_name=nome_aba)
                    writer.sheets[nome_aba].set_column('A:A', 50)
                except Exception as e:
                    pass

        # 2. Aba Base Completa
        cols_fixas = ["Data", "Atendente", "Tempo Resposta", "Tempo Resolução", "CSAT Nota", "CSAT Comentario", "Link", "Qtd. Atributos"]
        cols_extras = [c for c in colunas_selecionadas if c not in cols_fixas]
        cols_finais = cols_fixas + cols_extras
        
        cols_existentes = [c for c in cols_finais if c in df.columns]
        
        df[cols_existentes].to_excel(writer, index=False, sheet_name='Base Completa')
        writer.sheets['Base Completa'].set_column('A:A', 18) 
        
    return output.getvalue()

# --- INTERFACE ---

st.title(f"📊 Relatório de Atributos + SLA")

with st.sidebar:
    st.header("Filtros")
    if st.button("🧹 Limpar Cache"):
        st.cache_data.clear()
        st.success("Cache limpo!")

    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    team_input = st.text_input("IDs dos Times:", value="9156876")
    btn_run = st.button("🚀 Gerar Dados", type="primary")

if btn_run:
    start, end = periodo
    ids_times = [int(x.strip()) for x in team_input.split(",") if x.strip().isdigit()] if team_input else None
    
    with st.spinner("Analisando dados atuais e passados..."):
        mapa = get_attribute_definitions()
        admins_map = get_all_admins()
        
        # 1. Busca Período Atual
        raw = fetch_conversations(start, end, ids_times)
        
        # 2. Busca Período Anterior (Para Delta)
        delta_days = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=delta_days - 1)
        
        raw_prev = fetch_conversations(prev_start, prev_end, ids_times)
        
        if raw:
            df = process_data(raw, mapa, admins_map)
            df_prev = process_data(raw_prev, mapa, admins_map) if raw_prev else pd.DataFrame()
            
            st.session_state['df_final'] = df
            st.session_state['df_prev'] = df_prev 
            
            try:
                st.toast(f"✅ Sucesso! {len(df)} conversas carregadas.")
            except:
                st.sidebar.success(f"✅ Sucesso! {len(df)} conversas carregadas.")
            
        else:
            st.warning("Nenhum dado encontrado para o período selecionado.")

if 'df_final' in st.session_state:
    df = st.session_state['df_final']
    df_prev = st.session_state.get('df_prev', pd.DataFrame())
    
    st.divider()
    
    # --- SELEÇÃO DE COLUNAS ---
    todas_colunas = list(df.columns)
    
    COL_EXPANSAO = "Expansão (Passagem de bastão para CSM)"
    sugestao = ["Tipo de Atendimento", COL_EXPANSAO, "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao_existente = [c for c in sugestao if c in todas_colunas]
    
    colunas_ignorar = ["ID", "timestamp_real", "Data", "Data_Dia", "Link", "Qtd. Atributos", "Atendente", "CSAT Nota", "CSAT Comentario", "Tempo Resposta (seg)", "Tempo Resolução (seg)", "Tempo Resposta", "Tempo Resolução"]
    
    cols_usuario = st.multiselect(
        "Selecione os atributos para análise:",
        options=[c for c in todas_colunas if c not in colunas_ignorar],
        default=padrao_existente,
        key="seletor_colunas_principal"
    )

    # --- CÁLCULO DE COMPLEXIDADE ---
    if cols_usuario:
        cols_para_contar = [c for c in cols_usuario if c not in colunas_ignorar + ["Status do atendimento", "Tipo de Atendimento"]]
        
        if cols_para_contar:
            df["Qtd. Atributos"] = df[cols_para_contar].notna().sum(axis=1)
        else:
            df["Qtd. Atributos"] = 0
    else:
        df["Qtd. Atributos"] = 0

    # --- RESUMO EXECUTIVO COM DELTA (5 COLUNAS) ---
    st.markdown("### 📌 Resumo do Período")
    
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    
    # 1. KPIs de Volume
    total_conv = len(df)
    preenchidos = df["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df.columns else 0
    
    total_conv_prev = len(df_prev)
    preenchidos_prev = df_prev["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df_prev.columns else 0
    
    delta_total = total_conv - total_conv_prev
    delta_preenchidos = preenchidos - preenchidos_prev
    
    # 2. KPI de Resolvidos
    resolvidos = 0
    resolvidos_prev = 0
    if "Status do atendimento" in df.columns:
        resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0]
    if not df_prev.empty and "Status do atendimento" in df_prev.columns:
        resolvidos_prev = df_prev[df_prev["Status do atendimento"] == "Resolvido"].shape[0]
    
    delta_resolvidos = resolvidos - resolvidos_prev
    
    # 3. KPI de Tempo (Média)
    col_tempo_seg = "Tempo Resolução (seg)"
    tempo_medio_seg = df[col_tempo_seg].mean() if col_tempo_seg in df.columns else 0
    tempo_medio_prev_seg = df_prev[col_tempo_seg].mean() if not df_prev.empty and col_tempo_seg in df_prev.columns else 0
    
    delta_tempo_seg = tempo_medio_seg - tempo_medio_prev_seg
    
    tempo_str = format_sla_string(tempo_medio_seg)
    tempo_prev_str = format_sla_string(tempo_medio_prev_seg)
    delta_str_human = format_sla_string(abs(delta_tempo_seg))
    
    # Formatação visual do Delta de Tempo
    delta_exibicao = None
    if delta_tempo_seg > 0: 
        delta_exibicao = f"{delta_str_human}" # Piorou (Aumentou)
    elif delta_tempo_seg < 0: 
        delta_exibicao = f"-{delta_str_human}" # Melhorou (Diminuiu)
    else: 
        delta_exibicao = "0s"

    # --- EXIBIÇÃO COM TOOLTIPS EXPLICATIVOS ---
    
    # KPI 1: Total
    kpi1.metric(
        "Total Conversas", 
        total_conv, 
        delta=delta_total,
        delta_color="inverse", # Menos chamados = Verde
        help=f"Período Anterior: {total_conv_prev} | Atual: {total_conv}"
    )
    
    # KPI 2: Classificados
    kpi2.metric(
        "Classificados", 
        f"{preenchidos}", 
        delta=delta_preenchidos,
        help=f"Período Anterior: {preenchidos_prev} | Atual: {preenchidos}"
    )
    
    # KPI 3: Resolvidos
    kpi3.metric(
        "Resolvidos", 
        resolvidos, 
        delta=delta_resolvidos,
        help=f"Período Anterior: {resolvidos_prev} | Atual: {resolvidos}"
    )
    
    # KPI 4: Tempo Médio
    kpi4.metric(
        "Tempo Médio", 
        tempo_str, 
        delta=delta_exibicao, 
        delta_color="inverse", # Menos tempo = Verde
        help=f"Anterior: {tempo_prev_str} ➡ Atual: {tempo_str}"
    )
    
    # KPI 5: Motivo Principal
    top_motivo_txt = "N/A"
    qtd_top = 0
    if "Motivo de Contato" in df.columns:
        counts = df["Motivo de Contato"].value_counts()
        if not counts.empty:
            full_name = counts.index[0]
            qtd_top = counts.values[0]
            top_motivo_txt = str(full_name).split(">")[-1].strip()
            
    kpi5.metric(
        "Principal Motivo",
        top_motivo_txt,
        f"{qtd_top} casos",
        delta_color="off" 
    )

    st.divider()

    # --- ABAS DE ANÁLISE ---
    tab_grafico, tab_equipe, tab_cruzamento, tab_motivos, tab_csat, tab_tempo, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe", "🔀 Cruzamentos", "🔗 Motivo x Motivo", "⭐ CSAT", "⏱️ Tempo & SLA", "📋 Detalhes & Export"])

    with tab_grafico:
        c1, c2 = st.columns([2, 1])
        with c1:
            if cols_usuario:
                graf_sel = st.selectbox("Atributo:", cols_usuario, key="sel_bar")
                df_clean = df[df[graf_sel].notna()]
                contagem = df_clean[graf_sel].value_counts().reset_index()
                contagem.columns = ["Opção", "Quantidade"]
                total_registros = contagem["Quantidade"].sum()
                contagem["Texto_Label"] = contagem["Quantidade"].apply(lambda x: f"{x} ({(x / total_registros * 100):.1f}%)")
                altura_dinamica = max(400, 150 + (len(contagem) * 35))
                fig_bar = px.bar(contagem, x="Quantidade", y="Opção", text="Texto_Label", title=f"Distribuição: {graf_sel}", orientation='h', height=altura_dinamica)
                fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.warning("Selecione atributos no topo.")
        with c2:
             if cols_usuario:
                 st.write("**Ranking Completo:**")
                 st.dataframe(df[graf_sel].value_counts(), use_container_width=True)

    with tab_equipe:
        st.subheader("Performance do Time")
        vol_por_agente = df['Atendente'].value_counts().reset_index()
        vol_por_agente.columns = ['Agente', 'Volume']
        total_geral_agentes = vol_por_agente['Volume'].sum()
        vol_por_agente['Label'] = vol_por_agente['Volume'].apply(lambda x: f"{x} ({(x/total_geral_agentes*100):.1f}%)")
        c1, c2 = st.columns([2, 1])
        c1.plotly_chart(px.bar(vol_por_agente, x='Agente', y='Volume', title="Volume de Conversas por Agente", text='Label'), use_container_width=True)
        c2.dataframe(vol_por_agente[['Agente', 'Volume']], hide_index=True, use_container_width=True)
        st.divider()
        st.subheader("🕵️ Detalhe por Agente")
        opcoes_cruzamento = ["Status do atendimento"] + [c for c in cols_usuario if c != "Status do atendimento"]
        cruzamento_agente = st.selectbox("Cruzar Atendente com:", opcoes_cruzamento, key="sel_cruzamento_agente")
        if cruzamento_agente in df.columns:
            df_agente_cross = df.dropna(subset=[cruzamento_agente])
            agrupado = df_agente_cross.groupby(["Atendente", cruzamento_agente]).size().reset_index(name='Qtd')
            agrupado['Total_Agente'] = agrupado.groupby("Atendente")['Qtd'].transform('sum')
            agrupado['Label'] = agrupado.apply(lambda x: f"{x['Qtd']} ({(x['Qtd'] / x['Total_Agente'] * 100):.1f}%)", axis=1)
            fig_ag = px.bar(agrupado, x="Atendente", y="Qtd", color=cruzamento_agente, text="Label", title=f"Distribuição de {cruzamento_agente} por Agente")
            st.plotly_chart(fig_ag, use_container_width=True)

    with tab_cruzamento:
        def plot_empilhado_pct(df_input, col_y, col_color, title):
            grouped = df_input.groupby([col_y, col_color]).size().reset_index(name='Qtd')
            grouped['Total_Grupo'] = grouped.groupby(col_y)['Qtd'].transform('sum')
            grouped['Label'] = grouped.apply(lambda x: f"{x['Qtd']} ({(x['Qtd']/x['Total_Grupo']*100):.0f}%)", axis=1)
            qtd_categorias_y = grouped[col_y].nunique()
            altura = max(500, 100 + (qtd_categorias_y * 30))
            fig = px.bar(grouped, y=col_y, x='Qtd', color=col_color, text='Label', orientation='h', title=title, height=altura)
            fig.update_layout(yaxis={'categoryorder':'total ascending'})
            return fig
        if "Motivo de Contato" in df.columns and "Status do atendimento" in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", "Status do atendimento"]), "Motivo de Contato", "Status do atendimento", "Status por Motivo"), use_container_width=True)
        if "Motivo de Contato" in df.columns and "Tipo de Atendimento" in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"]), "Motivo de Contato", "Tipo de Atendimento", "Tipo por Motivo"), use_container_width=True)
        if "Motivo de Contato" in df.columns and COL_EXPANSAO in df.columns:
            st.plotly_chart(plot_empilhado_pct(df.dropna(subset=["Motivo de Contato", COL_EXPANSAO]), "Motivo de Contato", COL_EXPANSAO, "Expansão por Motivo"), use_container_width=True)

    with tab_motivos:
        col_m1, col_m2 = "Motivo de Contato", "Motivo 2 (Se houver)"
        if col_m1 in df.columns and col_m2 in df.columns:
            ranking_global = pd.concat([df[col_m1], df[col_m2]]).value_counts().reset_index()
            ranking_global.columns = ["Motivo Unificado", "Incidência Total"]
            total_motivos = ranking_global["Incidência Total"].sum()
            ranking_global["Label"] = ranking_global["Incidência Total"].apply(lambda x: f"{x} ({(x/total_motivos*100):.1f}%)")
            c_rank1, c_rank2 = st.columns([2, 1])
            with c_rank1:
                fig_global = px.bar(ranking_global, x="Incidência Total", y="Motivo Unificado", orientation='h', text="Label", height=max(500, 100 + (len(ranking_global) * 30)))
                fig_global.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_global, use_container_width=True)
            with c_rank2:
                st.dataframe(ranking_global, use_container_width=True, hide_index=True)

    with tab_csat:
        if "CSAT Nota" not in df.columns:
             st.warning("Gere os dados novamente.")
        else:
            df_csat = df.dropna(subset=["CSAT Nota"])
            if df_csat.empty:
                st.info("Sem CSAT.")
            else:
                k1, k2 = st.columns(2)
                k1.metric("Média Geral CSAT", f"{df_csat['CSAT Nota'].mean():.2f}/5.0")
                k2.metric("Total de Avaliações", len(df_csat))
                
                # GRÁFICO 1: MÉDIA
                if "Motivo de Contato" in df.columns:
                    csat_por_motivo = df_csat.groupby("Motivo de Contato")["CSAT Nota"].mean().reset_index().sort_values("CSAT Nota")
                    fig_csat_avg = px.bar(csat_por_motivo, x="CSAT Nota", y="Motivo de Contato", orientation='h', text_auto='.2f', color="CSAT Nota", color_continuous_scale="RdYlGn", range_color=[1, 5])
                    fig_csat_avg.update_layout(coloraxis_showscale=False)
                    st.plotly_chart(fig_csat_avg, use_container_width=True)
                    
                    st.divider()
                    
                    # GRÁFICO 2: VOLUME (RESTAURADO)
                    st.subheader("Volume de Avaliações por Nota e Motivo")
                    df_csat["Nota Label"] = df_csat["CSAT Nota"].astype(int).astype(str)
                    
                    csat_grouped = df_csat.groupby(["Motivo de Contato", "Nota Label"]).size().reset_index(name='Qtd')
                    csat_grouped['Total_Motivo'] = csat_grouped.groupby("Motivo de Contato")['Qtd'].transform('sum')
                    csat_grouped['Label_Pct'] = csat_grouped.apply(lambda x: f"{x['Qtd']} ({(x['Qtd']/x['Total_Motivo']*100):.0f}%)", axis=1)

                    fig_csat_vol = px.bar(
                        csat_grouped, 
                        x="Qtd", 
                        y="Motivo de Contato", 
                        color="Nota Label", 
                        text="Label_Pct",
                        orientation='h',
                        category_orders={"Nota Label": ["1", "2", "3", "4", "5"]},
                        color_discrete_map={"1": "#FF4B4B", "2": "#FF8C00", "3": "#FFD700", "4": "#9ACD32", "5": "#008000"}
                    )
                    fig_csat_vol.update_layout(yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_csat_vol, use_container_width=True)

    with tab_tempo:
        st.header("⏱️ Análise de Tempo e SLA")
        
        col_res_seg = "Tempo Resolução (seg)"
        col_rep_seg = "Tempo Resposta (seg)"
        
        df_tempo = df.dropna(subset=[col_res_seg])
        
        if df_tempo.empty:
            st.warning("Não há dados de tempo de resolução disponíveis.")
        else:
            t1, t2, t3 = st.columns(3)
            med_resol_seg = df_tempo[col_res_seg].mean()
            med_resp_seg = df_tempo[col_rep_seg].mean()
            
            t1.metric("Tempo Médio de Resolução", format_sla_string(med_resol_seg))
            t2.metric("Tempo Médio 1ª Resposta", format_sla_string(med_resp_seg))
            t3.metric("Conversas consideradas", len(df_tempo))
            
            st.divider()
            
            # Gráfico 1: Velocidade por Agente
            st.subheader("⚡ Velocidade por Agente")
            tempo_agente = df_tempo.groupby("Atendente")[col_res_seg].mean().reset_index().sort_values(col_res_seg)
            tempo_agente["Label"] = tempo_agente[col_res_seg].apply(format_sla_string)
            
            fig_time_agente = px.bar(
                tempo_agente, 
                x=col_res_seg, 
                y="Atendente", 
                text="Label",  
                orientation='h', 
                title=f"Média de Tempo para Resolver (Menor é melhor)"
            )
            fig_time_agente.update_xaxes(showticklabels=False)
            st.plotly_chart(fig_time_agente, use_container_width=True)
            
            # Gráfico 2: Motivos mais demorados
            if "Motivo de Contato" in df.columns:
                st.divider()
                st.subheader("🐢 Motivos mais demorados")
                tempo_motivo = df_tempo.groupby("Motivo de Contato")[col_res_seg].mean().reset_index().sort_values(col_res_seg, ascending=False)
                tempo_motivo["Label"] = tempo_motivo[col_res_seg].apply(format_sla_string)
                
                h_motivo = max(400, 100 + (len(tempo_motivo) * 30))
                
                fig_time_motivo = px.bar(
                    tempo_motivo, 
                    x=col_res_seg, 
                    y="Motivo de Contato", 
                    text="Label",
                    orientation='h', 
                    height=h_motivo,
                    title=f"Média de Tempo por Motivo"
                )
                fig_time_motivo.update_xaxes(showticklabels=False)
                fig_time_motivo.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_time_motivo, use_container_width=True)

    with tab_tabela:
        if "CSAT Nota" not in df.columns:
            st.warning("⚠️ Dados antigos na memória.")
            st.info("👉 Limpe o cache e Gere os Dados novamente.")
            st.stop()
        
        c1, c2 = st.columns([3, 1])
        with c1:
            f1, f2 = st.columns(2)
            ocultar_vazios = f1.checkbox("Ocultar vazios", value=True, key="chk_ocultar_vazios")
            ver_complexas = f2.checkbox("🔥 Apenas complexas (2+ atributos)", key="chk_ver_complexas")
        with c2:
            excel_data = gerar_excel_multias(df, cols_usuario)
            st.download_button("📥 Baixar Excel", data=excel_data, file_name="relatorio_completo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

        df_view = df.copy()
        if ocultar_vazios: df_view = df_view[df_view["Qtd. Atributos"] > 0]
        if ver_complexas: df_view = df_view[df_view["Qtd. Atributos"] >= 2]

        st.divider()
        st.caption("🔎 Filtros Avançados")
        
        # Filtro Atendente
        agentes_unicos = sorted(df_view["Atendente"].astype(str).unique().tolist())
        sel_agentes = st.multiselect("Filtrar por Atendente:", agentes_unicos, key="filtro_agente_tab")
        if sel_agentes:
            df_view = df_view[df_view["Atendente"].isin(sel_agentes)]

        # Filtros Cascata
        col_f1, col_v1 = st.columns(2)
        with col_f1:
            coluna_1 = st.selectbox("1º Filtro (Atributo Principal):", ["(Todos)"] + cols_usuario, index=0, key="filtro_coluna_1")
        with col_v1:
            if coluna_1 != "(Todos)":
                opcoes_1 = sorted(df_view[coluna_1].astype(str).unique().tolist())
                valores_1 = st.multiselect(f"Selecione valores em '{coluna_1}':", options=opcoes_1, key="filtro_valores_1")
                if valores_1: df_view = df_view[df_view[coluna_1].astype(str).isin(valores_1)]

        if coluna_1 != "(Todos)":
            st.markdown("⬇️ *E dentro destes resultados...*")
            col_f2, col_v2 = st.columns(2)
            with col_f2:
                cols_restantes = [c for c in cols_usuario if c != coluna_1]
                coluna_2 = st.selectbox("2º Filtro (Atributo Refinamento):", ["(Nenhum)"] + cols_restantes, index=0, key="filtro_coluna_2")
            with col_v2:
                if coluna_2 != "(Nenhum)":
                    opcoes_2 = sorted(df_view[coluna_2].astype(str).unique().tolist())
                    valores_2 = st.multiselect(f"Selecione valores em '{coluna_2}':", options=opcoes_2, key=f"v2_{coluna_2}")
                    if valores_2: df_view = df_view[df_view[coluna_2].astype(str).isin(valores_2)]

        st.divider()
        st.write(f"**Resultados encontrados:** {len(df_view)}")
        
        fixas = ["Data", "Atendente", "Tempo Resposta", "Tempo Resolução", "CSAT Nota", "Link"]
        fixas_existentes = [c for c in fixas if c in df_view.columns]
        extras = [c for c in cols_usuario if c not in fixas_existentes]
        cols_display = fixas_existentes + extras

        st.dataframe(
            df_view[cols_display], 
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="🔗 Abrir"),
                "CSAT Nota": st.column_config.NumberColumn("CSAT", format="%d ⭐"),
                "Tempo Resolução": st.column_config.TextColumn("Tempo Resolução"),
                "Tempo Resposta": st.column_config.TextColumn("Tempo 1ª Resp")
            }
        )
