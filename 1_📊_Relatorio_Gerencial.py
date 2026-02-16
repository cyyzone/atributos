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
st.set_page_config(page_title="Relatório Gerencial Intercom", page_icon="📊", layout="wide")

# --- BLOQUEIO DE SENHA ---
usuario = check_password()

if not usuario:
    st.stop()

if usuario == "analista":
    st.error("⛔ Acesso Negado: Área restrita à gestão.")
    st.info("Utilize o menu lateral para acessar o **Painel do Analista**.")
    st.stop()

WORKSPACE_ID = "xwvpdtlu"

# --- AUTENTICAÇÃO INTERCOM ---
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password", key="token_gerencial")

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
            "Tempo Resposta (seg)": time_reply_sec,
            "Tempo Resolução (seg)": time_close_sec,
            "Tempo Resposta": format_sla_string(time_reply_sec),
            "Tempo Resolução": format_sla_string(time_close_sec),
            "CSAT Nota": (c.get('conversation_rating') or {}).get('rating'),
            "CSAT Comentario": (c.get('conversation_rating') or {}).get('remark')
        }
        
        attrs = c.get('custom_attributes', {})
        for key, value in attrs.items():
            nome_bonito = mapping.get(key)
            if nome_bonito: row[nome_bonito] = value
            else: row[key] = value
        rows.append(row)
    
    df = pd.DataFrame(rows)
    coluna_teimosa = "Motivo 2 (Se houver)"
    if not df.empty and coluna_teimosa not in df.columns:
        df[coluna_teimosa] = None 
        
    if not df.empty:
        df = df.sort_values(by="timestamp_real", ascending=True)
    return df

def gerar_excel_multias(df, colunas_selecionadas):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for col in colunas_selecionadas:
            if col in df.columns and col not in ["Data", "Link", "ID", "Qtd. Atributos"]:
                try:
                    resumo = df[col].value_counts().reset_index()
                    resumo.columns = [col, 'Quantidade']
                    nome_aba = col[:30].replace("/", "-")
                    resumo.to_excel(writer, index=False, sheet_name=nome_aba)
                except: pass

        cols_fixas = ["Data", "Atendente", "Tempo Resposta", "Tempo Resolução", "CSAT Nota", "CSAT Comentario", "Link"]
        cols_finais = cols_fixas + [c for c in colunas_selecionadas if c not in cols_fixas]
        cols_existentes = [c for c in cols_finais if c in df.columns]
        df[cols_existentes].to_excel(writer, index=False, sheet_name='Base Completa')
        writer.sheets['Base Completa'].set_column('A:A', 18) 
    return output.getvalue()

# --- INTERFACE ---

st.title("📊 Relatório Gerencial: Atributos & SLA")

with st.sidebar:
    st.header("Filtros")
    if st.button("🧹 Limpar Cache"):
        st.cache_data.clear()
        st.success("Limpo!")

    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=7), data_hoje), format="DD/MM/YYYY")
    team_input = st.text_input("IDs dos Times:", value="2975006")
    btn_run = st.button("🚀 Gerar Dados", type="primary")
    logout_button()

if btn_run:
    start, end = periodo
    ids_times = [int(x.strip()) for x in team_input.split(",") if x.strip().isdigit()] if team_input else None
    
    with st.spinner("Analisando dados..."):
        mapa = get_attribute_definitions()
        admins_map = get_all_admins()
        raw = fetch_conversations(start, end, ids_times)
        
        if raw:
            df = process_data(raw, mapa, admins_map)
            st.session_state['df_final'] = df
            st.toast(f"✅ {len(df)} conversas carregadas.")
        else:
            st.warning("Nenhum dado encontrado.")

if 'df_final' in st.session_state:
    df = st.session_state['df_final']
    st.divider()
    
    # --- SELEÇÃO DE COLUNAS ---
    todas_colunas = list(df.columns)
    COL_EXPANSAO = "Expansão (Passagem de bastão para CSM)"
    sugestao = ["Tipo de Atendimento", COL_EXPANSAO, "Motivo de Contato", "Motivo 2 (Se houver)", "Status do atendimento"]
    padrao = [c for c in sugestao if c in todas_colunas]
    ignorar = ["ID", "timestamp_real", "Data", "Link", "Atendente", "CSAT Nota", "CSAT Comentario", "Tempo Resposta (seg)", "Tempo Resolução (seg)", "Tempo Resposta", "Tempo Resolução"]
    
    cols_usuario = st.multiselect("Atributos para análise:", [c for c in todas_colunas if c not in ignorar], default=padrao)

    # --- KPIs ---
    st.markdown("### 📌 Resumo")
    k1, k2, k3, k4, k5 = st.columns(5)
    
    total_conv = len(df)
    preenchidos = df["Motivo de Contato"].notna().sum() if "Motivo de Contato" in df.columns else 0
    resolvidos = df[df["Status do atendimento"] == "Resolvido"].shape[0] if "Status do atendimento" in df.columns else 0
    tempo_med = df["Tempo Resolução (seg)"].mean() if "Tempo Resolução (seg)" in df.columns else 0
    
    top_motivo = "N/A"
    if "Motivo de Contato" in df.columns:
        c = df["Motivo de Contato"].value_counts()
        if not c.empty: top_motivo = c.index[0].split(">")[-1].strip()

    k1.metric("Total Conversas", total_conv)
    k2.metric("Classificados", preenchidos)
    k3.metric("Resolvidos", resolvidos)
    k4.metric("Tempo Médio", format_sla_string(tempo_med))
    k5.metric("Top Motivo", top_motivo)

    st.divider()

    # --- ABAS ---
    tab_graf, tab_equipe, tab_cross, tab_motivos, tab_csat, tab_tempo, tab_tabela = st.tabs(["📊 Distribuição", "👥 Equipe & Performance", "🔀 Cruzamentos", "🔗 Top Motivos", "⭐ CSAT / DSAT", "⏱️ SLA", "📋 Dados"])

    with tab_graf:
        c_filt1, c_filt2 = st.columns([3, 1])
        with c_filt1:
            graf_sel = st.selectbox("Selecione o Atributo:", cols_usuario, key="sel_graf_dist")
        with c_filt2:
            qtd_dist = st.slider("Qtd. Itens:", 5, 50, 10, key="slider_dist_qtd")

        if cols_usuario:
            c1, c2 = st.columns([2, 1])
            
            df_clean = df[df[graf_sel].notna()]
            contagem = df_clean[graf_sel].value_counts().reset_index()
            contagem.columns = ["Opção", "Qtd"]
            contagem = contagem.head(qtd_dist) 
            
            total_registros = contagem["Qtd"].sum()
            contagem["Label"] = contagem.apply(lambda x: f"{x['Qtd']} ({(x['Qtd']/total_registros*100):.1f}%)", axis=1)
            contagem = contagem.sort_values("Qtd", ascending=False).reset_index(drop=True)

            with c1:
                altura_graf = max(600, len(contagem) * 50) 
                fig = px.bar(contagem, x="Qtd", y="Opção", text="Label", orientation='h', title=f"Distribuição: {graf_sel} (Top {qtd_dist})", height=altura_graf)
                fig.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig, use_container_width=True)
                
            with c2:
                st.write(f"**Ranking (Top {qtd_dist}):**")
                st.dataframe(contagem[["Opção", "Qtd"]], use_container_width=True, hide_index=True)
        else:
            st.warning("Selecione atributos no topo da página.")

    with tab_equipe:
        st.subheader("Volume de Conversas")
        vol = df['Atendente'].value_counts().reset_index()
        vol.columns = ['Agente', 'Volume']
        st.plotly_chart(px.bar(vol, x='Agente', y='Volume', text='Volume', height=500), use_container_width=True)
        
        st.divider()
        
        st.subheader("🚀 Matriz de Eficiência: Volume x Tempo")
        st.info("💡 **Como ler:** Analistas no canto **inferior direito** atendem muito e rápido. No **superior esquerdo**, atendem pouco e demoram (atenção).")
        
        if "Tempo Resolução (seg)" in df.columns:
            df_perf = df.groupby("Atendente").agg(Volume=('ID', 'count'), Tempo_Medio_Seg=('Tempo Resolução (seg)', 'mean')).reset_index()
            df_perf = df_perf[df_perf['Tempo_Medio_Seg'] > 0]
            df_perf['Tempo Médio'] = df_perf['Tempo_Medio_Seg'].apply(format_sla_string)
            
            fig_scatter = px.scatter(df_perf, x="Volume", y="Tempo_Medio_Seg", text="Atendente", size="Volume", color="Tempo_Medio_Seg", color_continuous_scale="RdYlGn_r", hover_data=["Tempo Médio"], title="Relação: Quem atende mais vs Quem demora mais", height=700)
            media_vol = df_perf["Volume"].mean()
            media_tempo = df_perf["Tempo_Medio_Seg"].mean()
            fig_scatter.add_vline(x=media_vol, line_dash="dash", line_color="gray", annotation_text="Média Vol.")
            fig_scatter.add_hline(y=media_tempo, line_dash="dash", line_color="gray", annotation_text="Média Tempo")
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.warning("Dados de tempo não disponíveis.")

    with tab_cross:
        qtd_cross = st.slider("Quantidade de itens no Ranking:", 5, 50, 10, key="slider_cross")

        def plot_stack(df_in, x_col, color_col, title, limit=10):
            top_n = df_in[x_col].value_counts().head(limit).index.tolist()
            df_filtered = df_in[df_in[x_col].isin(top_n)]
            g = df_filtered.groupby([x_col, color_col]).size().reset_index(name='Qtd')
            g['Total'] = g.groupby(x_col)['Qtd'].transform('sum')
            g['Pct'] = g.apply(lambda x: f"{(x['Qtd']/x['Total']*100):.0f}%", axis=1)
            h_dyn = max(600, len(top_n) * 50) 
            f = px.bar(g, y=x_col, x='Qtd', color=color_col, text='Pct', orientation='h', title=title, height=h_dyn)
            f.update_layout(yaxis={'categoryorder':'total ascending'})
            return f

        if "Motivo de Contato" in df.columns and "Status do atendimento" in df.columns:
            st.plotly_chart(plot_stack(df.dropna(subset=["Motivo de Contato", "Status do atendimento"]), "Motivo de Contato", "Status do atendimento", "1. Status por Motivo", qtd_cross), use_container_width=True)
        
        st.divider()

        if "Motivo de Contato" in df.columns and "Tipo de Atendimento" in df.columns:
            st.plotly_chart(plot_stack(df.dropna(subset=["Motivo de Contato", "Tipo de Atendimento"]), "Motivo de Contato", "Tipo de Atendimento", "2. Tipo por Motivo", qtd_cross), use_container_width=True)
        
        st.divider()
        
        if "Tipo de Atendimento" in df.columns and "Status do atendimento" in df.columns:
            st.plotly_chart(plot_stack(df.dropna(subset=["Tipo de Atendimento", "Status do atendimento"]), "Tipo de Atendimento", "Status do atendimento", "3. Status por Tipo de atendimento", qtd_cross), use_container_width=True)

    with tab_motivos:
        col_m1, col_m2 = "Motivo de Contato", "Motivo 2 (Se houver)"
        if col_m1 in df.columns and col_m2 in df.columns:
            qtd_top = st.slider("Quantidade de Motivos no Ranking:", 5, 50, 10)
            rank = pd.concat([df[col_m1], df[col_m2]]).value_counts().reset_index()
            rank.columns = ["Motivo", "Total"]
            rank_cut = rank.head(qtd_top)
            total_abs = rank["Total"].sum()
            rank_cut["Label"] = rank_cut["Total"].apply(lambda x: f"{x} ({(x/total_abs*100):.1f}%)")
            h_mot = max(600, qtd_top*50)

            fig_glob = px.bar(rank_cut, x="Total", y="Motivo", orientation='h', text="Label", title=f"Top {qtd_top} Motivos de Contato", height=h_mot)
            fig_glob.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_glob, use_container_width=True)
            
            with st.expander("Ver lista completa"):
                st.dataframe(rank, use_container_width=True)

    with tab_csat:
        if "CSAT Nota" not in df.columns:
             st.warning("Sem dados.")
        else:
            df_csat = df.dropna(subset=["CSAT Nota"])
            if df_csat.empty:
                st.info("Sem avaliações.")
            else:
                k1, k2 = st.columns(2)
                k1.metric("Média Geral CSAT", f"{df_csat['CSAT Nota'].mean():.2f}/5.0")
                k2.metric("Total de Avaliações", len(df_csat))
                
                st.divider()
                
                # --- CONTROLES UNIFICADOS ---
                c_conf1, c_conf2 = st.columns([2, 1])
                with c_conf1:
                    ordem_csat = st.selectbox(
                        "Ordenar Gráfico de Média por:", 
                        ["Melhores Notas Primeiro (Ranking)", "Piores Notas Primeiro (Foco DSat)"], 
                        key="sel_ordem_csat_final" 
                    )
                with c_conf2:
                    qtd_csat = st.slider("Qtd. Motivos:", 5, 50, 10, key="slider_csat_qtd")
                
                eh_dsat = "Piores" in ordem_csat
                
                if "Motivo de Contato" in df.columns:
                    # Agrupa para tirar média e contagem
                    csat_summary = df_csat.groupby("Motivo de Contato")["CSAT Nota"].agg(['mean', 'count']).reset_index()
                    csat_summary.columns = ["Motivo de Contato", "Média", "Qtd"]
                    
                    # --- GRÁFICO 1: MÉDIA ---
                    st.subheader("1. Média de CSAT")
                    
                    # Lógica de Ordenação e Filtro:
                    if eh_dsat:
                        # Queremos ver as PIORES notas (1.0).
                        # Pegamos os top N menores valores.
                        df_chart1 = csat_summary.sort_values("Média", ascending=True).head(qtd_csat)
                        # Ordenamos Descending para que o Plotly desenhe os menores no TOPO.
                        df_chart1 = df_chart1.sort_values("Média", ascending=False)
                    else:
                        # Queremos ver as MELHORES notas (5.0).
                        # Pegamos os top N maiores valores.
                        df_chart1 = csat_summary.sort_values("Média", ascending=False).head(qtd_csat)
                        # Ordenamos Ascending para que o Plotly desenhe os maiores no TOPO.
                        df_chart1 = df_chart1.sort_values("Média", ascending=True)

                    df_chart1["Label"] = df_chart1.apply(lambda x: f"{x['Média']:.2f} ({int(x['Qtd'])} av.)", axis=1)
                    
                    h_c1 = max(400, len(df_chart1) * 50)
                    
                    fig1 = px.bar(
                        df_chart1, 
                        x="Média", 
                        y="Motivo de Contato", 
                        orientation='h', 
                        text="Label", 
                        color="Média", 
                        color_continuous_scale="RdYlGn", 
                        range_color=[1, 5], 
                        height=h_c1,
                        title=f"Média CSAT (Top {qtd_csat})"
                    )
                    fig1.update_layout(coloraxis_showscale=False)
                    st.plotly_chart(fig1, use_container_width=True)
                    
                    st.divider()
                    
                    # --- GRÁFICO 2: VOLUME ---
                    st.subheader("2. Total de Avaliações (Volume)")
                    
                    # Lógica de Ordenação por VOLUME (Sempre Maior para Menor)
                    # Filtramos os Top N mais volumosos.
                    df_chart2 = csat_summary.sort_values("Qtd", ascending=False).head(qtd_csat)
                    # Ordenamos Ascending para que o Plotly desenhe os maiores no TOPO.
                    df_chart2 = df_chart2.sort_values("Qtd", ascending=True)
                    
                    df_chart2["Label"] = df_chart2["Qtd"].astype(int).astype(str)
                    
                    h_c2 = max(400, len(df_chart2) * 50)
                    
                    fig2 = px.bar(
                        df_chart2,
                        x="Qtd",
                        y="Motivo de Contato",
                        orientation='h',
                        text="Label",
                        height=h_c2,
                        title=f"Volume de Avaliações (Top {qtd_csat})"
                    )
                    fig2.update_xaxes(title="Quantidade")
                    st.plotly_chart(fig2, use_container_width=True)

    with tab_tempo:
        st.header("Análise de Tempo")
        col_res = "Tempo Resolução (seg)"
        if col_res in df.columns:
            df_t = df.dropna(subset=[col_res])
            if not df_t.empty:
                st.subheader("⚡ Velocidade por Agente")
                tag = df_t.groupby("Atendente")[col_res].mean().reset_index().sort_values(col_res)
                tag["Label"] = tag[col_res].apply(format_sla_string)
                f_tag = px.bar(tag, x=col_res, y="Atendente", text="Label", orientation='h', title="Média de Tempo (Menor é melhor)", height=max(500, len(tag)*50))
                f_tag.update_xaxes(showticklabels=False)
                st.plotly_chart(f_tag, use_container_width=True)
                
                st.divider()
                
                st.subheader("🐢 Motivos mais demorados (Média de Resolução)")
                qtd_sla = st.slider("Qtd. Motivos:", 5, 50, 10, key="slider_sla")
                
                if "Motivo de Contato" in df.columns:
                    t_motivo = df_t.groupby("Motivo de Contato")[col_res].mean().reset_index()
                    t_motivo = t_motivo.sort_values(col_res, ascending=False).head(qtd_sla)
                    t_motivo = t_motivo.sort_values(col_res, ascending=True)
                    t_motivo["Label"] = t_motivo[col_res].apply(format_sla_string)
                    h_dyn = max(600, len(t_motivo) * 50)
                    
                    fig_tm = px.bar(t_motivo, x=col_res, y="Motivo de Contato", text="Label", orientation='h', height=h_dyn, title=f"Top {qtd_sla} Motivos mais demorados")
                    fig_tm.update_xaxes(showticklabels=False)
                    st.plotly_chart(fig_tm, use_container_width=True)
            else: st.warning("Sem dados de tempo.")

    with tab_tabela:
        c_filter, c_export = st.columns([3, 1])
        
        with c_filter:
            agentes_unicos = sorted(df["Atendente"].astype(str).unique())
            sel_agentes = st.multiselect("Filtrar por Analista:", agentes_unicos, key="sel_agente_final")

        with c_export:
            st.write("") 
            excel = gerar_excel_multias(df, cols_usuario)
            st.download_button("📥 Baixar Excel", data=excel, file_name="relatorio_gerencial.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

        df_view = df.copy()
        if sel_agentes:
            df_view = df_view[df_view["Atendente"].isin(sel_agentes)]
        
        cols_display = ["Data", "Atendente", "Link", "Tempo Resolução"] + cols_usuario
        cols_existentes = [c for c in cols_display if c in df_view.columns]
        
        st.dataframe(
            df_view[cols_existentes], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="🔗 Abrir Conversa")
            }
        )
