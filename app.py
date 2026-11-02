import os
import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
from pipeline_ia import carregar_env, formatar_mensagem_whatsapp, enviar_whatsapp

carregar_env()

st.set_page_config(page_title="AI Job Hunter | Agente de Triagem", page_icon="🤖", layout="wide")

st.title("🤖 AI Job Hunter — Agente Autônomo de Triagem de Vagas")
st.markdown("**Pipeline AI-First:** Coleta Automatizada (API/Web Scraping) ➔ Triagem com LLM (*Structured Outputs*) ➔ Modelagem SQL & Pandas.")

# Conexão com o Banco SQLite
conn = sqlite3.connect('vagas_ia.db')

# Query SQL 1: Visão Geral Filtrada
df_vagas = pd.read_sql_query("""
    SELECT * FROM vagas_analisadas 
    ORDER BY match_score DESC
""", conn)

# Filtros na Barra Lateral
st.sidebar.header("🎯 Filtros do Agente")
apenas_tech = st.sidebar.checkbox("Apenas vagas compatíveis (TI/Dados/Geral)", value=True)
score_minimo = st.sidebar.slider("Match Score Mínimo (%)", 0, 100, 60)

if apenas_tech:
    df_filtrado = df_vagas[(df_vagas['is_tech_or_data'] == 1) & (df_vagas['match_score'] >= score_minimo)]
else:
    df_filtrado = df_vagas[df_vagas['match_score'] >= score_minimo]

st.sidebar.divider()
st.sidebar.header("📲 Alertas no WhatsApp")
provedor_ui = st.sidebar.selectbox(
    "Provedor de API",
    ["Green-API (Gratuito)", "Twilio Sandbox (Gratuito)"],
)
wpp_phone = st.sidebar.text_input(
    "Seu WhatsApp (com DDI 55 + DDD)",
    value=os.environ.get("WHATSAPP_PHONE", "5511999999999"),
)

if "Green-API" in provedor_ui:
    green_id = st.sidebar.text_input(
        "Green-API Instance ID",
        value=os.environ.get("GREEN_API_INSTANCE_ID", ""),
    )
    green_token = st.sidebar.text_input(
        "Green-API Token",
        value=os.environ.get("GREEN_API_TOKEN", ""),
        type="password",
    )
    tw_sid, tw_token = "", ""
    prov_code = "green_api"
else:
    tw_sid = st.sidebar.text_input(
        "Twilio Account SID",
        value=os.environ.get("TWILIO_ACCOUNT_SID", ""),
    )
    tw_token = st.sidebar.text_input(
        "Twilio Auth Token",
        value=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        type="password",
    )
    green_id, green_token = "", ""
    prov_code = "twilio"

if st.sidebar.button("🚀 Enviar Top Vagas no WhatsApp Agora", use_container_width=True):
    if df_filtrado.empty:
        st.sidebar.warning("Nenhuma vaga nos filtros atuais para enviar.")
    else:
        msg = formatar_mensagem_whatsapp(df_filtrado, max_vagas=5)
        sucesso = enviar_whatsapp(
            msg,
            phone=wpp_phone,
            provider=prov_code,
            green_instance_id=green_id,
            green_api_token=green_token,
            twilio_sid=tw_sid,
            twilio_token=tw_token,
        )
        if sucesso:
            st.sidebar.success("✅ Top vagas enviadas para o seu WhatsApp!")
        else:
            st.sidebar.error("⚠️ Verifique seu número e as credenciais da API selecionada.")
            with st.sidebar.expander("Prévia da mensagem gerada"):
                st.text(msg)

# 1. KPIs Principais
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total de Vagas Raspadas", len(df_vagas))
col2.metric("Aprovadas pelo Agente IA", len(df_vagas[df_vagas['is_tech_or_data'] == 1]))
col3.metric("Alto Match (>= 75%)", len(df_vagas[df_vagas['match_score'] >= 75]))
col4.metric("Tempo Economizado Estimado", f"{round(len(df_vagas) * 6 / 60, 1)} horas")

st.divider()

# 2. Gráficos Analíticos (Pandas + Plotly)
col_graf1, col_graf2 = st.columns(2)

with col_graf1:
    st.subheader("📊 Top Hard Skills Demandadas (Análise com Pandas)")
    skills_series = df_filtrado['hard_skills'].str.split(', ').explode().value_counts().reset_index()
    skills_series.columns = ['Skill', 'Frequência']
    fig_skills = px.bar(skills_series.head(10), x='Frequência', y='Skill', orientation='h', color='Frequência', color_continuous_scale='Viridis')
    fig_skills.update_layout(yaxis={'categoryorder':'total ascending'})
    st.plotly_chart(fig_skills, use_container_width=True)

with col_graf2:
    st.subheader("🎯 Distribuição por Categoria (SQL Group By)")
    df_cat = pd.read_sql_query("""
        SELECT categoria, COUNT(*) as total, ROUND(AVG(match_score), 1) as media_score
        FROM vagas_analisadas
        GROUP BY categoria
        ORDER BY total DESC
    """, conn)
    fig_cat = px.pie(df_cat, names='categoria', values='total', hole=0.4)
    st.plotly_chart(fig_cat, use_container_width=True)

conn.close()

# 3. Tabela Interativa com Parecer do Agente
st.subheader("📋 Ranking de Oportunidades Recomendadas pela IA")
st.dataframe(
    df_filtrado[['match_score', 'empresa', 'titulo_vaga', 'categoria', 'hard_skills', 'justificativa_ia', 'dias_restantes', 'origem_ou_link']],
    use_container_width=True,
    hide_index=True
)