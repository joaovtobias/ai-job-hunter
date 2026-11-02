import os
import sys
import time
import json
import sqlite3
import urllib.parse
from datetime import datetime
import requests
import pandas as pd
from scrapy import Selector
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


def carregar_env():
    """Carrega variáveis de um arquivo .env local, se existir."""
    if os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


carregar_env()

# ==========================================
# 1. CONFIGURAÇÃO DO AGENTE DE IA (GEMINI)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise RuntimeError("A variável GEMINI_API_KEY não foi encontrada. Defina-a no arquivo .env!")
client = genai.Client(api_key=GEMINI_API_KEY)


# Estrutura exata que obrigamos a IA a devolver (Prompt Engineering Avançado)
class VagaAnalisada(BaseModel):
    empresa: str
    titulo_vaga: str
    localidade: str
    modelo_trabalho: str = Field(description="Remoto, Híbrido, Presencial ou Não informado")
    is_tech_or_data: bool = Field(description="True se aceitar TI, Dados, BI, IA ou Qualquer Curso com foco analítico")
    categoria: str = Field(description="Dados/BI, IA/Automação, Desenvolvimento, Negócios/Geral")
    hard_skills: list[str] = Field(description="Lista de skills exigidas ou inferidas, ex: SQL, Python, Excel, IA")
    match_score: int = Field(description="Nota de 0 a 100 de compatibilidade com estudante que domina SQL, Python e Pandas")
    justificativa_ia: str = Field(description="Explicação direta de 1 frase do porquê vale a pena ou não se inscrever")
    dias_restantes: str
    origem_ou_link: str


class ListaVagasAnalisadas(BaseModel):
    vagas: list[VagaAnalisada]


# ==========================================
# FUNÇÕES DE INTEGRAÇÃO COM WHATSAPP (CALLMEBOT)
# ==========================================
def inicializar_tabela_notificacoes(conn: sqlite3.Connection):
    """Cria tabela para controlar quais vagas já foram enviadas no WhatsApp (evita spam)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vagas_notificadas (
            chave_vaga TEXT PRIMARY KEY,
            empresa TEXT,
            titulo_vaga TEXT,
            match_score INTEGER,
            data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def filtrar_vagas_nao_enviadas(conn: sqlite3.Connection, df: pd.DataFrame, score_minimo: int = 60) -> pd.DataFrame:
    """Retorna apenas vagas compatíveis com TI/Dados, acima do score mínimo e ainda não enviadas no WhatsApp."""
    if df.empty:
        return df

    inicializar_tabela_notificacoes(conn)
    ja_enviadas = {
        row[0]
        for row in conn.execute("SELECT chave_vaga FROM vagas_notificadas").fetchall()
    }

    df_aprovadas = df[(df["is_tech_or_data"] == True) & (df["match_score"] >= score_minimo)].copy()
    if df_aprovadas.empty:
        return df_aprovadas

    df_aprovadas["chave_vaga"] = (
        df_aprovadas["empresa"].astype(str).str.strip().str.lower()
        + "::"
        + df_aprovadas["titulo_vaga"].astype(str).str.strip().str.lower()
    )
    df_novas = df_aprovadas[~df_aprovadas["chave_vaga"].isin(ja_enviadas)].sort_values(
        by="match_score", ascending=False
    )
    return df_novas


def formatar_mensagem_whatsapp(df_vagas: pd.DataFrame, max_vagas: int = 5) -> str:
    """Formata um resumo das melhores vagas para envio no WhatsApp."""
    total_novas = len(df_vagas)
    top_vagas = df_vagas.head(max_vagas)

    linhas = [
        f"🤖 *AI Job Hunter — {total_novas} Nova(s) Vaga(s) Compatível(is)!*",
        f"📅 _{datetime.now().strftime('%d/%m/%Y %H:%M')}_",
        "",
    ]

    for idx, (_, row) in enumerate(top_vagas.iterrows(), start=1):
        linhas.append(
            f"*{idx}. {row['empresa']}* — {row['titulo_vaga']}\n"
            f"🎯 *Match:* {row['match_score']}% | 📂 {row['categoria']}\n"
            f"🛠️ *Skills:* {row['hard_skills']}\n"
            f"💡 _{row['justificativa_ia']}_\n"
            f"⏳ *Prazo:* {row['dias_restantes']}\n"
            f"🔗 {row['origem_ou_link']}\n"
        )

    if total_novas > max_vagas:
        linhas.append(f"➕ _E mais {total_novas - max_vagas} vaga(s) salva(s) no seu dashboard!_")

    return "\n".join(linhas).strip()


def enviar_whatsapp_green_api(mensagem: str, phone: str, instance_id: str, api_token: str) -> bool:
    """Envia mensagem no WhatsApp via Green-API (Plano Developer Gratuito)."""
    url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{api_token}"
    payload = {
        "chatId": f"{phone}@c.us",
        "message": mensagem,
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200 and "idMessage" in resp.text:
            print(f"📲 [WhatsApp - Green-API] Mensagem enviada com sucesso para +{phone}!")
            return True
        print(f"⚠️ [Green-API] Resposta inesperada (HTTP {resp.status_code}): {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"⚠️ [Green-API] Erro ao enviar mensagem: {e}")
        return False


def enviar_whatsapp_twilio(
    mensagem: str, phone: str, account_sid: str, auth_token: str, twilio_from: str = "14155238886"
) -> bool:
    """Envia mensagem no WhatsApp via Twilio WhatsApp Sandbox (Gratuito)."""
    twilio_from = twilio_from.strip().replace("whatsapp:", "").replace("+", "").replace(" ", "")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {
        "From": f"whatsapp:+{twilio_from}",
        "To": f"whatsapp:+{phone}",
        "Body": mensagem,
    }
    try:
        resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=20)
        if resp.status_code in (200, 201):
            print(f"📲 [WhatsApp - Twilio] Mensagem enviada com sucesso para +{phone}!")
            return True
        print(f"⚠️ [Twilio] Resposta inesperada (HTTP {resp.status_code}): {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"⚠️ [Twilio] Erro ao enviar mensagem: {e}")
        return False


def enviar_whatsapp(
    mensagem: str,
    phone: str = "",
    provider: str = "",
    green_instance_id: str = "",
    green_api_token: str = "",
    twilio_sid: str = "",
    twilio_token: str = "",
    twilio_from: str = "",
    callmebot_key: str = "",
) -> bool:
    """
    Envia mensagem para o WhatsApp detectando automaticamente o provedor configurado no .env:
    1. Green-API (GREEN_API_INSTANCE_ID + GREEN_API_TOKEN)
    2. Twilio Sandbox (TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN)
    3. CallMeBot (CALLMEBOT_API_KEY)
    """
    carregar_env()
    phone = (phone or os.environ.get("WHATSAPP_PHONE", "")).strip().replace("+", "").replace(" ", "").replace("-", "")

    green_id = (green_instance_id or os.environ.get("GREEN_API_INSTANCE_ID", "")).strip()
    green_token = (green_api_token or os.environ.get("GREEN_API_TOKEN", "")).strip()

    tw_sid = (twilio_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")).strip()
    tw_token = (twilio_token or os.environ.get("TWILIO_AUTH_TOKEN", "")).strip()
    tw_from = (twilio_from or os.environ.get("TWILIO_WHATSAPP_FROM", "14155238886")).strip()

    cmb_key = (callmebot_key or os.environ.get("CALLMEBOT_API_KEY", "")).strip()

    phone_valido = bool(phone and phone != "5511999999999")

    # 1. Tenta Green-API se configurado
    if phone_valido and green_id and green_token and green_id != "SEU_INSTANCE_ID" and (provider in ("", "green_api")):
        return enviar_whatsapp_green_api(mensagem, phone, green_id, green_token)

    # 2. Tenta Twilio se configurado
    if phone_valido and tw_sid and tw_token and tw_sid != "SEU_ACCOUNT_SID" and (provider in ("", "twilio")):
        return enviar_whatsapp_twilio(mensagem, phone, tw_sid, tw_token, tw_from)

    # 3. Tenta CallMeBot se configurado
    if phone_valido and cmb_key and cmb_key != "SUA_API_KEY_CALLMEBOT" and (provider in ("", "callmebot")):
        texto_codificado = urllib.parse.quote(mensagem)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={texto_codificado}&apikey={cmb_key}"
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200 and ("queued" in resp.text.lower() or "sent" in resp.text.lower()):
                print(f"📲 [WhatsApp - CallMeBot] Mensagem enviada com sucesso para +{phone}!")
                return True
            print(f"⚠️ [CallMeBot] Resposta inesperada (HTTP {resp.status_code}): {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"⚠️ [CallMeBot] Erro ao conectar: {e}")
            return False

    print("\n⚠️ [WhatsApp] Nenhuma API de WhatsApp configurada ainda no arquivo .env.")
    print("👉 Configure no arquivo .env a Opção A (Green-API) ou Opção B (Twilio Sandbox).")
    print("\n📱 Prévia da mensagem que será enviada ao seu WhatsApp:\n" + "-" * 50)
    print(mensagem)
    print("-" * 50)
    return False


# Mantém alias para compatibilidade
enviar_whatsapp_callmebot = enviar_whatsapp


def registrar_vagas_notificadas(conn: sqlite3.Connection, df_enviadas: pd.DataFrame):
    """Registra no SQLite as vagas que já foram notificadas no WhatsApp."""
    inicializar_tabela_notificacoes(conn)
    for _, row in df_enviadas.iterrows():
        chave = (
            f"{str(row['empresa']).strip().lower()}::{str(row['titulo_vaga']).strip().lower()}"
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO vagas_notificadas (chave_vaga, empresa, titulo_vaga, match_score)
            VALUES (?, ?, ?, ?)
            """,
            (chave, str(row["empresa"]), str(row["titulo_vaga"]), int(row["match_score"])),
        )
    conn.commit()


# ==========================================
# PIPELINE COMPLETA (SCRAPER + IA + SQL + WHATSAPP)
# ==========================================
def executar_pipeline(notificar_whatsapp: bool = True) -> pd.DataFrame:
    carregar_env()
    score_minimo_wpp = int(os.environ.get("SCORE_MINIMO_WHATSAPP", "60"))

    # ------------------------------------------
    # 2. SCRAPER (CIA DE TALENTOS + CIA DE ESTÁGIOS)
    # ------------------------------------------
    print("🔍 [1/5] Coletando vagas na API da Cia de Talentos...")
    headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7',
        'content-type': 'application/json',
        'origin': 'https://www.ciadetalentos.com.br',
        'referer': 'https://www.ciadetalentos.com.br/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
    }

    vagas_brutas = []

    try:
        resp_ct = requests.post(
            'https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter',
            headers=headers,
            json={'locale': 'pt'},
            timeout=15
        )
        dados_ct = resp_ct.json()

        # Pegamos as primeiras 20 vagas para o MVP rodar super rápido
        for vaga in dados_ct[:20]:
            vagas_brutas.append({
                "titulo": vaga.get('opportunityName', ''),
                "empresa": vaga.get('companyName', ''),
                "local": str(vaga.get('opportunityLocations', '')),
                "area": str(vaga.get('opportunityAreas', '')).replace('Área', 'Area'),
                "prazo": f"{vaga.get('daysRemainingForInscription', '?')} dias",
                "link": "https://www.ciadetalentos.com.br/"
            })
        print(f"✅ {len(vagas_brutas)} vagas coletadas da Cia de Talentos!")
    except Exception as e:
        print(f"⚠️ Erro na Cia de Talentos: {e}")

    print("🔍 [2/5] Coletando vagas da Cia de Estágios e convertendo para Markdown...")
    try:
        url_ce = 'https://www.ciadeestagios.com.br/vagas-de-estagio/#vagas'
        html_ce = requests.get(url_ce, headers={'user-agent': headers['user-agent']}, timeout=15).text
        sel = Selector(text=html_ce)
        links = sel.css('a.button.button--green.button--md.button--full-width::attr(href)').getall()

        # Pegamos até 5 links e usamos r.jina.ai para extrair o resumo
        for link in links[:5]:
            link_completo = link if link.startswith('http') else f"https://www.ciadeestagios.com.br{link}"
            try:
                md_vaga = requests.get(f"https://r.jina.ai/{link_completo}", timeout=10).text[:1200]
            except Exception:
                md_vaga = f"Vaga disponível no link: {link_completo}"

            vagas_brutas.append({
                "titulo": "Programa de Estágio (Ver Detalhes)",
                "empresa": "Via Cia de Estágios",
                "local": "Brasil",
                "area": md_vaga,
                "prazo": "Aberto",
                "link": link_completo
            })
        print(f"✅ Links da Cia de Estágios adicionados! Total bruto: {len(vagas_brutas)} vagas.")
    except Exception as e:
        print(f"⚠️ Erro na Cia de Estágios: {e}")

    # ------------------------------------------
    # 3. ORQUESTRAÇÃO DO AGENTE DE TRIAGEM (LLM)
    # ------------------------------------------
    print("🤖 [3/5] Acionando Agente de IA (Gemini) para filtrar TI/Dados e calcular Match Score...")

    prompt_agente = f"""
Você é um Agente Especialista em Recrutamento Técnico e Triagem de Dados (AI Job Hunter).
Analise a lista de vagas brutas abaixo e avalie cada uma para o seguinte perfil de candidato:
- Perfil: Estudante universitário focado em Análise de Dados, BI e IA.
- Hard Skills atuais: SQL, Python, Pandas, Web Scraping, Automação com IA e lógica de programação.
- Objetivo: Vagas de Estágio em Dados, BI, IA, Tecnologia ou Programas de Estágio Gerais (que aceitem qualquer curso e tenham trilhas de negócios/dados/inovação).

Regras:
1. Marque `is_tech_or_data = True` se a vaga tiver áreas de Tecnologia, Dados, Engenharias, Negócios/Geral ou múltiplos cursos. Marque `False` apenas se for estritamente de outra área incompatível (ex: exclusivo Direito ou Medicina).
2. Infira as `hard_skills` prováveis exigidas pela vaga (ex: ["Excel", "SQL", "Python", "Power BI", "IA", "Análise de Dados"]).
3. Calcule um `match_score` realista (0 a 100) baseado no quanto um perfil com SQL + Pandas + IA se destacaria nessa vaga.

VAGAS BRUTAS (JSON):
{json.dumps(vagas_brutas, ensure_ascii=False)}
"""

    modelos_candidatos = ['gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.8-flash']
    response_ia = None

    for modelo in modelos_candidatos:
        try:
            print(f"Tentando gerar com o modelo: {modelo}...")
            response_ia = client.models.generate_content(
                model=modelo,
                contents=prompt_agente,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ListaVagasAnalisadas,
                    temperature=0.2,
                ),
            )
            print(f"✅ Sucesso com {modelo}!")
            break
        except Exception as e:
            print(f"⚠️ Erro ao tentar {modelo}: {e}")

    if response_ia is None:
        raise RuntimeError("Nenhum modelo do Gemini respondeu com sucesso.")

    resultado_estruturado = json.loads(response_ia.text)
    lista_vagas_processadas = resultado_estruturado.get("vagas", [])

    # ------------------------------------------
    # 4. ESTRUTURAÇÃO COM PANDAS E BANCO SQLITE
    # ------------------------------------------
    print("💾 [4/5] Estruturando com Pandas e salvando no banco relacional SQLite...")

    df = pd.DataFrame(lista_vagas_processadas)

    if not df.empty:
        df['hard_skills'] = df['hard_skills'].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else str(x)
        )

    conn = sqlite3.connect('vagas_ia.db')
    df.to_sql('vagas_analisadas', conn, if_exists='replace', index=False)

    df.to_csv('vagas_analisadas.csv', index=False, encoding='utf-8-sig')
    print("🚀 SUCESSO! Banco 'vagas_ia.db' e 'vagas_analisadas.csv' gerados!")
    if not df.empty:
        print(df[['empresa', 'titulo_vaga', 'is_tech_or_data', 'match_score']].head(10))

    # ------------------------------------------
    # 5. ENVIO DE NOVAS VAGAS NO WHATSAPP
    # ------------------------------------------
    if notificar_whatsapp and not df.empty:
        print(f"📲 [5/5] Verificando novas vagas com Match >= {score_minimo_wpp}% para enviar no WhatsApp...")
        df_novas = filtrar_vagas_nao_enviadas(conn, df, score_minimo=score_minimo_wpp)

        if df_novas.empty:
            print("✅ Nenhuma vaga inédita acima do score mínimo neste ciclo (evitando mensagens repetidas).")
        else:
            mensagem_wpp = formatar_mensagem_whatsapp(df_novas, max_vagas=5)
            enviado = enviar_whatsapp_callmebot(mensagem_wpp)
            if enviado:
                registrar_vagas_notificadas(conn, df_novas)

    conn.close()
    return df


if __name__ == "__main__":
    if "--loop" in sys.argv:
        intervalo_horas = float(os.environ.get("INTERVALO_HORAS", "4"))
        print(f"🔄 Modo de monitoramento contínuo ativado! Rodando a cada {intervalo_horas} hora(s)...")
        while True:
            try:
                executar_pipeline(notificar_whatsapp=True)
            except Exception as err:
                print(f"⚠️ Erro durante o ciclo da pipeline: {err}")
            print(f"⏳ Próxima varredura em {intervalo_horas} hora(s)... (Pressione Ctrl+C para parar)")
            time.sleep(intervalo_horas * 3600)
    else:
        executar_pipeline(notificar_whatsapp=True)
