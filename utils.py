import streamlit as st # O arquiteto. Eu preciso dele pra acessar os 'secrets' (o cofre de senhas).
import requests # O motoboy. É ele que leva e traz as mensagens pra API.
import time # O relógio. Essencial pra gente saber quanto tempo esperar quando a API cansa.
import pymongo

def check_password():
    """Gerencia autenticação simples via secrets."""
    if "APP_PASSWORD" not in st.secrets: # Primeiro, eu verifico se eu mesma não esqueci de criar a senha no cofre (.streamlit/secrets.toml).
        st.error("ERRO: Configure 'APP_PASSWORD' no arquivo .streamlit/secrets.toml")
        return False # Se não tem senha configurada, ninguém entra.

    def password_entered(): # Essa é uma "função dentro da função". Ela só roda quando a pessoa aperta Enter.
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]: # Eu comparo o que a pessoa digitou (st.session_state["password"]) com a senha real (st.secrets).
            st.session_state["password_correct"] = True # Aprovada!
            del st.session_state["password"] # Apago a senha da memória por segurança. Ninguém precisa ver.
        else:
            st.session_state["password_correct"] = False # Reprovada!

    if st.session_state.get("password_correct", False): # Se a pessoa JÁ logou antes (está na memória como True), eu deixo passar direto.
        return True
# Se não logou ainda, mostro a caixinha pra digitar.
    st.text_input(
        "🔒 Digite a senha de acesso:", 
        type="password",  # Isso transforma as letras em bolinhas ••••
        on_change=password_entered,  # Quando der Enter, roda a função lá de cima.
        key="password" # Guardo o que foi digitado nessa variável.
    )
    # Se ela tentou entrar e errou (password_correct é False), eu aviso.
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 Senha incorreta.")
# Enquanto não acertar, a porta continua fechada (False).
    return False

# O Motoboy Inteligente (make_api_request)
#Essa é a função mais importante! Ela protege a gente de ser banida pelo Intercom.
def make_api_request(method, url, json=None, params=None, max_retries=3):
    """
    Faz chamadas API seguras respeitando o Rate Limit do Intercom.
    Usa o header 'X-RateLimit-Reset' para espera inteligente.
    Se o Intercom disser "PARE" (Erro 429), eu espero o tempo certo em vez de insistir.
    """
    token = st.secrets.get("INTERCOM_TOKEN", "") # Pego o meu crachá (Token) lá no cofre. Se não tiver, uso vazio "".
    headers = { # Coloco o uniforme oficial pra API me respeitar
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
# Eu tento 3 vezes (max_retries). Se a internet piscar, eu tento de novo.
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST": # Se for pra enviar dados (POST)..
                response = requests.post(url, json=json, params=params, headers=headers)
            else: # Se for só pra ler dados (GET)..
                response = requests.get(url, params=params, headers=headers)
            
            if response.status_code == 200: # Se deu tudo certo (Código 200), eu devolvo o presente (os dados em JSON).
                return response.json()
            # 🛑 AQUI É O PULO DO GATO! Se deu Erro 429 (Rate Limit)...
            elif response.status_code == 429: # Rate Limit
                # Lógica Inteligente baseada na documentação do Intercom
                reset_time = response.headers.get("X-RateLimit-Reset")
                
                if reset_time:
                    try:
                        wait_seconds = int(reset_time) - int(time.time()) + 1 # Calculo: Hora de liberar - Hora de agora + 1 segundinho de margem.
                    except ValueError:
                        wait_seconds = (2 ** attempt) + 1 # Se o cálculo der ruim, espero um pouquinho exponencialmente (2s, 4s, 8s...).
                else:
                    # Se eles não disserem o tempo, eu chuto um tempo seguro.
                    wait_seconds = (2 ** attempt) + 1
                
                # Garanto que nunca vou esperar tempo negativo (o que seria viagem no tempo rs).
                wait_seconds = max(1, wait_seconds)
                # Aviso na tela (Toast) pro usuário não achar que travou. "Tô esperando, calma!"
                st.toast(f"⏳ API cheia. Aguardando {wait_seconds}s para o reset...", icon="🛑")
                time.sleep(wait_seconds) # O código dorme. Zzz...
                continue # Acordou? Tenta de novo (volta pro começo do loop).
            
            else:
                # Se for outro erro bizarro (tipo 500 ou 404), eu anoto no console pra investigar depois.
                print(f"Erro API {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"Erro de Conexão: {e}") # Se a internet cair ou o computador explodir...
            return None
            
    st.error("Falha na conexão com a API após várias tentativas.") # Se eu tentei 3 vezes e falhei em todas... desisto.
    return None
#A Fofoqueira (send_slack_alert)
#Essa função leva as notícias pro Slack.
def send_slack_alert(message):
    """Envia notificação para o Slack se o webhook estiver configurado."""
    # Tento pegar o endereço do Slack no cofre.
    webhook = st.secrets.get("SLACK_WEBHOOK")
    
    if not webhook:
        # Se eu esqueci de colocar o endereço, eu aviso no console e não faço nada.
        print("❌ ERRO: Webhook do Slack não encontrado nos secrets.") 
        return

    payload = {"text": message} # Embrulho a mensagem num pacote que o Slack entende (JSON).
    
    try: # Envio o pacote! 🚀
        requests.post(webhook, json=payload)
    except Exception as e: # Se o Slack estiver fora do ar, eu anoto o erro.
        print(f"Erro ao enviar alerta Slack: {e}")

# Variável global para manter a conexão aberta (cache de conexão)
@st.cache_resource
def init_mongo_connection():
    """Conecta ao MongoDB Atlas usando a URI dos secrets."""
    try:
        uri = st.secrets["MONGO_URI"]
        client = pymongo.MongoClient(uri)
        # Testa a conexão
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"Erro ao conectar no MongoDB: {e}")
        return None

def salvar_lote_tickets_mongo(lista_tickets):
    """Salva/Atualiza uma lista de tickets no MongoDB."""
    client = init_mongo_connection()
    if not client: return 0
    
    db = client["suporte_db"] # Nome do seu banco
    collection = db["tickets"] # Nome da 'tabela'
    
    operacoes = []
    for ticket in lista_tickets:
        # UpdateOne com upsert=True: Se existe, atualiza. Se não, cria.
        # Usamos o 'id' do Intercom como chave única
        op = pymongo.UpdateOne(
            {"id": ticket["id"]}, 
            {"$set": ticket}, 
            upsert=True
        )
        operacoes.append(op)
    
    if operacoes:
        resultado = collection.bulk_write(operacoes)
        return resultado.upserted_count + resultado.modified_count
    return 0

def carregar_tickets_mongo(termo_busca=None):
    """
    Traz tickets. Se termo_busca for None, traz TODOS (limite de 1000).
    Se tiver termo, busca por ID, ID Interno ou Nome.
    """
    client = init_mongo_connection()
    if not client: return []
    
    db = client["suporte_db"]
    collection = db["tickets"]
    
    filtro = {}
    
    # Só aplica filtro se o usuário digitou algo
    if termo_busca and str(termo_busca).strip() != "":
        termo_str = str(termo_busca).strip()
        regex_busca = {"$regex": termo_str, "$options": "i"}
        
        filtro = {
            "$or": [
                {"id_interno": termo_str},          # ID exato da empresa
                {"cliente": regex_busca},           # Nome da empresa (Energisa...)
                {"autor_nome": regex_busca},        # Nome do usuário
                {"autor_email": regex_busca},       # Email
                {"id": termo_str}                   # ID do Ticket
            ]
        }
    
    # Traz os últimos 1000 tickets para não travar a tela
    cursor = collection.find(filtro, {"_id": 0}).sort("updated_at", -1).limit(1000)
    
    return list(cursor)
