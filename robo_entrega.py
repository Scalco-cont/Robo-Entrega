import os
import re
import time
import shutil
import pdfplumber
from datetime import datetime, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv() # Carrega variáveis de ambiente se existir arquivo .env localmente
# --- CONFIGURAÇÕES DE DIRETÓRIOS ---
PASTA_ORIGEM = Path("/sv-scalco/Sistemas/GED/PastaMonitorada")
PASTA_DESTINO = Path("/sv-scalco/Trabalho/Contabilidade/Miguel/Miguel_Certificados/1/CNPJ/TemporarioAutomatico")
PASTA_ENVIADOS = Path("/sv-scalco/Trabalho/Contabilidade/Miguel/Miguel_Certificados/1/CNPJ/TemporarioAutomatico/Enviados")
PASTA_ERRO_ENVIO = Path("/sv-scalco/Trabalho/Contabilidade/Miguel/Miguel_Certificados/1/CNPJ/TemporarioAutomatico")
PASTA_REJEITADOS = Path("/sv-scalco/Trabalho/Contabilidade/Miguel/Miguel_Certificados/1/CNPJ/ArquivosAutomaticos")
PASTA_ICMS = Path("/sv-scalco/Trabalho/Contabilidade/P r o t o c o l o")
LOG_DIR = Path("/sv-scalco/Trabalho/Contabilidade/Miguel/Miguel_Certificados/1/CNPJ/logs")
# LOG_DIR.mkdir(exist_ok=True) # Desativado para evitar o erro de permissao do Linux na rede

# --- PADRÕES ---
PADROES = [
    "refd.contribuicoes",
    "refd.icms.ipi", 
    "recibo dctfweb mensal",
    "recibo dctfweb13",
]

PADROES_ICMS = [
    "icms normal cod 1112 ref", 
    "icms funded cod 5606 ref", 
    "icms funtur cod 9810 ref",
    "icms fundes cod 9816 ref", 
    "icms st cte cod 3818 ref", 
    "icms fecep st cod 9895 ref",
    "icms difal cod 1317 ref",
    "icms st cod 2817 ref"    
]

# --- CONTADORES GLOBAIS ---
total_validos = 0
total_rejeitados = 0
total_icms = 0  # Novo contador para ICMS

# --- FUNÇÕES DE LOG ---
def walle_log(msg, tipo="INFO"):
    emoji = {"INFO": "🤖", "WARN": "⚠️", "ERROR": "❌", "SUCCESS": "✅"}.get(tipo, "🤖")
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"[{hora}] {emoji} {msg}")

def get_log_file_path():
    """Retorna o caminho do arquivo de log para a data atual, garantindo que o log seja diário."""
    return LOG_DIR / f"Log_{datetime.now().strftime('%d_%m_%Y')}.txt"

def log_to_file(tipo, mensagem):
    """Registra uma mensagem no arquivo de log do dia corrente."""
    log_file = get_log_file_path()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{tipo.upper()}] {mensagem}\n")
    except Exception as e:
        walle_log(f"Falha crítica ao escrever no arquivo de log {log_file}: {e}", "ERROR")

# --- FUNÇÕES PRINCIPAIS DO ROBÔ ---

def iniciar_navegador():
    walle_log("Iniciando navegador em modo Headless...", "INFO")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    try:
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        walle_log(f"Falha ao iniciar o Chrome: {e}", "ERROR")
        log_to_file("ERRO CRÍTICO", f"Falha ao iniciar o Chrome: {e}")
        return None

def login_tareffa(driver):
    walle_log("Iniciando processo de login no Tareffa...", "INFO")
    url_login = "https://web.tareffa.com.br/servicos_programados"
    
    usuario = os.getenv("TAREFFA_USER")
    senha = os.getenv("TAREFFA_PASS")
    
    if not usuario or not senha:
        walle_log("Variáveis TAREFFA_USER ou TAREFFA_PASS não configuradas!", "ERROR")
        log_to_file("ERRO", "Credenciais ausentes no .env ou no Coolify.")
        return False
        
    try:
        driver.get(url_login)
        time.sleep(5) # Aguarda o carregamento inicial da página
        
        # --- PREENCHA OS XPATHs CORRETOS AQUI ---
        # Exemplos genéricos usando XPath para campos de formulário padrão
        input_usuario = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='email' or contains(@name, 'email') or contains(@id, 'email')]"))
        )
        input_senha = driver.find_element(By.XPATH, "//input[@type='password']")
        
        input_usuario.send_keys(usuario)
        input_senha.send_keys(senha)
        
        botao_entrar = driver.find_element(By.XPATH, "//button[@type='submit' or contains(text(), 'Entrar') or contains(text(), 'Acessar') or .//span[contains(text(), 'Entrar')]]")
        botao_entrar.click()
        
        walle_log("Aguardando o primeiro carregamento...", "INFO")
        time.sleep(7) 
        
        # Selecionar a conta na tela do OAuth
        try:
            walle_log("Procurando tela de seleção de usuário (OAuth)...", "INFO")
            botao_oauth = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "form.oauthuser button[type='submit']"))
            )
            botao_oauth.click()
            walle_log("Conta selecionada com sucesso no OAuth!", "SUCCESS")
            time.sleep(5) # Aguarda o redirecionamento final
        except TimeoutException:
            walle_log("Nenhuma tela de seleção de conta apareceu, seguindo fluxo normal.", "INFO")
        
        if "login" in driver.current_url.lower():
            walle_log("Login parece ter falhado. A URL ainda está na tela de login.", "ERROR")
            log_to_file("ERRO", "Falha de login no Tareffa. Verifique credenciais ou os seletores do XPath.")
            return False
            
        walle_log("Login no Tareffa realizado com sucesso!", "SUCCESS")
        return True
        
    except Exception as e:
        walle_log(f"Erro durante o login no Tareffa: {e}", "ERROR")
        log_to_file("ERRO", f"Exception no login: {e}")
        return False



def renomear_recibo():
    padrao_recibo = re.compile(r"^Recibo_.*_.*_.*_00000500.*\.pdf$")
    if not PASTA_ORIGEM.exists():
        walle_log(f"Pasta de origem não encontrada: {PASTA_ORIGEM}", "ERROR")
        return

    for caminho in PASTA_ORIGEM.glob("*.pdf"):
        if caminho.is_file() and padrao_recibo.match(caminho.name):
            try:
                with pdfplumber.open(caminho) as pdf:
                    texto_pdf = pdf.pages[0].extract_text() or ""
                
                match_mensal = re.search(r'Período de apuração(\d{2}/\d{4})', texto_pdf)
                match_13 = re.search(r'Período de apuração(\d{4})', texto_pdf)
                
                novo_nome = None
                sufixo = caminho.name[len("Recibo_"):]
                if match_mensal:
                    novo_nome = f"RECIBO DCTFWEB MENSAL_{sufixo}"
                elif match_13:
                    novo_nome = f"RECIBO DCTFWEB13_{sufixo}"
                
                if novo_nome:
                    caminho.rename(PASTA_ORIGEM / novo_nome)
                    walle_log(f"Arquivo renomeado para: {novo_nome}")

            except Exception as e:
                walle_log(f"Erro ao processar o arquivo {caminho.name}: {e}", "ERROR")
                log_to_file("ERRO", f"Falha ao renomear {caminho.name}: {e}")

def buscar_arquivos():
    '''Busca arquivos na origem, separa válidos de rejeitados e move-os.'''
    global total_validos, total_rejeitados, total_icms
    arquivos_validos, rejeitados, icms = [], [], []
    # As pastas abaixo devem ser criadas manualmente no Windows para evitar bloqueio do Linux
    # PASTA_DESTINO.mkdir(exist_ok=True)
    # PASTA_REJEITADOS.mkdir(exist_ok=True)
    # PASTA_ERRO_ENVIO.mkdir(exist_ok=True)
    # PASTA_ICMS.mkdir(parents=True, exist_ok=True)

    if not PASTA_ORIGEM.exists():
        msg = f"Pasta de origem não encontrada: {PASTA_ORIGEM}"
        walle_log(msg, "ERROR")
        log_to_file("ERRO", msg)
        return []
    
    for arq in PASTA_ORIGEM.iterdir():
        if arq.is_file() and arq.suffix.lower() in [".pdf", ".xml"]:
            nome_lower = arq.name.lower()
            
            # Verifica primeiro se é ICMS (prioridade)
            if any(p in nome_lower for p in PADROES_ICMS):
                shutil.move(str(arq), PASTA_ICMS / arq.name)
                icms.append(arq.name)
                log_to_file("ICMS", f"Arquivo ICMS movido para protocolo: {arq.name}")
            # Verifica se é válido para envio
            elif any(p in nome_lower for p in PADROES):
                shutil.move(str(arq), PASTA_DESTINO / arq.name)
                arquivos_validos.append(PASTA_DESTINO / arq.name)
            # Senão, é rejeitado
            else:
                shutil.move(str(arq), PASTA_REJEITADOS / arq.name)
                rejeitados.append(arq.name)
                log_to_file("REJEITADO", f"Arquivo movido para rejeitados: {arq.name}")

    num_validos_ciclo = len(arquivos_validos)
    num_rejeitados_ciclo = len(rejeitados)
    num_icms_ciclo = len(icms)
    
    total_validos += num_validos_ciclo
    total_rejeitados += num_rejeitados_ciclo
    total_icms += num_icms_ciclo
    
    walle_log(f"Ciclo atual - Válidos: {num_validos_ciclo} | ICMS: {num_icms_ciclo} | Rejeitados: {num_rejeitados_ciclo}")
    walle_log(f"Totais acumulados - Válidos: {total_validos} | ICMS: {total_icms} | Rejeitados: {total_rejeitados}")
        
    return arquivos_validos

def enviar_arquivos(driver, arquivos_para_enviar):
    '''Usa o Chrome Headless já logado e envia os arquivos. Retorna True em sucesso, False em falha.'''
    if not arquivos_para_enviar:
        walle_log("Nenhum arquivo para enviar neste ciclo.", "WARN")
        return True

    nomes_dos_arquivos = [p.name for p in arquivos_para_enviar]
    caminhos_formatados = '\n'.join([str(p) for p in arquivos_para_enviar])
    walle_log(f"Iniciando upload de {len(arquivos_para_enviar)} arquivos...")
    
    try:
        if "tareffa.com.br" not in driver.current_url:
            walle_log("A janela ativa do Chrome não está no Tareffa. O login pode ter caído.", "ERROR")
            log_to_file("ERRO", "Tentativa de upload falhou: a aba ativa não era do Tareffa.")
            return False

        walle_log("Abrindo a janela de upload...")
        upload_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[mattooltip='Carregar arquivos para baixa de serviços']"))
        )
        upload_button.click()
        time.sleep(3)
        
        walle_log("Enviando caminhos dos arquivos...")
        input_file = driver.find_element(By.XPATH, "//input[@type='file']")
        input_file.send_keys(caminhos_formatados)
        time.sleep(2)
        
        walle_log("Clicando no botão 'Enviar'...")
        driver.find_element(By.XPATH, "//button[.//span[contains(text(),'Enviar')]]").click()
        time.sleep(17)

        try:
            walle_log("Clicando no botão 'Fechar' do diálogo de upload...")
            botao_fechar = driver.find_element(By.XPATH, "//button[.//span[normalize-space()='Fechar']]")
            botao_fechar.click()
            walle_log("Diálogo de upload fechado.", "SUCCESS")
            time.sleep(2)
            
        except NoSuchElementException:
            walle_log("Botão 'Fechar' não encontrado. O diálogo pode ter fechado automaticamente.", "WARN")

        walle_log("Upload concluído!", "SUCCESS")
        log_to_file("SUCESSO", f"Lote de {len(nomes_dos_arquivos)} arquivos enviado com sucesso.")
        return True

    except NoSuchElementException as e:
        msg = f"Falha no upload: um elemento da página não foi encontrado. Verifique se a página do Tareffa está correta. Erro: {str(e).splitlines()[0]}"
        walle_log(msg, "ERROR")
        log_to_file("ERRO", f"{msg} Arquivos: {', '.join(nomes_dos_arquivos)}")
        return False
    except WebDriverException as e:
        msg = f"Não foi possível conectar ao Chrome. Verifique se ele está rodando em modo de depuração na porta 9222. Erro: {str(e).splitlines()[0]}"
        walle_log(msg, "ERROR")
        log_to_file("ERRO CRÍTICO", msg)
        return False
    except Exception as e:
        msg = f"Ocorreu um erro inesperado durante o envio. Erro: {e}"
        walle_log(msg, "ERROR")
        log_to_file("ERRO CRÍTICO", f"{msg} Arquivos: {', '.join(nomes_dos_arquivos)}")
        if driver:
            try:
                driver.save_screenshot(LOG_DIR / f"erro_inesperado_{datetime.now().strftime('%H%M%S')}.png")
            except Exception as screen_e:
                walle_log(f"Não foi possível salvar o screenshot do erro: {screen_e}", "WARN")
        return False
    finally:
        walle_log("Processo de upload desta rodada finalizado.")

def mover_arquivos_pos_envio(nomes_arquivos, sucesso):
    pasta_alvo = PASTA_ENVIADOS if sucesso else PASTA_ERRO_ENVIO
    log_tipo = "ENVIADO" if sucesso else "ERRO_MOVIMENTACAO"
    # pasta_alvo.mkdir(exist_ok=True)

    for nome_arquivo in nomes_arquivos:
        arquivo_origem = PASTA_DESTINO / nome_arquivo
        if arquivo_origem.exists():
            try:
                shutil.move(str(arquivo_origem), pasta_alvo / nome_arquivo)
                if sucesso:
                    log_to_file(log_tipo, f"Arquivo arquivado com sucesso: {nome_arquivo}")
                else:
                    walle_log(f"Arquivo {nome_arquivo} movido para a pasta de erro para análise.", "WARN")
                    log_to_file(log_tipo, f"Arquivo movido para {pasta_alvo} devido a falha no envio: {nome_arquivo}")
            except Exception as e:
                msg = f"Falha ao mover {nome_arquivo} para {pasta_alvo}. Erro: {e}"
                walle_log(msg, "ERROR")
                log_to_file("ERRO CRÍTICO", msg)

def main():
    ciclo = 1
    log_to_file("INFO", "Serviço Walle iniciado no formato Docker/Headless.")
    
    driver = iniciar_navegador()
    if not driver:
        walle_log("Encerrando porque o navegador falhou ao iniciar.", "ERROR")
        return
        
    sucesso_login = login_tareffa(driver)
    if not sucesso_login:
        walle_log("Encerrando porque o login falhou.", "ERROR")
        driver.quit()
        return

    last_refresh_time = datetime.now()
    
    while True:
        try:
            # --- Verificação para Refresh da Sessão ---
            if datetime.now() - last_refresh_time > timedelta(minutes=10):
                walle_log("Tempo de sessão expirado. Dando refresh na página para manter a sessão ativa.", "WARN")
                driver.refresh()
                time.sleep(5)
                last_refresh_time = datetime.now()

            print(f"\n========== CICLO #{ciclo} (Início: {datetime.now().strftime('%H:%M:%S')}) ==========")
            
            renomear_recibo()
            arquivos_para_enviar = buscar_arquivos()
            
            if arquivos_para_enviar:
                nomes_dos_arquivos = [p.name for p in arquivos_para_enviar]
                sucesso_envio = enviar_arquivos(driver, arquivos_para_enviar)
                mover_arquivos_pos_envio(nomes_dos_arquivos, sucesso_envio)
            
            walle_log(f"Ciclo #{ciclo} concluído.", "SUCCESS")
            ciclo += 1
            
            walle_log("Aguardando 50s para a próxima varredura...", "INFO")
            time.sleep(50)
            
        except KeyboardInterrupt:
            walle_log("Sistema interrompido pelo usuário.")
            log_to_file("INFO", "Serviço Walle interrompido pelo usuário.")
            break
        except Exception as e:
            msg = f"Erro crítico no ciclo #{ciclo}: {e}"
            walle_log(msg, "ERROR")
            log_to_file("ERRO CRÍTICO", msg)
            time.sleep(10)

if __name__ == "__main__":    
    main()