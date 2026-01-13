# app.py - Relatório de Fiscalização - Versão Otimizada para Streamlit Cloud
import streamlit as st
import pandas as pd
from fpdf import FPDF
import base64
from io import BytesIO
from PIL import Image
import os
import tempfile
from datetime import datetime as dt  # Altere aqui: renomeie para dt
import json
import re
import time
import uuid

# ========== CONFIGURAÇÃO GOOGLE SHEETS ==========
try:
    import gspread
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError as e:
    GOOGLE_SHEETS_AVAILABLE = False
    st.warning(f"Bibliotecas do Google Sheets não disponíveis: {e}")

# ========== CONFIGURAÇÃO GOOGLE DRIVE ==========
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False
    st.warning("Bibliotecas do Google Drive não disponíveis. Funcionalidade de nuvem limitada.")

# ========== CONFIGURAÇÃO INICIAL ==========
IS_STREAMLIT_CLOUD = os.environ.get("STREAMLIT_CLOUD", False)

# Configuração da página
st.set_page_config(
    page_title="Relatório de Fiscalização CREA-RJ",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://crea-rj.gov.br',
        'Report a bug': None,
        'About': "Sistema de Fiscalização CREA-RJ v1.0"
    }
)

# ========== CONFIGURAÇÃO GOOGLE DRIVE ==========
SCOPES = ['https://www.googleapis.com/auth/drive.file']
GOOGLE_DRIVE_FOLDER_ID = ""

try:
    if hasattr(st, "secrets"):
        if "GOOGLE_DRIVE_FOLDER_ID" in st.secrets:
            GOOGLE_DRIVE_FOLDER_ID = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
        elif "google_drive_folder_id" in st.secrets:
            GOOGLE_DRIVE_FOLDER_ID = st.secrets["google_drive_folder_id"]
        elif "GOOGLE_DRIVE" in st.secrets and "folder_id" in st.secrets["GOOGLE_DRIVE"]:
            GOOGLE_DRIVE_FOLDER_ID = st.secrets["GOOGLE_DRIVE"]["folder_id"]
except Exception:
    GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# ========== NOME DO ARQUIVO EXCEL DE DADOS ==========
EXCEL_DATABASE_NAME = "Planilha_Master.xlsx"

# ========== CACHE PARA PERFORMANCE ==========
@st.cache_data(ttl=3600)
def carregar_municipios_cache():
    """Cache da lista de municípios"""
    return [
        "Angra dos Reis", "Aperibé", "Araruama", "Areal", "Armação dos Búzios",
        "Arraial do Cabo", "Barra do Piraí", "Barra Mansa", "Belford Roxo",
        "Bom Jardim", "Bom Jesus do Itabapoana", "Cabo Frio", "Cachoeiras de Macacu",
        "Cambuci", "Campos dos Goytacazes", "Cantagalo", "Carapebus", "Cardoso Moreira",
        "Carmo", "Casimiro de Abreu", "Comendador Levy Gasparian", "Conceição de Macabu",
        "Cordeiro", "Duas Barras", "Duque de Caxias", "Engenheiro Paulo de Frontin",
        "Guapimirim", "Iguaba Grande", "Itaboraí", "Itaguaí", "Italva", "Itaocara",
        "Itaperuna", "Itatiaia", "Japeri", "Laje do Muriaé", "Macaé", "Macuco",
        "Magé", "Mangaratiba", "Maricá", "Mendes", "Mesquita", "Miguel Pereira",
        "Miracema", "Natividade", "Nilópolis", "Niterói", "Nova Friburgo",
        "Nova Iguaçu", "Paracambi", "Paraíba do Sul", "Paraty", "Paty do Alferes",
        "Petrópolis", "Pinheiral", "Piraí", "Porciúncula", "Porto Real",
        "Quatis", "Queimados", "Quissamã", "Resende", "Rio Bonito", "Rio Claro",
        "Rio das Flores", "Rio das Ostras", "Rio de Janeiro", "Santa Maria Madalena",
        "Santo Antônio de Pádua", "São Fidélis", "São Francisco de Itabapoana",
        "São Gonçalo", "São João da Barra", "São João de Meriti", "São José de Ubá",
        "São José do Vale do Rio Preto", "São Pedro da Aldeia", "São Sebastião do Alto",
        "Sapucaia", "Saquarema", "Seropédica", "Silva Jardim", "Sumidouro",
        "Tanguá", "Teresópolis", "Trajano de Morais", "Três Rios", "Valença",
        "Varre-Sai", "Vassouras", "Volta Redonda"
    ]

MUNICIPIOS_RJ = carregar_municipios_cache()

# ========== FUNÇÃO AUXILIAR: OBTER CREDENCIAIS ÚNICAS ==========
def obter_credenciais_google():
    """Obtém credenciais do Google do secrets (usa as mesmas para Drive e Sheets)"""
    try:
        # Primeiro tenta do google_drive.credentials (que já funciona)
        if 'google_drive' in st.secrets and 'credentials' in st.secrets.google_drive:
            creds_text = st.secrets.google_drive.credentials
            if isinstance(creds_text, str):
                try:
                    return json.loads(creds_text)
                except:
                    # Já pode estar como dict no Streamlit Cloud
                    return creds_text
            return creds_text
        
        # Tenta do google_sheets.credentials (se existir separado)
        if 'google_sheets' in st.secrets and 'credentials' in st.secrets.google_sheets:
            creds_text = st.secrets.google_sheets.credentials
            if isinstance(creds_text, str):
                try:
                    return json.loads(creds_text)
                except:
                    return creds_text
            return creds_text
            
        st.error("❌ Credenciais do Google não encontradas no secrets")
        return None
    except Exception as e:
        st.error(f"❌ Erro ao obter credenciais: {str(e)}")
        return None

# ========== NOVA FUNÇÃO: SALVAR NO GOOGLE SHEETS (CORRIGIDA) ==========
def salvar_relatorio_google_sheets(dados_relatorio, pdf_path=None):
    """
    Salva os dados do relatório no Google Sheets
    Cada relatório é adicionado como uma nova linha
    """
    try:
        if not GOOGLE_SHEETS_AVAILABLE:
            st.warning("Google Sheets não disponível. Os dados não serão salvos na planilha.")
            return False
        
        # ================================================
        # 1. OBTER CREDENCIAIS (usando função única)
        # ================================================
        creds_info = obter_credenciais_google()
        
        if not creds_info:
            st.error("❌ Credenciais do Google não encontradas")
            return False
        
        # ================================================
        # 2. AUTENTICAÇÃO
        # ================================================
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        
        try:
            credentials = ServiceAccountCredentials.from_service_account_info(creds_info, scopes=scope)
            gc = gspread.authorize(credentials)
        except Exception as e:
            st.error(f"❌ Erro na autenticação Google Sheets: {str(e)}")
            return False
        
        # ================================================
        # 3. ABRIR A PLANILHA
        # ================================================
        spreadsheet_id = ""
        
        if 'google_sheets' in st.secrets and 'spreadsheet_id' in st.secrets.google_sheets:
            spreadsheet_id = st.secrets.google_sheets.spreadsheet_id
        
        if not spreadsheet_id:
            st.error("❌ ID da planilha não configurado no secrets")
            return False
        
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
        except gspread.SpreadsheetNotFound:
            st.error(f"❌ Planilha não encontrada. ID: {spreadsheet_id}")
            st.info(f"Compartilhe a planilha com: {creds_info.get('client_email', 'N/A')}")
            return False
        except Exception as e:
            st.error(f"❌ Erro ao abrir planilha: {str(e)}")
            return False
        
        # ================================================
        # 4. SELECIONAR/CRIAR WORKSHEET
        # ================================================
        worksheet_name = st.secrets.google_sheets.get('worksheet_name', 'RELATORIOS')
        
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            # Se não existir, criar uma nova aba
            try:
                worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows="1000", cols="50")
                
                # Adicionar cabeçalhos
                cabecalhos = [
                    "DATA_REGISTRO", "Nº RELATÓRIO", "MATRÍCULA AGENTE", "NOME AGENTE", 
                    "UNIDADE", "SITUAÇÃO", "DATA RELATÓRIO", "FATO GERADOR", "PROTOCOLO",
                    "TIPO AÇÃO", "LATITUDE", "LONGITUDE", "ENDEREÇO", "NÚMERO", 
                    "COMPLEMENTO", "MUNICÍPIO", "UF", "CEP", "NOME CONTRATANTE",
                    "REGISTRO CONTRATANTE", "CPF/CNPJ", "CONSTATAÇÃO", "MOTIVO AÇÃO",
                    "CARACTERÍSTICA", "FASE ATIVIDADE", "Nº PAVIMENTOS", "QUANTIFICAÇÃO",
                    "UNIDADE MEDIDA", "NATUREZA", "TIPO CONSTRUÇÃO", "Nº CONTRATADOS",
                    "DOCUMENTOS SOLICITADOS", "DOCUMENTOS RECEBIDOS", "Nº FOTOS",
                    "PDF_PATH", "DRIVE_LINK", "TIMESTAMP"
                ]
                
                worksheet.append_row(cabecalhos)
            except Exception as e:
                st.error(f"❌ Erro ao criar worksheet: {str(e)}")
                return False
        except Exception as e:
            st.error(f"❌ Erro ao acessar worksheet: {str(e)}")
            return False
        
        # ================================================
        # 5. PREPARAR OS DADOS PARA A LINHA
        # ================================================
        dados_linha = []
        
        # Data de registro (agora)
        dados_linha.append(dt.now().strftime("%d/%m/%Y %H:%M:%S"))
        
        # Número do relatório
        dados_linha.append(dados_relatorio.get('numero_relatorio', ''))
        
        # Dados do agente
        agente_info = st.session_state.get('agente_info', {})
        dados_linha.append(agente_info.get('MATRICULA', ''))
        dados_linha.append(agente_info.get('NOME', ''))
        dados_linha.append(agente_info.get('UNIDADE', ''))
        
        # Dados gerais do relatório
        dados_linha.append(dados_relatorio.get('situacao', ''))
        dados_linha.append(dados_relatorio.get('data_relatorio', ''))
        dados_linha.append(dados_relatorio.get('fato_gerador', ''))
        dados_linha.append(dados_relatorio.get('protocolo', ''))
        dados_linha.append(dados_relatorio.get('tipo_visita', ''))
        
        # Coordenadas
        dados_linha.append(dados_relatorio.get('latitude', ''))
        dados_linha.append(dados_relatorio.get('longitude', ''))
        
        # Endereço
        endereco_completo = dados_relatorio.get('endereco', '')
        if dados_relatorio.get('numero'):
            endereco_completo += f", {dados_relatorio.get('numero', '')}"
        dados_linha.append(endereco_completo)
        
        dados_linha.append(dados_relatorio.get('numero', ''))
        dados_linha.append(dados_relatorio.get('complemento', ''))
        dados_linha.append(dados_relatorio.get('municipio', ''))
        dados_linha.append(dados_relatorio.get('uf', ''))
        dados_linha.append(dados_relatorio.get('cep', ''))
        
        # Contratante
        dados_linha.append(dados_relatorio.get('nome_contratante', ''))
        dados_linha.append(dados_relatorio.get('registro_contratante', ''))
        dados_linha.append(dados_relatorio.get('cpf_cnpj', ''))
        
        # Constatação e motivo
        constatacao = dados_relatorio.get('constatacao_fiscal', '')
        if constatacao and len(constatacao) > 100:
            constatacao = constatacao[:97] + "..."
        dados_linha.append(constatacao)
        
        motivo = dados_relatorio.get('motivo_acao', '')
        if motivo and len(motivo) > 100:
            motivo = motivo[:97] + "..."
        dados_linha.append(motivo)
        
        # Atividade desenvolvida
        dados_linha.append(dados_relatorio.get('caracteristica', ''))
        dados_linha.append(dados_relatorio.get('fase_atividade', ''))
        dados_linha.append(dados_relatorio.get('num_pavimentos', ''))
        dados_linha.append(dados_relatorio.get('quantificacao', ''))
        dados_linha.append(dados_relatorio.get('unidade_medida', ''))
        dados_linha.append(dados_relatorio.get('natureza', ''))
        dados_linha.append(dados_relatorio.get('tipo_construcao', ''))
        
        # Número de contratados
        num_contratados = len(dados_relatorio.get('contratados_data', []))
        dados_linha.append(str(num_contratados))
        
        # Documentos
        docs_solicitados = dados_relatorio.get('documentos_solicitados', '')
        if docs_solicitados and len(docs_solicitados) > 100:
            docs_solicitados = docs_solicitados[:97] + "..."
        dados_linha.append(docs_solicitados)
        
        docs_recebidos = dados_relatorio.get('documentos_recebidos', '')
        if docs_recebidos and len(docs_recebidos) > 100:
            docs_recebidos = docs_recebidos[:97] + "..."
        dados_linha.append(docs_recebidos)
        
        # Número de fotos
        fotos_info = st.session_state.get('fotos_info', [])
        dados_linha.append(str(len(fotos_info)))
        
        # Informações do PDF
        dados_linha.append(pdf_path if pdf_path else "Arquivo local")
        
        # Link do Google Drive (se houver)
        drive_link = st.session_state.get('drive_link', '')
        dados_linha.append(drive_link)
        
        # Timestamp
        dados_linha.append(dt.now().isoformat())
        
        # ================================================
        # 6. ADICIONAR A NOVA LINHA
        # ================================================
        try:
            worksheet.append_row(dados_linha)
            st.success(f"✅ Dados do relatório salvos no Google Sheets!")
            return True
        except Exception as e:
            st.error(f"❌ Erro ao adicionar linha no Google Sheets: {str(e)}")
            
            # Tentar método alternativo
            try:
                # Obter última linha
                ultima_linha = len(worksheet.get_all_values()) + 1
                
                # Inserir célula por célula
                for col, valor in enumerate(dados_linha, 1):
                    worksheet.update_cell(ultima_linha, col, valor)
                
                st.success("✅ Dados salvos com método alternativo!")
                return True
            except Exception as e2:
                st.error(f"❌ Método alternativo também falhou: {str(e2)}")
                return False
        
    except Exception as e:
        st.error(f"❌ Erro ao salvar no Google Sheets: {str(e)}")
        return False

# ========== CLASSE FOTOINFO ==========
class FotoInfo:
    def __init__(self, image_bytes, comentario="", foto_id=None):
        self.foto_id = foto_id or str(uuid.uuid4())
        self.image_bytes = image_bytes
        self.comentario = comentario
        self.timestamp = time.time()
        self._image_obj = None
        self._thumbnail = None
    
    def get_image(self):
        if self._image_obj is None:
            self._image_obj = Image.open(BytesIO(self.image_bytes))
        return self._image_obj
    
    def get_thumbnail(self, size=(200, 200)):
        if self._thumbnail is None:
            img = self.get_image()
            self._thumbnail = img.copy()
            self._thumbnail.thumbnail(size, Image.LANCZOS)
        return self._thumbnail

# ========== FUNÇÕES DO GOOGLE DRIVE ==========
def autenticar_google_drive():
    """Autentica com Google Drive usando Service Account do secrets"""
    if not GOOGLE_DRIVE_AVAILABLE:
        st.warning("Bibliotecas do Google Drive não disponíveis.")
        return None
    
    try:
        # Obter credenciais do secrets
        creds_info = obter_credenciais_google()
        
        if not creds_info:
            st.error("❌ Credenciais do Google não encontradas")
            return None
        
        # Usar service account para autenticação
        from google.oauth2 import service_account
        
        credentials = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=credentials)
        return service
        
    except Exception as e:
        st.error(f"Erro ao criar serviço do Drive: {str(e)}")
        return None

def upload_para_google_drive(caminho_arquivo, nome_arquivo, service, folder_id=None):
    """Faz upload de arquivo para Google Drive"""
    try:
        if not os.path.exists(caminho_arquivo):
            st.error(f"Arquivo não encontrado: {caminho_arquivo}")
            return None
        
        extensao = os.path.splitext(nome_arquivo)[1].lower()
        mimetypes = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel'
        }
        mimetype = mimetypes.get(extensao, 'application/octet-stream')
        
        if not folder_id:
            st.error("ID da pasta do Google Drive não configurado.")
            return None
        
        # Verificar se arquivo já existe
        query = f"name = '{nome_arquivo}' and '{folder_id}' in parents and trashed = false"
        try:
            results = service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)'
            ).execute()
            
            arquivos = results.get('files', [])
        except HttpError as error:
            st.error(f'Erro ao verificar arquivos: {error}')
            return None
        
        if arquivos:
            # Atualizar arquivo existente
            file_id = arquivos[0]['id']
            file_metadata = {'name': nome_arquivo}
            
            media = MediaFileUpload(
                caminho_arquivo,
                mimetype=mimetype,
                resumable=True
            )
            
            file = service.files().update(
                fileId=file_id,
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, webContentLink, size, modifiedTime'
            ).execute()
            
            resultado = {
                'id': file.get('id'),
                'nome': file.get('name'),
                'link_visualizacao': file.get('webViewLink'),
                'link_download': file.get('webContentLink'),
                'tamanho_bytes': int(file.get('size', 0)),
                'modificado': file.get('modifiedTime'),
                'acao': 'ATUALIZADO'
            }
        else:
            # Criar novo arquivo
            file_metadata = {
                'name': nome_arquivo,
                'description': f'Relatório de Fiscalização gerado pelo sistema CREA-RJ'
            }
            
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            media = MediaFileUpload(
                caminho_arquivo,
                mimetype=mimetype,
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, webContentLink, size, createdTime'
            ).execute()
            
            resultado = {
                'id': file.get('id'),
                'nome': file.get('name'),
                'link_visualizacao': file.get('webViewLink'),
                'link_download': file.get('webContentLink'),
                'tamanho_bytes': int(file.get('size', 0)),
                'criado': file.get('createdTime'),
                'acao': 'CRIADO'
            }
        
        return resultado
        
    except HttpError as error:
        st.error(f'Erro HTTP do Google Drive: {error}')
        return None
    except Exception as e:
        st.error(f'Erro ao fazer upload: {str(e)}')
        return None

# ========== FUNÇÃO PARA CARREGAR DADOS DOS FISCAIS DO ARQUIVO PÚBLICO ==========
@st.cache_data(ttl=3600)
def carregar_dados_fiscais():
    """Carrega os dados dos fiscais do arquivo Fiscais.xlsx (público no GitHub)"""
    
    # URLs possíveis para o arquivo Fiscais.xlsx
    urls_possiveis = [
        "Fiscais.xlsx",  # Arquivo local
        "data/Fiscais.xlsx",
        "Template/Fiscais.xlsx",
        "excel/Fiscais.xlsx",
        "uploads/Fiscais.xlsx",
        "database/Fiscais.xlsx"
    ]
    
    dados_fiscais = {}
    
    for url in urls_possiveis:
        try:
            # Tentar arquivo local
            if os.path.exists(url):
                df = pd.read_excel(url, sheet_name='DADOS FISCAIS')
            else:
                continue
            
            # Verificar colunas necessárias
            colunas_necessarias = ['NOME', 'MATRICULA', 'UNIDADE']
            colunas_disponiveis = [col for col in colunas_necessarias if col in df.columns]
            
            if len(colunas_disponiveis) < 3:
                st.warning(f"Arquivo {url} não contém todas as colunas necessárias. Encontradas: {df.columns.tolist()}")
                continue
            
            # Processar dados
            df['MATRICULA'] = df['MATRICULA'].astype(str).str.strip()
            df = df[df['MATRICULA'].notna() & (df['MATRICULA'] != '')]
            
            for _, row in df.iterrows():
                matricula = str(row['MATRICULA']).strip()
                if matricula and matricula != 'nan':
                    matricula_formatada = formatar_matricula(matricula)
                    dados_fiscais[matricula_formatada] = {
                        'NOME': str(row['NOME']).strip() if pd.notna(row['NOME']) else '',
                        'MATRICULA': matricula_formatada,
                        'UNIDADE': str(row['UNIDADE']).strip() if pd.notna(row['UNIDADE']) else ''
                    }
            
            if dados_fiscais:
                st.success(f"✅ Dados fiscais carregados: {len(dados_fiscais)} agentes")
                return dados_fiscais
                
        except Exception as e:
            st.warning(f"⚠️ Não foi possível carregar de {url}: {e}")
            continue
    
    # Se não conseguiu carregar de nenhuma fonte, usar dados de exemplo
    st.warning("⚠️ Não foi possível carregar dados fiscais do arquivo. Usando dados de exemplo.")
    
    # Dados de exemplo para desenvolvimento/demo
    dados_exemplo = {
        "0496": {
            "NOME": "Carlos Franklin Dias Moreira",
            "MATRICULA": "0496",
            "UNIDADE": "SBXD"
        },
        "1234": {
            "NOME": "João Silva",
            "MATRICULA": "1234",
            "UNIDADE": "CREA-RJ"
        },
        "5678": {
            "NOME": "Maria Santos",
            "MATRICULA": "5678",
            "UNIDADE": "CREA-RJ"
        },
        "9999": {
            "NOME": "Agente Demonstração",
            "MATRICULA": "9999",
            "UNIDADE": "CREA-RJ"
        }
    }
    
    return dados_exemplo

# ========== CLASSES DO SISTEMA ORIGINAL ==========
class ContadorRelatorios:
    def __init__(self, arquivo_contador="contador_relatorios.json"):
        self.arquivo_contador = arquivo_contador
        self.contadores = self.carregar_contadores()
    
    def carregar_contadores(self):
        try:
            if os.path.exists(self.arquivo_contador):
                with open(self.arquivo_contador, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def salvar_contadores(self):
        try:
            with open(self.arquivo_contador, 'w') as f:
                json.dump(self.contadores, f)
        except Exception as e:
            st.error(f"Erro ao salvar contadores: {e}")
    
    def gerar_numero_relatorio(self, matricula):
        """Gera número do relatório no formato: ANO + MATRÍCULA (4 dígitos) + SEQUENCIAL (4 dígitos)"""
        ano = dt.now().strftime("%Y")  # Ano com 4 dígitos
        matricula_formatada = matricula.zfill(4)  # Matrícula com 4 dígitos
        
        # Chave para controle: ANO + MATRÍCULA
        chave = f"{ano}_{matricula_formatada}"
        
        # Inicializar ou incrementar contador
        if chave not in self.contadores:
            self.contadores[chave] = 0  # Iniciar em 0 para primeiro ser 0001
        
        self.contadores[chave] += 1
        
        # Formatar sequencial com 4 dígitos
        sequencial_formatado = str(self.contadores[chave]).zfill(4)
        
        self.salvar_contadores()
        
        # Formato final: ANO(4) + MATRÍCULA(4) + SEQUENCIAL(4) = 12 dígitos
        return f"{ano}{matricula_formatada}{sequencial_formatado}"

class PDF(FPDF):
    def __init__(self, logo_data=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logo_data = logo_data
    
    def header(self):
        self.set_font('Arial', 'B', 14)
        if self.logo_data:
            try:
                if os.path.exists(self.logo_data):
                    img_width = 40
                    x_position = (210 - img_width) / 2
                    self.image(self.logo_data, x=x_position, y=10, w=img_width)
                    self.ln(15)
            except Exception as e:
                pass
        
        self.cell(0, 8, 'RELATÓRIO DE FISCALIZAÇÃO', 0, 1, 'C')
        
        if hasattr(self, 'agente_info') and self.agente_info:
            self.ln(4)
            self.set_font('Arial', '', 10)
            nome = self.agente_info.get('NOME', '')
            matricula = self.agente_info.get('MATRICULA', '')
            unidade = self.agente_info.get('UNIDADE', '')
            
            if nome and matricula and unidade:
                agente_texto = f"{nome} - {matricula} - {unidade}"
                self.cell(0, 6, f'Agente de Fiscalização: {agente_texto}', 0, 1, 'C')
        
        self.ln(5)
    
    def footer(self):
        self.set_y(-12)
        self.set_font('Arial', 'I', 7)
        self.cell(0, 8, f'Página {self.page_no()}', 0, 0, 'C')
    
    def add_assinatura_agente(self, agente_info):
        if agente_info:
            self.ln(10)
            nome = agente_info.get('NOME', '')
            matricula = agente_info.get('MATRICULA', '')
            
            if nome:
                self.cell(0, 8, '________________________________________', 0, 1, 'C')
                self.set_font('Arial', 'B', 12)
                self.cell(0, 6, nome, 0, 1, 'C')
                self.set_font('Arial', 'I', 10)
                self.cell(0, 5, 'Agente de Fiscalização', 0, 1, 'C')
                self.set_font('Arial', '', 10)
                if matricula:
                    self.cell(0, 5, f'Matrícula: {matricula}', 0, 1, 'C')
    
    def add_images_to_pdf(self, fotos_info):
        if not fotos_info:
            return
        
        self.add_page()
        self.set_font('Arial', 'B', 12)
        self.cell(0, 8, 'FOTOS REGISTRADAS', 0, 1, 'C')
        self.ln(5)
        
        max_width = 180
        max_height = 180
        
        for i, foto_info in enumerate(fotos_info, 1):
            try:
                if i > 1:
                    self.add_page()
                
                img = foto_info.get_image()
                img_width, img_height = img.size
                
                width_mm = img_width * 0.264583
                height_mm = img_height * 0.264583
                
                if width_mm > max_width or height_mm > max_height:
                    ratio = min(max_width / width_mm, max_height / height_mm)
                    new_width_mm = width_mm * ratio
                    new_height_mm = height_mm * ratio
                    
                    new_width_px = int(new_width_mm / 0.264583)
                    new_height_px = int(new_height_mm / 0.264583)
                    
                    if new_width_px < img_width or new_height_px < img_height:
                        img_resized = img.resize((new_width_px, new_height_px), Image.LANCZOS)
                    else:
                        img_resized = img
                else:
                    img_resized = img
                    new_width_mm = width_mm
                    new_height_mm = height_mm
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_img:
                    img_resized.save(temp_img.name, 'JPEG', quality=85, optimize=True)
                    temp_img_path = temp_img.name
                
                x_position = (210 - new_width_mm) / 2
                self.set_font('Arial', 'B', 11)
                self.cell(0, 6, f'Foto {i}', 0, 1, 'C')
                self.ln(2)
                
                y_position = self.get_y()
                self.image(temp_img_path, x=x_position, y=y_position, w=new_width_mm)
                self.set_y(y_position + new_height_mm + 4)
                
                if foto_info.comentario and foto_info.comentario.strip():
                    self.ln(2)
                    self.set_font('Arial', 'I', 9)
                    
                    comentario = foto_info.comentario
                    if len(comentario) > 200:
                        comentario = comentario[:197] + "..."
                    
                    self.multi_cell(0, 4, f"Comentário: {comentario}")
                    self.set_font('Arial', '', 10)
                
                try:
                    os.unlink(temp_img_path)
                except:
                    pass
                
                if i < len(fotos_info):
                    self.ln(5)
                
            except Exception as e:
                self.set_font('Arial', 'I', 8)
                self.cell(0, 5, f'Foto {i}: (erro no processamento)', 0, 1)
                self.ln(2)

# ========== FUNÇÕES AUXILIARES ==========
@st.cache_data(ttl=300)
def formatar_matricula(matricula):
    """Formata matrícula para ter exatamente 4 dígitos"""
    matricula_limpa = re.sub(r'\D', '', matricula)
    matricula_limpa = matricula_limpa[-4:] if len(matricula_limpa) > 4 else matricula_limpa
    return matricula_limpa.zfill(4)

def calcular_largura_celula(rotulos, pdf, padding=5):
    larguras = []
    for rotulo in rotulos:
        if rotulo:
            larguras.append(pdf.get_string_width(rotulo))
    if larguras:
        return max(larguras) + padding
    return 20

def criar_pdf(dados, logo_data, fotos_info=None, agente_info=None):
    pdf = PDF(logo_data=logo_data, orientation='P', unit='mm', format='A4')
    pdf.set_title("Relatório de Fiscalização")
    pdf.set_author("Sistema de Fiscalização CREA-RJ")
    
    if agente_info:
        pdf.agente_info = agente_info
    
    pdf.add_page()
    
    rotulos_todos = [
        'Número:', 'Situação:', 'Data:', 'Fato Gerador:', 'Protocolo:', 'Tipo Visita:',
        'Latitude:', 'Longitude:', 'Endereço:', 'Município:', 'CEP:', 'Descritivo:',
        'Nome:', 'Registro:', 'CPF/CNPJ:', 'Constatação:', 'Motivo Ação:',
        'Característica:', 'Fase Atividade:', 'Nº Pavimentos:', 'Quantificação:', 
        'Natureza:', 'Tipo Construção:', 'Profissional:', 'Registro:', 'CPF/CNPJ:',
        'Contratado PF/PJ:', 'Identificação do fiscalizado:', 'Número ART:', 'Número RRT:', 'Número TRT:',
        'Ramo Atividade:', 'Atividade (Serviço Executado):', 'Data Relatório Anterior:',
        'Informações Complementares:', 'Fonte Informação:', 'Qualificação:'
    ]
    
    largura_celula = calcular_largura_celula(rotulos_todos, pdf, padding=6)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(largura_celula, 7, 'Número:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('numero_relatorio', ''), 0, 1)
    
    if dados.get('situacao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Situação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('situacao', ''), 0, 1)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(largura_celula, 7, 'Data:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('data_relatorio', dt.now().strftime('%d/%m/%Y')), 0, 1)
    
    if dados.get('fato_gerador'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Fato Gerador:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('fato_gerador', ''), 0, 1)
    
    if dados.get('protocolo'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Protocolo:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('protocolo', ''), 0, 1)
    
    if dados.get('tipo_visita'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Tipo Visita:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('tipo_visita', ''), 0, 1)
    
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '01', 0, 0)
    pdf.cell(0, 9, ' - ENDEREÇO DO EMPREENDIMENTO', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if dados.get('latitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Latitude:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('latitude', ''), 0, 1)
    
    if dados.get('longitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Longitude:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('longitude', ''), 0, 1)
    
    endereco = dados.get('endereco', '')
    numero = dados.get('numero', '')
    complemento = dados.get('complemento', '')
    
    if endereco or numero:
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Endereço:', 0, 0)
        pdf.set_font('Arial', '', 10)
        
        endereco_completo = ""
        if endereco:
            endereco_completo += f"{endereco}"
        if numero:
            endereco_completo += f", nº: {numero}"
        if complemento:
            endereco_completo += f" / {complemento}"
        
        if len(endereco_completo) > 80:
            pdf.multi_cell(0, 5, endereco_completo)
        else:
            pdf.cell(0, 6, endereco_completo, 0, 1)
    
    municipio = dados.get('municipio', '')
    uf = dados.get('uf', '')
    if municipio:
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Município:', 0, 0)
        pdf.set_font('Arial', '', 10)
        municipio_uf = municipio
        if uf:
            municipio_uf += f" - {uf}"
        pdf.cell(0, 6, municipio_uf, 0, 1)
    
    if dados.get('cep'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'CEP:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cep', ''), 0, 1)
    
    if dados.get('descritivo_endereco'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Descritivo:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('descritivo_endereco', ''))
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '02', 0, 0)
    pdf.cell(0, 9, ' - IDENTIFICAÇÃO DO PROPRIETÁRIO/CONTRATANTE', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if dados.get('nome_contratante'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Nome:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('nome_contratante', ''), 0, 1)
    
    if dados.get('registro_contratante'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('registro_contratante', ''), 0, 1)
    
    if dados.get('cpf_cnpj'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cpf_cnpj', ''), 0, 1)
    
    if dados.get('constatacao_fiscal'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Constatação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('constatacao_fiscal', ''))
    
    if dados.get('motivo_acao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Motivo Ação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('motivo_acao', ''))
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '03', 0, 0)
    pdf.cell(0, 9, ' - ATIVIDADE DESENVOLVIDA (OBRA, SERVIÇO, EVENTOS)', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if dados.get('caracteristica'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Característica:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('caracteristica', ''), 0, 1)
    
    if dados.get('fase_atividade'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Fase Atividade:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('fase_atividade', ''), 0, 1)
    
    if dados.get('num_pavimentos') and dados.get('num_pavimentos') != '0':
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Nº Pavimentos:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('num_pavimentos', ''), 0, 1)
    
    quantificacao = dados.get('quantificacao', '')
    unidade_medida = dados.get('unidade_medida', '')
    if quantificacao:
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Quantificação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        quant_text = quantificacao
        if unidade_medida:
            quant_text += f" {unidade_medida}"
        pdf.cell(0, 6, quant_text, 0, 1)
    
    if dados.get('natureza'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Natureza:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('natureza', ''), 0, 1)
    
    if dados.get('tipo_construcao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Tipo Construção:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('tipo_construcao', ''), 0, 1)
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '04', 0, 0)
    pdf.cell(0, 9, ' - IDENTIFICAÇÃO DOS CONTRATADOS, RESPONSÁVEIS TÉCNICOS E/OU FISCALIZADOS', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    contratados_data = dados.get('contratados_data', [])
    
    if not contratados_data:
        pdf.multi_cell(0, 5, 'SEM CONTRATADOS E RESPONSÁVEIS TÉCNICOS')
    else:
        for i, contrato in enumerate(contratados_data, 1):
            if i > 1:
                pdf.ln(5)
                pdf.cell(0, 6, '=' * 60, 0, 1)
                pdf.ln(2)
                pdf.cell(0, 6, f'--- Registro {i} ---', 0, 1)
                pdf.ln(2)
            
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, 'Identificação do Contratante:', 0, 1)
            pdf.set_font('Arial', '', 10)
            
            mesmo_contratante = contrato.get('mesmo_contratante', '')
            
            if mesmo_contratante == "SIM":
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 6, '(Mesmo do campo 02)', 0, 1)
                pdf.set_font('Arial', '', 10)
                
                if dados.get('nome_contratante'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'Nome:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, dados.get('nome_contratante', ''), 0, 1)
                
                if dados.get('registro_contratante'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, dados.get('registro_contratante', ''), 0, 1)
                
                if dados.get('cpf_cnpj'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, dados.get('cpf_cnpj', ''), 0, 1)
            
            elif mesmo_contratante == "NÃO":
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 6, '(Informações específicas para este registro)', 0, 1)
                pdf.set_font('Arial', '', 10)
                
                if contrato.get('nome_contratante_secao04'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'Nome:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, contrato.get('nome_contratante_secao04', ''), 0, 1)
                
                if contrato.get('registro_contratante_secao04'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, contrato.get('registro_contratante_secao04', ''), 0, 1)
                
                if contrato.get('cpf_cnpj_secao04'):
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, contrato.get('cpf_cnpj_secao04', ''), 0, 1)
            
            pdf.ln(2)
            
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, 'Dados do Contratado/Responsável Técnico:', 0, 1)
            pdf.set_font('Arial', '', 10)
            
            if contrato.get('contratado_pf_pj'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Contratado PF/PJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('contratado_pf_pj', ''), 0, 1)
            
            if contrato.get('registro'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('registro', ''), 0, 1)
            
            if contrato.get('cpf_cnpj_contratado'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('cpf_cnpj_contratado', ''), 0, 1)
            
            if contrato.get('contrato'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Profissional:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('contrato', ''), 0, 1)
            
            if contrato.get('identificacao_fiscalizado'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Identificação do fiscalizado:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('identificacao_fiscalizado', ''), 0, 1)
            
            if contrato.get('numero_art'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número ART:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_art', ''), 0, 1)
            
            if contrato.get('numero_rrt'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número RRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_rrt', ''), 0, 1)
            
            if contrato.get('numero_trt'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número TRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_trt', ''), 0, 1)
            
            if contrato.get('ramo_atividade'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Ramo Atividade:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('ramo_atividade', ''), 0, 1)
            
            if contrato.get('atividade_servico'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Atividade (Serviço Executado):', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('atividade_servico', ''), 0, 1)
            
            pdf.ln(3)
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '05', 0, 0)
    pdf.cell(0, 9, ' - DOCUMENTOS SOLICITADOS / EXPEDIDOS', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    documentos_solicitados = dados.get('documentos_solicitados', '')
    if documentos_solicitados and documentos_solicitados != "SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS":
        pdf.multi_cell(0, 5, documentos_solicitados)
    else:
        pdf.multi_cell(0, 5, 'SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS')
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '06', 0, 0)
    pdf.cell(0, 9, ' - DOCUMENTOS RECEBIDOS', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    documentos_recebidos = dados.get('documentos_recebidos', '')
    if documentos_recebidos and documentos_recebidos != "SEM DOCUMENTOS RECEBIDOS":
        pdf.multi_cell(0, 5, documentos_recebidos)
    else:
        pdf.multi_cell(0, 5, 'SEM DOCUMENTOS RECEBIDOS')
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '07', 0, 0)
    pdf.cell(0, 9, ' - OUTRAS INFORMAÇÕES', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if dados.get('data_relatorio_anterior') and dados.get('data_relatorio_anterior') != "NAO INFORMADO":
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Data Relatório Anterior:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('data_relatorio_anterior', ''), 0, 1)
    
    if dados.get('informacoes_complementares'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Informações Complementares:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('informacoes_complementares', ''))
    
    if dados.get('fonte_informacao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Fonte Informação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('fonte_informacao', ''), 0, 1)
    
    if dados.get('qualificacao_fonte'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Qualificação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('qualificacao_fonte', ''), 0, 1)
    
    pdf.ln(4)
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '08', 0, 0)
    pdf.cell(0, 9, ' - FOTOS', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if fotos_info:
        pdf.multi_cell(0, 5, f"Total de fotos registradas: {len(fotos_info)}")
    else:
        pdf.multi_cell(0, 5, 'NAO INFORMADO')
    
    pdf.ln(4)
    
    if fotos_info:
        pdf.add_images_to_pdf(fotos_info)
    
    if agente_info:
        pdf.add_assinatura_agente(agente_info)
    
    return pdf

# ========== FUNÇÃO PARA OBTER LOGO ==========
def obter_logo():
    logos_possiveis = [
        "10.png",
        "logo.png",
        "Logo.png",
        "assets/logo.png",
        "images/logo.png",
        "static/logo.png",
    ]
    
    for logo_path in logos_possiveis:
        if os.path.exists(logo_path):
            return logo_path
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (200, 100), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        
        try:
            fnt = ImageFont.truetype("arial.ttf", 20)
        except:
            fnt = ImageFont.load_default()
        
        d.text((10, 40), "CREA-RJ", font=fnt, fill=(255, 255, 255))
        d.text((10, 60), "FISCALIZAÇÃO", font=fnt, fill=(255, 255, 255))
        
        temp_logo_path = "temp_logo.png"
        img.save(temp_logo_path)
        return temp_logo_path
    except:
        placeholder_base64 = "iVBORw0KGgoAAAANSUhEUgAAAGQAAAAyCAYAAACqNX6+AAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAIHSURBVHgB7dqxSxxRHMDx7+a6Cja2Vgk22p1wkpxykqBFfsB1J5zkHyBlizZp0iY/4CSnwCluk9rKQst0p9wVd7JTpHO+9+Z3i+D31wjvgeAdt7c38Hjz3ps3Oz9Lvd7qAQB80W9w7wEgHEIAhBAAMYQAiCEkQK8JgBiGyR5hW0v0yP76bwghoTF9SFgx9p7UDBFDSKBMH8J2FqhuX5J2QwGzEFMYQkLlvpS23RBCCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQAwhAGIIARBDCIAYQgDEEAIghhAAMYQAiCEEQEofVjMOC9aQpjoAAAAASUVORK5CYII="
        temp_logo_path = "placeholder_logo.png"
        with open(temp_logo_path, "wb") as f:
            f.write(base64.b64decode(placeholder_base64))
        return temp_logo_path

# ========== FUNÇÕES PARA LIMPAR FORMULÁRIO ==========
def limpar_formulario():
    if 'fotos_info' in st.session_state:
        st.session_state.fotos_info = []
    
    if 'contratados_data' in st.session_state:
        st.session_state.contratados_data = []
    
    if 'current_contratado_index' in st.session_state:
        st.session_state.current_contratado_index = 0
    
    if 'current_foto_index' in st.session_state:
        st.session_state.current_foto_index = 0
    
    if 'documentos_solicitados_text' not in st.session_state:
        st.session_state.documentos_solicitados_text = ""
    
    if 'documentos_recebidos_text' not in st.session_state:
        st.session_state.documentos_recebidos_text = ""
    
    if 'temp_photo_bytes' in st.session_state:
        st.session_state.temp_photo_bytes = None
    
    if 'camera_counter' in st.session_state:
        st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
    
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    st.session_state.form_widget_counter += 1

def limpar_campos_registro():
    return {
        'mesmo_contratante': None,
        'nome_contratante_secao04': "",
        'registro_contratante_secao04': "",
        'cpf_cnpj_secao04': "",
        'contrato': "",
        'registro': "",
        'cpf_cnpj_contratado': "",
        'contratado_pf_pj': "",
        'identificacao_fiscalizado': " ",
        'numero_art': "",
        'numero_rrt': "",
        'numero_trt': "",
        'ramo_atividade': "",
        'atividade_servico': ""
    }

def limpar_campos_secao_04():
    return limpar_campos_registro()

def salvar_registro_atual(dados_registro):
    try:
        if 'contratados_data' not in st.session_state:
            st.session_state.contratados_data = []
        
        st.session_state.contratados_data.append(dados_registro.copy())
        
        total_registros = len(st.session_state.contratados_data)
        
        return True, total_registros
    except Exception as e:
        st.error(f"Erro ao salvar registro: {e}")
        return False, 0

# ========== FUNÇÃO PRINCIPAL ==========
def main():
    # ========== INICIALIZAÇÃO DO SESSION_STATE ==========
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'matricula' not in st.session_state:
        st.session_state.matricula = ""
    if 'senha_hash' not in st.session_state:
        st.session_state.senha_hash = ""
    if 'numero_relatorio_gerado' not in st.session_state:
        st.session_state.numero_relatorio_gerado = ""
    if 'agente_info' not in st.session_state:
        st.session_state.agente_info = None
    if 'drive_link' not in st.session_state:
        st.session_state.drive_link = ""
    
    if 'formulario_inicializado' not in st.session_state:
        st.session_state.formulario_inicializado = False
    
    if 'fotos_info' not in st.session_state:
        st.session_state.fotos_info = []
    if 'contratados_data' not in st.session_state:
        st.session_state.contratados_data = []
    if 'current_registro' not in st.session_state:
        st.session_state.current_registro = limpar_campos_registro()
    if 'current_foto_index' not in st.session_state:
        st.session_state.current_foto_index = 0
    if 'documentos_solicitados_text' not in st.session_state:
        st.session_state.documentos_solicitados_text = ""
    if 'documentos_recebidos_text' not in st.session_state:
        st.session_state.documentos_recebidos_text = ""
    
    if 'temp_photo_bytes' not in st.session_state:
        st.session_state.temp_photo_bytes = None
    if 'camera_counter' not in st.session_state:
        st.session_state.camera_counter = 0
    
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    
    if 'registro_counter' not in st.session_state:
        st.session_state.registro_counter = 1
    
    if 'secao04_limpa_counter' not in st.session_state:
        st.session_state.secao04_limpa_counter = 0
    
    # Carregar dados dos fiscais do arquivo público
    dados_fiscais = carregar_dados_fiscais()
    
    # Inicializar gerenciador de contadores
    contador_manager = ContadorRelatorios()
    
    # Obter logo para uso em toda a aplicação
    logo_data = obter_logo()
    
    # Página de login se não estiver logado
    if not st.session_state.logged_in:
        st.title("Relatório de Fiscalização - CREA-RJ")
        
        try:
            if os.path.exists(logo_data):
                img = Image.open(logo_data)
                img.thumbnail((300, 300))
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    st.image(img, width=300)
            else:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    st.markdown("<div style='height: 200px; display: flex; align-items: center; justify-content: center; font-size: 50px;'>🔒</div>", unsafe_allow_html=True)
        except:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.markdown("<div style='height: 200px; display: flex; align-items: center; justify-content: center; font-size: 50px;'>🔒</div>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            matricula_input = st.text_input(
                "Matrícula (3-4 dígitos)",
                placeholder="Ex: 496 ou 0496",
                key="login_matricula"
            )
            
            if matricula_input:
                matricula_formatada = formatar_matricula(matricula_input)
                st.caption(f"Matrícula formatada: {matricula_formatada}")
            
            senha_input = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite sua senha",
                key="login_senha"
            )
            
            if st.button("Entrar", type="primary", use_container_width=True, key="login_button"):
                if matricula_input and senha_input:
                    matricula_limpa = re.sub(r'\D', '', matricula_input)
                    
                    if len(matricula_limpa) >= 3 and len(matricula_limpa) <= 4:
                        matricula_formatada = formatar_matricula(matricula_input)
                        
                        agente_info = None
                        if dados_fiscais:
                            if matricula_formatada in dados_fiscais:
                                agente_info = dados_fiscais[matricula_formatada]
                            elif matricula_limpa in dados_fiscais:
                                agente_info = dados_fiscais[matricula_limpa]
                        
                        if agente_info:
                            senha_hash = str(hash(senha_input))[-4:].zfill(4)
                            numero_relatorio = contador_manager.gerar_numero_relatorio(matricula_formatada)
                            
                            st.session_state.logged_in = True
                            st.session_state.matricula = matricula_formatada
                            st.session_state.senha_hash = senha_hash
                            st.session_state.numero_relatorio_gerado = numero_relatorio
                            st.session_state.agente_info = agente_info
                            
                            st.success(f"Login realizado! Agente: {agente_info['NOME']}")
                            st.info(f"Número do relatório gerado: {numero_relatorio}")
                            st.rerun()
                        else:
                            st.warning("Usando modo de demonstração (agente de exemplo)")
                            agente_info = {
                                'NOME': 'Agente de Demonstração',
                                'MATRICULA': matricula_formatada,
                                'UNIDADE': 'CREA-RJ'
                            }
                            
                            senha_hash = str(hash(senha_input))[-4:].zfill(4)
                            numero_relatorio = contador_manager.gerar_numero_relatorio(matricula_formatada)
                            
                            st.session_state.logged_in = True
                            st.session_state.matricula = matricula_formatada
                            st.session_state.senha_hash = senha_hash
                            st.session_state.numero_relatorio_gerado = numero_relatorio
                            st.session_state.agente_info = agente_info
                            
                            st.success(f"Modo demonstração ativado!")
                            st.info(f"Número do relatório gerado: {numero_relatorio}")
                            st.rerun()
                    else:
                        st.error("Matrícula deve ter entre 3 e 4 dígitos!")
                else:
                    st.error("Preencha matrícula e senha!")
        
        st.markdown("---")
        st.markdown("**Sistema de Fiscalização CREA-RJ**")
        st.caption("Versão 1.0 - Desenvolvido para otimização dos processos de fiscalização")
        return
    
    # Barra lateral com menu
    with st.sidebar:
        try:
            if os.path.exists(logo_data):
                img = Image.open(logo_data)
                img.thumbnail((200, 200))
                st.image(img, width=200)
            else:
                st.markdown("<div style='height: 200px; display: flex; align-items: center; justify-content: center; font-size: 40px;'>📋</div>", unsafe_allow_html=True)
        except:
            st.markdown("<div style='height: 200px; display: flex; align-items: center; justify-content: center; font-size: 40px;'>📋</div>", unsafe_allow_html=True)
        
        st.title("Relatório de Fiscalização")
        
        if st.session_state.agente_info:
            nome = st.session_state.agente_info.get('NOME', '')
            matricula = st.session_state.agente_info.get('MATRICULA', '')
            unidade = st.session_state.agente_info.get('UNIDADE', '')
            
            st.markdown(f"**Agente:** {nome}")
            st.markdown(f"**Matrícula:** {matricula}")
            st.markdown(f"**Unidade:** {unidade}")
        
        # Mostrar número do relatório com formatação
        numero_formatado = st.session_state.numero_relatorio_gerado
        if numero_formatado:
            ano = numero_formatado[:4]
            mat = numero_formatado[4:8]
            seq = numero_formatado[8:]
            st.markdown(f"**Relatório atual:** `{ano}.{mat}.{seq}`")
        
        with st.expander("⚙️ Configurações"):
            st.info("Configurações do sistema")
            
            # Botão de teste Google Sheets
            if st.button("🧪 Testar Google Sheets", key="testar_sheets_sidebar"):
                try:
                    import gspread
                    from google.oauth2.service_account import Credentials
                    
                    creds_info = obter_credenciais_google()
                    if not creds_info:
                        st.error("Credenciais não encontradas")
                        return
                    
                    scope = ['https://spreadsheets.google.com/feeds',
                            'https://www.googleapis.com/auth/drive']
                    credentials = Credentials.from_service_account_info(creds_info, scopes=scope)
                    gc = gspread.authorize(credentials)
                    
                    spreadsheet_id = st.secrets.google_sheets.spreadsheet_id
                    spreadsheet = gc.open_by_key(spreadsheet_id)
                    
                    st.success(f"✅ Conectado: {spreadsheet.title}")
                    
                    from datetime import datetime as dt_temp  # Nome temporário para evitar conflito
                    worksheet_name = st.secrets.google_sheets.get('worksheet_name', 'RELATORIOS')
                    try:
                        worksheet = spreadsheet.worksheet(worksheet_name)
                    except:
                        worksheet = spreadsheet.add_worksheet(worksheet_name, 100, 50)
                    
                    teste = ["TESTE SIDEBAR", dt_temp.now().strftime("%H:%M:%S")]
                    worksheet.append_row(teste)
                    
                    st.success("✅ Teste de escrita realizado!")
                    
                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")
            
            if GOOGLE_DRIVE_FOLDER_ID and GOOGLE_DRIVE_FOLDER_ID != "seu-folder-id-aqui":
                st.success(f"✅ Google Drive configurado")
            else:
                st.warning("Google Drive não configurado")
        
        opcao = st.radio("Selecione o módulo:", ("OBRA", "EMPRESA", "EVENTOS", "AGRONOMIA"), key="sidebar_radio")
        
        if st.button("Sair", type="secondary", use_container_width=True, key="logout_button"):
            st.session_state.logged_in = False
            st.session_state.matricula = ""
            st.session_state.senha_hash = ""
            st.session_state.numero_relatorio_gerado = ""
            st.session_state.agente_info = None
            st.session_state.formulario_inicializado = False
            st.session_state.form_widget_counter = 0
            limpar_formulario()
            st.rerun()

    # ========== MÓDULO OBRA ==========
    if opcao == "OBRA":
        st.markdown("""
        <div style="display: flex; align-items: center; margin-bottom: 20px;">
            <div style="flex-shrink: 0; margin-right: 40px;">
        """, unsafe_allow_html=True)
        
        try:
            if os.path.exists(logo_data):
                img = Image.open(logo_data)
                img.thumbnail((120, 120))
                st.image(img, width=120)
        except:
            pass
        
        st.markdown("""
            </div>
            <div>
                <h1 style="margin: 0; color: #1E3A8A;">Relatório de Fiscalização - Obra</h1>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.session_state.agente_info:
            nome = st.session_state.agente_info.get('NOME', '')
            matricula = st.session_state.agente_info.get('MATRICULA', '')
            unidade = st.session_state.agente_info.get('UNIDADE', '')
            
            # Campo Agente de Fiscalização: Nome - Matricula - Unidade
            st.markdown(f"**Agente de Fiscalização:** {nome} - {matricula} - {unidade}")
        
        # Mostrar número do relatório formatado
        numero_formatado = st.session_state.numero_relatorio_gerado
        if numero_formatado:
            ano = numero_formatado[:4]
            mat = numero_formatado[4:8]
            seq = numero_formatado[8:]
            st.markdown(f"**Número do Relatório:** `{ano}.{mat}.{seq}`")
        
        st.markdown("Preencha os dados abaixo para gerar o relatório de fiscalização.")
        
        if not st.session_state.formulario_inicializado:
            st.session_state.fotos_info = []
            st.session_state.contratados_data = []
            st.session_state.current_registro = limpar_campos_registro()
            st.session_state.registro_counter = 1
            st.session_state.current_foto_index = 0
            st.session_state.documentos_solicitados_text = ""
            st.session_state.documentos_recebidos_text = ""
            st.session_state.formulario_inicializado = True
        
        widget_counter = st.session_state.form_widget_counter
        secao04_counter = st.session_state.secao04_limpa_counter
        
        # Cabeçalho do Relatório
        st.header("DADOS GERAIS DO RELATÓRIO")
        col1, col2, col3 = st.columns(3)
        with col1:
            # Mostrar número formatado
            numero_formatado = st.session_state.numero_relatorio_gerado
            if numero_formatado:
                ano = numero_formatado[:4]
                mat = numero_formatado[4:8]
                seq = numero_formatado[8:]
                numero_formatado_display = f"{ano}.{mat}.{seq}"
            else:
                numero_formatado_display = ""
            
            st.text_input("Número do Relatório", 
                         value=numero_formatado_display,
                         disabled=True,
                         key=f"numero_relatorio_display_{widget_counter}")
            
            situacao = st.selectbox("Situação", ["", "CADASTRADO", "EM ANDAMENTO", "CONCLUÍDO", "CANCELADO"], 
                                   key=f"situacao_select_{widget_counter}")
        with col2:
            data_relatorio = st.date_input("Data do Relatório", value=dt.now(), 
                                          key=f"data_relatorio_input_{widget_counter}")
            fato_gerador = st.text_input("Fato Gerador", placeholder="Ex: AÇÃO PROGRAMADA DILIGENCIA VERIFICAÇÃO", 
                                        key=f"fato_gerador_input_{widget_counter}")
        with col3:
            protocolo = st.text_input("Protocolo", placeholder="Número do protocolo", 
                                     key=f"protocolo_input_{widget_counter}")
            
            tipo_visita_opcoes = ["", "AFC", "Obra", "Manutenção Predial", "Carnaval", "Empresa", 
                                "Posto de Combustível", "Evento", "Condomínio", "Estádio", 
                                "Interno", "Hospital", "Hotel", "Agronomia", "Aeroporto", 
                                "Porto", "Embarcacao", "Cemitério", "Outras"]
            
            tipo_visita = st.selectbox("Tipo de Ação", 
                                      tipo_visita_opcoes, 
                                      key=f"tipo_visita_select_{widget_counter}")
            
            tipo_visita_outros = ""
            if tipo_visita == "Outras":
                tipo_visita_outros = st.text_input(
                    "Especifique o tipo de ação:",
                    placeholder="Digite o tipo de ação personalizado",
                    key=f"tipo_visita_outros_input_{widget_counter}"
                )
                if tipo_visita_outros:
                    tipo_visita = tipo_visita_outros
        
        # Seção 01 - Endereço Empreendimento
        st.markdown("### 01 - ENDEREÇO DO EMPREENDIMENTO")
        st.subheader("Coordenadas do Local")
        
        col_lat, col_lon = st.columns(2)
        with col_lat:
            latitude_input = st.text_input(
                "Latitude *",
                placeholder="Ex: -22.550520",
                key=f"latitude_input_{widget_counter}",
                help="Coordenada de latitude."
            )
        
        with col_lon:
            longitude_input = st.text_input(
                "Longitude *",
                placeholder="Ex: -43.633308",
                key=f"longitude_input_{widget_counter}",
                help="Coordenada de longitude."
            )
        
        st.subheader("Endereço do Empreendimento")
        
        col_endereco, col_numero = st.columns([3, 1])
        with col_endereco:
            endereco = st.text_input("Endereço *",
                                   placeholder="Nome completo do endereço", 
                                   key=f"endereco_input_{widget_counter}")
        with col_numero:
            numero = st.text_input("Nº", 
                                  placeholder="Número ou S/N", 
                                  key=f"numero_input_{widget_counter}")
        
        complemento = st.text_input("Complemento/Referência", placeholder="Ponto de referência ou complemento", 
                                   key=f"complemento_input_{widget_counter}")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            bairro = st.text_input("Bairro", 
                                  placeholder="Nome", 
                                  key=f"bairro_input_{widget_counter}")
        with col2:
            municipio = st.selectbox(
                "Município *",
                options=[""] + sorted(MUNICIPIOS_RJ),
                key=f"municipio_select_{widget_counter}",
                help="Selecione o município do Rio de Janeiro"
            )
        
        with col3:
            st.text_input("UF", 
                         value="RJ", 
                         max_chars=2, 
                         disabled=True,
                         key=f"uf_input_{widget_counter}",
                         help="Estado do Rio de Janeiro",
                         placeholder="RJ")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            cep = st.text_input("CEP", 
                               placeholder="00000-000", 
                               max_chars=9, 
                               key=f"cep_input_{widget_counter}")
        
        with col2:
            descritivo_endereco = st.text_area("Descritivo do Endereço", placeholder="Descrição adicional do endereço", 
                                              key=f"descritivo_endereco_textarea_{widget_counter}")
        
        # Seção 02 - Identificação do Contratante
        st.markdown("### 02 - IDENTIFICAÇÃO DO PROPRIETÁRIO/CONTRATANTE")
        nome_contratante = st.text_input("Nome do Proprietário/Contratante", placeholder="Razão social ou nome completo", 
                                        key=f"nome_contratante_input_{widget_counter}")
        col1, col2 = st.columns(2)
        with col1:
            registro_contratante = st.text_input("Registro", placeholder="Número de registro", 
                                                key=f"registro_contratante_input_{widget_counter}")
        with col2:
            cpf_cnpj = st.text_input("CPF/CNPJ", placeholder="CPF ou CNPJ", 
                                    key=f"cpf_cnpj_input_{widget_counter}")
        
        constatacao_fiscal = st.text_area("Constatação do Fiscal", placeholder="Observações do fiscal", 
                                         key=f"constatacao_fiscal_textarea_{widget_counter}")
        motivo_acao = st.text_area("Motivo da Ação", placeholder="Motivo que originou a fiscalização", 
                                  key=f"motivo_acao_textarea_{widget_counter}")
        
        # Seção 03 - Atividade Desenvolvida
        st.markdown("### 03 - ATIVIDADE DESENVOLVIDA")
        col1, col2 = st.columns(2)
        with col1:
            caracteristica = st.selectbox("Característica", 
                                        ["", "CONSTRUÇÃO", "REFORMA", "AMPLIAÇÃO", "DEMOLIÇÃO", "MANUTENÇÃO", "OUTRAS"], 
                                        key=f"caracteristica_select_{widget_counter}")
            
            if caracteristica == "OUTRAS":
                caracteristica_outras = st.text_input(
                    "Especifique a característica:",
                    placeholder="Digite a característica da atividade",
                    key=f"caracteristica_outras_input_{widget_counter}"
                )
                if caracteristica_outras:
                    caracteristica = caracteristica_outras
            
            fase_atividade = st.selectbox("Fase da Atividade", 
                                       ["", "FUNDAÇÃO", "REVESTIMENTO", "ACABAMENTO", "ESTRUTURA", "LAJE", "OUTRAS"], 
                                       key=f"fase_atividade_select_{widget_counter}")
            
            if fase_atividade == "OUTRAS":
                fase_atividade_outras = st.text_input(
                    "Especifique a fase:",
                    placeholder="Digite a fase da atividade",
                    key=f"fase_atividade_outras_input_{widget_counter}"
                )
                if fase_atividade_outras:
                    fase_atividade = fase_atividade_outras
            
            natureza = st.selectbox("Natureza", ["", "PÚBLICA", "PRIVADA", "MISTA", "OUTRAS"], 
                                   key=f"natureza_select_{widget_counter}")
            
            if natureza == "OUTRAS":
                natureza_outras = st.text_input(
                    "Especifique a natureza:",
                    placeholder="Digite a natureza da obra",
                    key=f"natureza_outras_input_{widget_counter}"
                )
                if natureza_outras:
                    natureza = natureza_outras
                    
        with col2:
            num_pavimentos = st.number_input("Nº de Pavimentos", min_value=0, value=0, 
                                            key=f"num_pavimentos_input_{widget_counter}")
            quantificacao = st.text_input("Quantificação", placeholder="Ex: 5000", 
                                         key=f"quantificacao_input_{widget_counter}")
            unidade_medida = st.selectbox("Unidade de Medida", 
                                        ["", "Metro", "m²", "m³", "UN", "Kg", "TON", "KVA", "Km", "OUTRAS"], 
                                        key=f"unidade_medida_select_{widget_counter}")
            
            if unidade_medida == "OUTRAS":
                unidade_medida_outras = st.text_input(
                    "Especifique a unidade de medida:",
                    placeholder="Digite a unidade de medida",
                    key=f"unidade_medida_outras_input_{widget_counter}"
                )
                if unidade_medida_outras:
                    unidade_medida = unidade_medida_outras
            
            tipo_construcao = st.selectbox("Tipo de Construcao", 
                                         [" ", "ALVENARIA e CONCRETO", "CONCRETO", "ALVENARIA", "METÁLICA", "MISTA", "MADEIRA", "OUTRAS"], 
                                         key=f"tipo_construcao_select_{widget_counter}")
            
            if tipo_construcao == "OUTRAS":
                tipo_construcao_outras = st.text_input(
                    "Especifique o tipo de construção:",
                    placeholder="Digite o tipo de construção",
                    key=f"tipo_construcao_outras_input_{widget_counter}"
                )
                if tipo_construcao_outras:
                    tipo_construcao = tipo_construcao_outras
        
        # Seção 04 - Identificação dos Contratados
        st.markdown("### 04 - IDENTIFICAÇÃO DOS CONTRATADOS, RESPONSÁVEIS TÉCNICOS")
        st.markdown(f"#### 📝 Registro Atual: {st.session_state.registro_counter}")
        
        current_data = st.session_state.current_registro
        
        st.subheader(f"Identificação do Contratante - Registro {st.session_state.registro_counter}")
        st.markdown("**A identificação do Contratante é a mesma do campo 02?**")
        
        col_sim, col_nao = st.columns(2)
        
        with col_sim:
            sim_checkbox = st.checkbox(
                "SIM",
                value=(current_data.get('mesmo_contratante') == "SIM"),
                key=f"mesmo_contratante_sim_{widget_counter}_{secao04_counter}"
            )
        
        with col_nao:
            nao_checkbox = st.checkbox(
                "NÃO",
                value=(current_data.get('mesmo_contratante') == "NÃO"),
                key=f"mesmo_contratante_nao_{widget_counter}_{secao04_counter}"
            )
        
        if sim_checkbox and nao_checkbox:
            if current_data.get('mesmo_contratante') == "SIM":
                nao_checkbox = False
                current_data['mesmo_contratante'] = "SIM"
            else:
                sim_checkbox = False
                current_data['mesmo_contratante'] = "NÃO"
        elif sim_checkbox:
            current_data['mesmo_contratante'] = "SIM"
        elif nao_checkbox:
            current_data['mesmo_contratante'] = "NÃO"
        
        if current_data.get('mesmo_contratante') is None:
            st.warning("⚠️ **Este campo é obrigatório!** Selecione SIM ou NÃO.")
        else:
            st.info(f"**Opção selecionada:** {current_data.get('mesmo_contratante')}")
        
        if current_data.get('mesmo_contratante') == "NÃO":
            st.markdown("**Preencha as informações do Contratante para este registro:**")
            
            col_nome, col_registro, col_cpf = st.columns(3)
            
            with col_nome:
                nome_contratante_secao04 = st.text_input(
                    "Nome do Contratante *",
                    value=current_data.get('nome_contratante_secao04', ''),
                    placeholder="Razão social ou nome completo",
                    key=f"nome_contratante_secao04_input_{widget_counter}_{secao04_counter}"
                )
                current_data['nome_contratante_secao04'] = nome_contratante_secao04
            
            with col_registro:
                registro_contratante_secao04 = st.text_input(
                    "Registro *",
                    value=current_data.get('registro_contratante_secao04', ''),
                    placeholder="Número de registro",
                    key=f"registro_contratante_secao04_input_{widget_counter}_{secao04_counter}"
                )
                current_data['registro_contratante_secao04'] = registro_contratante_secao04
            
            with col_cpf:
                cpf_cnpj_secao04 = st.text_input(
                    "CPF/CNPJ *",
                    value=current_data.get('cpf_cnpj_secao04', ''),
                    placeholder="CPF ou CNPJ",
                    key=f"cpf_cnpj_secao04_input_{widget_counter}_{secao04_counter}"
                )
                current_data['cpf_cnpj_secao04'] = cpf_cnpj_secao04
            
            if (nome_contratante_secao04 == "" or 
                registro_contratante_secao04 == "" or 
                cpf_cnpj_secao04 == ""):
                st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!**")
        else:
            current_data['nome_contratante_secao04'] = ""
            current_data['registro_contratante_secao04'] = ""
            current_data['cpf_cnpj_secao04'] = ""
        
        st.subheader(f"Dados do Contratado/Responsável Técnico - Registro {st.session_state.registro_counter}")
        
        col1, col2 = st.columns(2)
        with col1:
            contratado_pf_pj = st.text_input("Contratado/Responsável Técnico",
                                           value=current_data.get('contratado_pf_pj', ''),
                                           key=f"contratado_pf_pj_{widget_counter}_{secao04_counter}",
                                           placeholder="Nome/Razão Social")
            
            registro = st.text_input("Registro", 
                                   value=current_data.get('registro', ''),
                                   key=f"registro_{widget_counter}_{secao04_counter}",
                                   placeholder="Número de registro")
            
            cpf_cnpj_contratado = st.text_input("CPF/CNPJ", 
                                              value=current_data.get('cpf_cnpj_contratado', ''),
                                              key=f"cpf_cnpj_{widget_counter}_{secao04_counter}",
                                              placeholder="CPF ou CNPJ do contratado")
        
        with col2:
            contrato = st.text_input("Profissional",
                                   value=current_data.get('contrato', ''),
                                   key=f"contrato_{widget_counter}_{secao04_counter}",
                                   placeholder="Nome do profissional")
            
            st.write("Identificação do fiscalizado:")
            identificacao_options = [" ", "Com Placa", "Sem Placa"]
            
            identificacao_fiscalizado = st.selectbox(
                "Selecione a identificação:",
                options=identificacao_options,
                index=identificacao_options.index(current_data.get('identificacao_fiscalizado', ' ')) if current_data.get('identificacao_fiscalizado', ' ') in identificacao_options else 0,
                key=f"identificacao_select_{widget_counter}_{secao04_counter}",
                label_visibility="collapsed"
            )
            
            numero_art = st.text_input("Número ART",
                                     value=current_data.get('numero_art', ''),
                                     key=f"art_{widget_counter}_{secao04_counter}",
                                     placeholder="Número da Anotação de Responsabilidade Técnica")
            
            numero_rrt = st.text_input("Número RRT",
                                     value=current_data.get('numero_rrt', ''),
                                     key=f"rrt_{widget_counter}_{secao04_counter}",
                                     placeholder="Número do Registro de Responsabilidade Técnica")
        
        col3, col4 = st.columns(2)
        with col3:
            numero_trt = st.text_input("Número TRT",
                                     value=current_data.get('numero_trt', ''),
                                     key=f"trt_{widget_counter}_{secao04_counter}",
                                     placeholder="Número do Termo de Responsabilidade Técnica")
            
            st.write("Ramo Atividade:")
            ramo_options = ["", 
                           "1050 - Engª Civil", 
                           "2010 - Engª Elétrica", 
                           "3020 - Engª Mecânica", 
                           "4010 - Arquitetura", 
                           "5010 - Engª Florestal", 
                           "6010 - Geologia", 
                           "7010 - Segurança do Trabalho", 
                           "8010 - Química", 
                           "9010 - Agrimensura"]
            
            ramo_atividade = st.selectbox(
                "Selecione o ramo de atividade:",
                options=ramo_options,
                index=ramo_options.index(current_data.get('ramo_atividade', '')) if current_data.get('ramo_atividade', '') in ramo_options else 0,
                key=f"ramo_select_{widget_counter}_{secao04_counter}",
                label_visibility="collapsed"
            )
        
        with col4:
            st.write("Atividade (Serviço Executado):")
            atividade_options = ["", "Projeto Cálculo Estrutural", 
                               "Execução de Obra", 
                               "Projeto de Construcao", 
                               "Projeto e Execução de Obra", "Outras"]
            
            atividade_servico = st.selectbox(
                "Selecione a atividade:",
                options=atividade_options,
                index=atividade_options.index(current_data.get('atividade_servico', '')) if current_data.get('atividade_servico', '') in atividade_options else 0,
                key=f"atividade_select_{widget_counter}_{secao04_counter}",
                label_visibility="collapsed"
            )
            
            atividade_servico_outras = ""
            if atividade_servico == "Outras":
                atividade_servico_outras = st.text_input(
                    "Especifique a atividade:",
                    placeholder="Digite a atividade personalizada",
                    key=f"atividade_servico_outras_input_{widget_counter}_{secao04_counter}"
                )
                if atividade_servico_outras:
                    atividade_servico = atividade_servico_outras
        
        st.session_state.current_registro = {
            'mesmo_contratante': current_data.get('mesmo_contratante'),
            'nome_contratante_secao04': current_data.get('nome_contratante_secao04', ''),
            'registro_contratante_secao04': current_data.get('registro_contratante_secao04', ''),
            'cpf_cnpj_secao04': current_data.get('cpf_cnpj_secao04', ''),
            'contrato': contrato,
            'registro': registro,
            'cpf_cnpj_contratado': cpf_cnpj_contratado,
            'contratado_pf_pj': contratado_pf_pj,
            'identificacao_fiscalizado': identificacao_fiscalizado,
            'numero_art': numero_art,
            'numero_rrt': numero_rrt,
            'numero_trt': numero_trt,
            'ramo_atividade': ramo_atividade,
            'atividade_servico': atividade_servico
        }
        
        st.markdown("---")
        if st.button("SALVAR", 
                   type="primary", 
                   use_container_width=True,
                   key=f"salvar_registro_button_{widget_counter}_{secao04_counter}"):
            
            if st.session_state.current_registro.get('mesmo_contratante') is None:
                st.error("❌ **Campo obrigatório:** Selecione SIM ou NÃO para a pergunta sobre o contratante")
                st.stop()
            
            if st.session_state.current_registro.get('mesmo_contratante') == "NÃO":
                if (not st.session_state.current_registro.get('nome_contratante_secao04') or
                    not st.session_state.current_registro.get('registro_contratante_secao04') or
                    not st.session_state.current_registro.get('cpf_cnpj_secao04')):
                    st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!")
                    st.stop()
            
            sucesso, total_registros = salvar_registro_atual(st.session_state.current_registro)
            
            if sucesso:
                st.session_state.current_registro = limpar_campos_secao_04()
                st.session_state.registro_counter += 1
                st.session_state.secao04_limpa_counter += 1
                
                st.success(f"✅ Registro {st.session_state.registro_counter - 1} salvo com sucesso!")
                st.info(f"Próximo registro: {st.session_state.registro_counter}")
                st.info("Os campos da seção 04 foram limpos para o próximo registro.")
                
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ Erro ao salvar registro. Tente novamente.")
        
        # Seções 05-06 - Documentos
        st.markdown("### 05 - DOCUMENTOS SOLICITADOS / EXPEDIDOS")
        
        col_doc1, col_doc2 = st.columns(2)
        
        with col_doc1:
            st.subheader("Documentos Solicitados/Expedidos")
            st.markdown("**Oficio:**")
            
            circular_solicitado = st.checkbox("Circular", key=f"circular_solicitado_checkbox_{widget_counter}")
            quadro_tecnico_solicitado = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_solicitado_checkbox_{widget_counter}")
            prestadores_servicos_solicitado = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_solicitado_checkbox_{widget_counter}")
            outros_solicitado = st.checkbox("Outros", key=f"outros_solicitado_checkbox_{widget_counter}")
            
            circular_numero = ""
            if circular_solicitado:
                circular_numero = st.text_input(
                    "Número da Circular:",
                    placeholder="Digite o número da circular",
                    key=f"circular_numero_input_{widget_counter}"
                )
            
            outros_texto_solicitado = ""
            if outros_solicitado:
                outros_texto_solicitado = st.text_input(
                    "Especifique 'Outros':",
                    placeholder="Descreva outros documentos solicitados/expedidos",
                    key=f"outros_solicitado_input_{widget_counter}"
                )
            
            st.markdown("**Detalhes adicionais:**")
            documentos_solicitados_text = st.text_area(
                "",
                value=st.session_state.documentos_solicitados_text,
                placeholder="Informações adicionais sobre documentos solicitados/expedidos",
                key=f"documentos_solicitados_textarea_{widget_counter}",
                height=100,
                label_visibility="collapsed"
            )
            
            st.session_state.documentos_solicitados_text = documentos_solicitados_text
            
        with col_doc2:
            st.markdown("#### 06 - DOCUMENTOS RECEBIDOS")
            st.markdown("**Oficio:**")
            
            circular_recebido = st.checkbox("Circular", key=f"circular_recebido_checkbox_{widget_counter}")
            quadro_tecnico_recebido = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_recebido_checkbox_{widget_counter}")
            prestadores_servicos_recebido = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_recebido_checkbox_{widget_counter}")
            outros_recebido = st.checkbox("Outros", key=f"outros_recebido_checkbox_{widget_counter}")
            
            circular_numero_recebido = ""
            if circular_recebido:
                circular_numero_recebido = st.text_input(
                    "Número da Circular:",
                    placeholder="Digite o número da circular",
                    key=f"circular_numero_recebido_input_{widget_counter}"
                )
            
            quadro_tecnico_quantidade = ""
            if quadro_tecnico_recebido:
                quadro_tecnico_quantidade = st.text_input(
                    "Quantidade (Quadro Técnico):",
                    placeholder="Quantidade",
                    key=f"quadro_tecnico_quantidade_input_{widget_counter}"
                )
            
            prestadores_quantidade = ""
            if prestadores_servicos_recebido:
                prestadores_quantidade = st.text_input(
                    "Quantidade (Prestadores de Serviços Técnicos):",
                    placeholder="Quantidade",
                    key=f"prestadores_quantidade_input_{widget_counter}"
                )
            
            outros_texto_recebido = ""
            if outros_recebido:
                outros_texto_recebido = st.text_input(
                    "Especifique 'Outros':",
                    placeholder="Descreva outros documentos recebidos",
                    key=f"outros_recebido_input_{widget_counter}"
                )
            
            st.markdown("**Detalhes adicionais:**")
            documentos_recebidos_text = st.text_area(
                "",
                value=st.session_state.documentos_recebidos_text,
                placeholder="Informações adicionais sobre documentos recebidos",
                key=f"documentos_recebidos_textarea_{widget_counter}",
                height=100,
                label_visibility="collapsed"
            )
            
            st.session_state.documentos_recebidos_text = documentos_recebidos_text
        
        # Seção 07 - Outras Informações
        st.markdown("### 07 - OUTRAS INFORMAÇÕES")
        data_relatorio_anterior = st.text_input("Data do Relatório Anterior", placeholder="Data do relatório anterior se houver", 
                                               key=f"data_relatorio_anterior_input_{widget_counter}")
        informacoes_complementares = st.text_area("Informações Complementares", 
                                                placeholder="Informações adicionais sobre a fiscalização", 
                                                key=f"informacoes_complementares_textarea_{widget_counter}")
        
        col1, col2 = st.columns(2)
        with col1:
            fonte_informacao = st.text_input("Fonte da Informacao", 
                                           placeholder="Digite a fonte da informação",
                                           key=f"fonte_informacao_input_{widget_counter}",
                                           help="Ex: CONSTATAÇÃO, DOCUMENTO, DENÚNCIA, etc.")
                    
        with col2:
            qualificacao_fonte = st.selectbox("Qualificação da Fonte", 
                                            ["PROPRIETÁRIO", "RESPONSÁVEL TÉCNICO", "MESTRE DE OBRA", "OUTRAS"], 
                                            key=f"qualificacao_fonte_select_{widget_counter}")
            
            if qualificacao_fonte == "OUTRAS":
                qualificacao_fonte_outras = st.text_input(
                    "Especifique a qualificação:",
                    placeholder="Digite a qualificação da fonte",
                    key=f"qualificacao_fonte_outras_input_{widget_counter}"
                )
                if qualificacao_fonte_outras:
                    qualificacao_fonte = qualificacao_fonte_outras
        
        # Seção 08 - Fotos
        st.markdown("### 08 - FOTOS - REGISTRO FOTOGRÁFICO")
        
        if 'temp_photo_bytes' not in st.session_state:
            st.session_state.temp_photo_bytes = None
        
        tab1, tab2, tab3 = st.tabs(["📷 Capturar Fotos", "📁 Upload de Fotos", "📋 Visualizar e Gerenciar"])
        
        with tab1:
            st.subheader("Sistema de Captura de Fotos")
            
            total_fotos = len(st.session_state.fotos_info)
            
            col_stats1, col_stats2, col_stats3 = st.columns(3)
            with col_stats1:
                st.markdown("**Total de Fotos**")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>{total_fotos}</h3>", unsafe_allow_html=True)
            with col_stats2:
                fotos_com_comentarios = sum(1 for foto in st.session_state.fotos_info if foto.comentario.strip())
                st.markdown("**Fotos com Comentarios**")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>{fotos_com_comentarios}</h3>", unsafe_allow_html=True)
            with col_stats3:
                st.markdown("**Última Foto**")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>#{total_fotos}</h3>" if total_fotos > 0 else "<h3 style='text-align: center; font-size: 24px;'>Nenhuma</h3>", unsafe_allow_html=True)
            
            st.markdown("---")
            
            col_cam, col_controls = st.columns([2, 1])
            
            with col_cam:
                camera_picture = st.camera_input(
                    "Aponte a câmera e clique no botão para capturar",
                    key=f"camera_capture_{st.session_state.get('camera_counter', 0)}_{widget_counter}"
                )
                
                if camera_picture is not None:
                    st.session_state.temp_photo_bytes = camera_picture.getvalue()
                    
                    try:
                        img = Image.open(BytesIO(st.session_state.temp_photo_bytes))
                        img.thumbnail((400, 400))
                        st.image(img, caption="Pré-visualização da foto capturada")
                    except:
                        pass
            
            with col_controls:
                st.write("**Controles da Foto**")
                
                novo_comentario = st.text_area(
                    "Comentário para esta foto:",
                    max_chars=200,
                    height=100,
                    key=f"novo_comentario_input_{widget_counter}",
                    placeholder="Digite um comentário para esta foto..."
                )
                
                chars_used = len(novo_comentario)
                st.caption(f"Caracteres: {chars_used}/200")
                
                col_save1, col_save2 = st.columns(2)
                with col_save1:
                    if st.button("💾 Salvar Foto", 
                               use_container_width=True,
                               disabled=st.session_state.temp_photo_bytes is None,
                               key=f"salvar_foto_button_{widget_counter}"):
                        
                        foto_existe = False
                        for foto in st.session_state.fotos_info:
                            if foto.image_bytes == st.session_state.temp_photo_bytes:
                                foto_existe = True
                                break
                        
                        if not foto_existe:
                            nova_foto = FotoInfo(
                                image_bytes=st.session_state.temp_photo_bytes,
                                comentario=novo_comentario
                            )
                            st.session_state.fotos_info.append(nova_foto)
                            
                            st.session_state.temp_photo_bytes = None
                            st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
                            
                            st.success(f"✅ Foto {len(st.session_state.fotos_info)} salva com sucesso!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.warning("Esta foto já foi adicionada ao relatório.")
                
                with col_save2:
                    if st.button("🔄 Nova Foto", 
                               use_container_width=True,
                               key=f"nova_foto_button_{widget_counter}"):
                        st.session_state.temp_photo_bytes = None
                        st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
                        st.rerun()
        
        with tab2:
            st.subheader("Upload de Fotos Existentes")
            
            uploaded_files = st.file_uploader(
                "Selecione fotos do seu dispositivo (múltiplas permitidas)",
                type=['jpg', 'jpeg', 'png', 'heic'],
                accept_multiple_files=True,
                key=f"photo_uploader_multiple_{widget_counter}"
            )
            
            if uploaded_files:
                st.write(f"**{len(uploaded_files)} foto(s) selecionada(s)**")
                
                cols = st.columns(4)
                for i, uploaded_file in enumerate(uploaded_files):
                    with cols[i % 4]:
                        try:
                            img = Image.open(uploaded_file)
                            img.thumbnail((100, 100))
                            st.image(img, caption=f"Foto {i+1}")
                        except:
                            st.write(f"Arquivo {i+1}")
                
                upload_comentario = st.text_area(
                    "Comentário para todas as fotos (opcional):",
                    max_chars=200,
                    height=80,
                    key=f"upload_comentario_geral_{widget_counter}",
                    placeholder="Este comentário será aplicado a todas as fotos..."
                )
                
                col_process1, col_process2 = st.columns(2)
                
                with col_process1:
                    if st.button("📤 Adicionar Todas as Fotos", 
                               type="primary", 
                               use_container_width=True,
                               key=f"adicionar_todas_fotos_{widget_counter}"):
                        
                        fotos_adicionadas = 0
                        for uploaded_file in uploaded_files:
                            try:
                                img_bytes = uploaded_file.getvalue()
                                
                                foto_existe = False
                                for foto in st.session_state.fotos_info:
                                    if foto.image_bytes == img_bytes:
                                        foto_existe = True
                                        break
                                
                                if not foto_existe:
                                    nova_foto = FotoInfo(
                                        image_bytes=img_bytes,
                                        comentario=upload_comentario
                                    )
                                    st.session_state.fotos_info.append(nova_foto)
                                    fotos_adicionadas += 1
                            except Exception as e:
                                st.error(f"Erro ao processar arquivo: {e}")
                        
                        if fotos_adicionadas > 0:
                            st.success(f"✅ {fotos_adicionadas} foto(s) adicionada(s) com sucesso!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.warning("Todas as fotos selecionadas já estão no relatório.")
                
                with col_process2:
                    if st.button("🗑️ Limpar Seleção", 
                               type="secondary",
                               use_container_width=True,
                               key=f"limpar_selecao_upload_{widget_counter}"):
                        st.rerun()
        
        with tab3:
            st.subheader("Visualizar e Gerenciar Fotos")
            
            total_fotos = len(st.session_state.fotos_info)
            
            if total_fotos == 0:
                st.warning("Nenhuma foto registrada ainda.")
                st.info("Use as abbas '📷 Capturar Fotos' ou '📁 Upload de Fotos' para adicionar fotos.")
            else:
                st.success(f"✅ **Total de fotos no relatório: {total_fotos}**")
                
                if total_fotos > 20:
                    st.info(f"⚠️ Muitas fotos ({total_fotos}). Mostrando apenas as primeiras 20.")
                    fotos_exibidas = st.session_state.fotos_info[:20]
                else:
                    fotos_exibidas = st.session_state.fotos_info
                
                current_foto_idx = st.session_state.current_foto_index
                if current_foto_idx >= len(fotos_exibidas):
                    current_foto_idx = 0
                
                col_nav, col_info = st.columns([3, 1])
                
                with col_nav:
                    col_prev, col_counter, col_next = st.columns([1, 2, 1])
                    
                    with col_prev:
                        if st.button("⬅️ Anterior", 
                                   disabled=current_foto_idx == 0,
                                   use_container_width=True,
                                   key=f"nav_anterior_gestao_{widget_counter}"):
                            st.session_state.current_foto_index = max(0, current_foto_idx - 1)
                            st.rerun()
                    
                    with col_counter:
                        st.markdown(f"### Foto {current_foto_idx + 1} de {len(fotos_exibidas)}")
                    
                    with col_next:
                        if st.button("Próxima ➡️",
                                   disabled=current_foto_idx == len(fotos_exibidas) - 1,
                                   use_container_width=True,
                                   key=f"nav_proxima_gestao_{widget_counter}"):
                            st.session_state.current_foto_index = min(len(fotos_exibidas) - 1, current_foto_idx + 1)
                            st.rerun()
                
                with col_info:
                    st.write("**Ações:**")
                    
                    if st.button("🗑️ Remover",
                               type="secondary",
                               use_container_width=True,
                               key=f"remover_foto_atual_gestao_{widget_counter}"):
                        if 0 <= current_foto_idx < total_fotos:
                            st.session_state.fotos_info.pop(current_foto_idx)
                            st.session_state.current_foto_index = max(0, min(current_foto_idx, total_fotos - 2))
                            st.success("Foto removida com sucesso!")
                            time.sleep(0.3)
                            st.rerun()
                
                st.markdown("---")
                foto_atual = fotos_exibidas[current_foto_idx]
                
                col_foto, col_comentario = st.columns([2, 1])
                
                with col_foto:
                    try:
                        img = foto_atual.get_thumbnail(size=(600, 400))
                        st.image(img, caption=f"Foto {current_foto_idx + 1} - Preview")
                    except Exception as e:
                        st.error(f"Erro ao carregar foto: {e}")
                
                with col_comentario:
                    st.write("**Comentário:**")
                    
                    comentario_edit = st.text_area(
                        "Editar comentário:",
                        value=foto_atual.comentario,
                        max_chars=200,
                        height=150,
                        key=f"comentario_edit_{current_foto_idx}_{widget_counter}",
                        label_visibility="collapsed"
                    )
                    
                    chars_used = len(comentario_edit)
                    chars_left = 100 - chars_used
                    st.caption(f"Caracteres: {chars_used}/100 ({chars_left} restantes)")
                    
                    if st.button("💾 Salvar Comentário", 
                               use_container_width=True,
                               key=f"salvar_comentario_edit_{current_foto_idx}_{widget_counter}"):
                        if comentario_edit != foto_atual.comentario:
                            st.session_state.fotos_info[current_foto_idx].comentario = comentario_edit
                            st.success("Comentário atualizado com sucesso!")
                            time.sleep(0.3)
                            st.rerun()
                
                st.markdown("---")
                st.subheader("Todas as Fotos (Thumbnails)")
                
                cols = st.columns(4)
                for i, foto in enumerate(fotos_exibidas):
                    with cols[i % 4]:
                        try:
                            img = foto.get_thumbnail(size=(120, 120))
                            indicador_atual = "📍" if i == current_foto_idx else ""
                            indicador_comentario = "📝" if foto.comentario else "📄"
                            
                            st.image(img, caption=f"{indicador_atual} Foto {i+1} {indicador_comentario}")
                            
                            if st.button(f"Selecionar #{i+1}", 
                                       key=f"select_thumb_{i}_{widget_counter}",
                                       use_container_width=True):
                                st.session_state.current_foto_index = i
                                st.rerun()
                        except:
                            st.error(f"Erro na foto {i+1}")
        
        # Botões de ação
        st.markdown("---")
        col_gerar1, col_gerar2, col_gerar3 = st.columns([1, 1, 1])
        
        # Botão GERAR RELATÓRIO PDF
        with col_gerar1:
            if st.button("📄 GERAR RELATÓRIO PDF", 
                       type="primary", 
                       use_container_width=True,
                       key=f"gerar_relatorio_final_{widget_counter}"):
                
                # Validar campos obrigatórios
                if not latitude_input or not longitude_input:
                    st.error("❌ Campos obrigatórios: Latitude e Longitude devem ser preenchidos")
                    st.stop()
                
                if not endereco:
                    st.error("❌ Campo obrigatório: Endereço deve ser preenchido")
                    st.stop()
                
                if not municipio:
                    st.error("❌ Campo obrigatório: Município deve ser selecionado")
                    st.stop()
                
                # Salvar automaticamente o último registro se tiver dados
                current_registro = st.session_state.current_registro
                tem_dados_atuais = False
                
                for key, value in current_registro.items():
                    if value and key != 'identificacao_fiscalizado':
                        tem_dados_atuais = True
                        break
                
                if tem_dados_atuais:
                    if current_registro.get('mesmo_contratante') is None:
                        st.error("❌ **Campo obrigatório:** Selecione SIM ou NÃO para a pergunta sobre o contratante")
                        st.stop()
                    
                    if current_registro.get('mesmo_contratante') == "NÃO":
                        if (not current_registro.get('nome_contratante_secao04') or
                            not current_registro.get('registro_contratante_secao04') or
                            not current_registro.get('cpf_cnpj_secao04')):
                            st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!")
                            st.stop()
                    
                    sucesso, total_registros = salvar_registro_atual(current_registro)
                    
                    if sucesso:
                        st.success(f"✅ Último registro salvo automaticamente!")
                        st.session_state.current_registro = limpar_campos_registro()
                    else:
                        st.error("❌ Erro ao salvar o último registro automaticamente")
                
                total_fotos = len(st.session_state.fotos_info)
                
                if total_fotos == 0:
                    st.warning("⚠️ Nenhuma foto adicionada ao relatório.")
                    if not st.checkbox("Continuar sem fotos", key=f"continuar_sem_fotos_{widget_counter}"):
                        st.stop()
                
                # Construir string de documentos solicitados
                documentos_solicitados_list = []
                oficio_header = "Ofício: "
                tipos_documentos = []
                
                if circular_solicitado:
                    if circular_numero:
                        tipos_documentos.append(f"Circular nº {circular_numero}")
                    else:
                        tipos_documentos.append("Circular")
                
                if quadro_tecnico_solicitado:
                    tipos_documentos.append("Quadro Técnico")
                
                if prestadores_servicos_solicitado:
                    tipos_documentos.append("Prestadores de Serviços Técnicos")
                
                if outros_solicitado:
                    if outros_texto_solicitado:
                        tipos_documentos.append(f"Outros {outros_texto_solicitado}")
                    else:
                        tipos_documentos.append("Outros")
                
                if tipos_documentos:
                    documentos_solicitados_list.append(oficio_header + " | ".join(tipos_documentos))
                
                if documentos_solicitados_text:
                    documentos_solicitados_list.append(documentos_solicitados_text)
                
                if documentos_solicitados_list:
                    documentos_solicitados = " | ".join(documentos_solicitados_list)
                else:
                    documentos_solicitados = "SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS"
                
                # Construir string de documentos recebidos
                documentos_recebidos_list = []
                oficio_header_recebido = "Ofício: "
                tipos_documentos_recebidos = []
                
                if circular_recebido:
                    if circular_numero_recebido:
                        tipos_documentos_recebidos.append(f"Circular nº {circular_numero_recebido}")
                    else:
                        tipos_documentos_recebidos.append("Circular")
                
                if quadro_tecnico_recebido:
                    if quadro_tecnico_quantidade:
                        tipos_documentos_recebidos.append(f"Quadro Técnico - Quantidade: {quadro_tecnico_quantidade}")
                    else:
                        tipos_documentos_recebidos.append("Quadro Técnico")
                
                if prestadores_servicos_recebido:
                    if prestadores_quantidade:
                        tipos_documentos_recebidos.append(f"Prestadores de Serviços Técnicos - Quantidade: {prestadores_quantidade}")
                    else:
                        tipos_documentos_recebidos.append("Prestadores de Serviços Técnicos")
                
                if outros_recebido:
                    if outros_texto_recebido:
                        tipos_documentos_recebidos.append(f"Outros {outros_texto_recebido}")
                    else:
                        tipos_documentos_recebidos.append("Outros")
                
                if tipos_documentos_recebidos:
                    documentos_recebidos_list.append(oficio_header_recebido + " | ".join(tipos_documentos_recebidos))
                
                if documentos_recebidos_text:
                    documentos_recebidos_list.append(documentos_recebidos_text)
                
                if documentos_recebidos_list:
                    documentos_recebidos = " | ".join(documentos_recebidos_list)
                else:
                    documentos_recebidos = "SEM DOCUMENTOS RECEBIDOS"
                
                # Coletar todos os dados
                dados = {
                    'numero_relatorio': st.session_state.numero_relatorio_gerado,
                    'situacao': situacao,
                    'data_relatorio': data_relatorio.strftime('%d/%m/%Y'),
                    'fato_gerador': fato_gerador,
                    'protocolo': protocolo,
                    'tipo_visita': tipo_visita,
                    'latitude': latitude_input,
                    'longitude': longitude_input,
                    'endereco': endereco,
                    'numero': numero,
                    'complemento': complemento,
                    'bairro': bairro,
                    'municipio': municipio,
                    'uf': "RJ",
                    'cep': cep,
                    'descritivo_endereco': descritivo_endereco,
                    'nome_contratante': nome_contratante,
                    'registro_contratante': registro_contratante,
                    'cpf_cnpj': cpf_cnpj,
                    'constatacao_fiscal': constatacao_fiscal,
                    'motivo_acao': motivo_acao,
                    'caracteristica': caracteristica,
                    'fase_atividade': fase_atividade,
                    'num_pavimentos': str(num_pavimentos),
                    'quantificacao': quantificacao,
                    'unidade_medida': unidade_medida,
                    'natureza': natureza,
                    'tipo_construcao': tipo_construcao,
                    'contratados_data': st.session_state.contratados_data,
                    'documentos_solicitados': documentos_solicitados,
                    'documentos_recebidos': documentos_recebidos,
                    'data_relatorio_anterior': data_relatorio_anterior or "NAO INFORMADO",
                    'informacoes_complementares': informacoes_complementares,
                    'fonte_informacao': fonte_informacao,
                    'qualificacao_fonte': qualificacao_fonte,
                }
                
                try:
                    # Mostrar progresso
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    status_text.text("🔄 Preparando dados...")
                    progress_bar.progress(10)
                    
                    # Criar PDF
                    status_text.text("📄 Criando PDF...")
                    pdf = criar_pdf(dados, logo_data, 
                                  st.session_state.fotos_info, st.session_state.agente_info)
                    progress_bar.progress(40)
                    
                    # Salvar em arquivo temporário
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                        temp_file_path = temp_file.name
                    
                    status_text.text("💾 Salvando PDF...")
                    pdf.output(temp_file_path)
                    progress_bar.progress(70)
                    
                    # ========== GOOGLE DRIVE UPLOAD ==========
                    st.subheader("☁️ Armazenamento em Nuvem (Google Drive)")
                    
                    col_drive1, col_drive2 = st.columns(2)
                    with col_drive1:
                        upload_drive = st.checkbox(
                            "Enviar para Google Drive",
                            value=True,
                            key=f"upload_drive_checkbox_{widget_counter}",
                            help="Envie uma cópia do relatório para a nuvem"
                        )
                    
                    drive_resultado = None
                    drive_info = None
                    
                    if upload_drive:
                        if GOOGLE_DRIVE_FOLDER_ID and GOOGLE_DRIVE_FOLDER_ID != "seu-folder-id-aqui":
                            status_text.text("🔐 Conectando ao Google Drive...")
                            drive_service = autenticar_google_drive()
                            
                            if drive_service:
                                status_text.text("📤 Enviando PDF para a nuvem...")
                                pdf_nome_arquivo = f"relatorio_{st.session_state.numero_relatorio_gerado}.pdf"
                                drive_info = upload_para_google_drive(
                                    caminho_arquivo=temp_file_path,
                                    nome_arquivo=pdf_nome_arquivo,
                                    service=drive_service,
                                    folder_id=GOOGLE_DRIVE_FOLDER_ID
                                )
                                
                                if drive_info:
                                    drive_resultado = True
                                    progress_bar.progress(80)
                                    status_text.text("✅ PDF enviado para o Google Drive!")
                                    
                                    # Salvar link no session_state
                                    st.session_state.drive_link = drive_info.get('link_visualizacao', '')
                                    
                                    tamanho_mb = drive_info['tamanho_bytes'] / (1024 * 1024)
                                    
                                    st.markdown(f"""
                                    <div style="
                                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                        padding: 25px;
                                        border-radius: 15px;
                                        color: white;
                                        margin: 20px 0;
                                        text-align: center;
                                        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
                                    ">
                                        <h3 style="margin-top: 0;">📁 RELATÓRIO SALVO NA NUVEM!</h3>
                                        <p style="font-size: 16px; margin: 10px 0;">
                                            <strong>Nome:</strong> {drive_info['nome']}<br>
                                            <strong>Tamanho:</strong> {tamanho_mb:.2f} MB<br>
                                            <strong>Ação:</strong> {drive_info.get('acao', 'ENVIADO')}
                                        </p>
                                        <a href="{drive_info['link_visualizacao']}" target="_blank" style="
                                            display: inline-block;
                                            background: white;
                                            color: #667eea;
                                            padding: 12px 25px;
                                            border-radius: 50px;
                                            text-decoration: none;
                                            font-weight: bold;
                                            font-size: 16px;
                                            margin: 10px 0;
                                            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
                                        ">
                                           🔗 ABRIR NO GOOGLE DRIVE
                                        </a>
                                        <p style="font-size: 14px; opacity: 0.9; margin-top: 10px;">
                                            Clique no botão acima para visualizar ou baixar
                                        </p>
                                    </div>
                                    """, unsafe_allow_html=True)
                                else:
                                    drive_resultado = False
                                    st.warning("⚠️ Não foi possível enviar PDF para o Google Drive.")
                            else:
                                st.warning("⚠️ Serviço do Google Drive não disponível.")
                                drive_resultado = False
                        else:
                            st.warning("⚠️ ID da pasta do Google Drive não configurado corretamente.")
                            st.info("Configure o GOOGLE_DRIVE_FOLDER_ID no secrets do Streamlit.")
                            drive_resultado = False
                    
                    # ========== GOOGLE SHEETS SAVE ==========
                    status_text.text("📊 Salvando dados no Google Sheets...")
                    
                    # Preparar dados para salvar no Google Sheets
                    dados_para_sheets = dados.copy()
                    dados_para_sheets['numero_relatorio'] = st.session_state.numero_relatorio_gerado
                    
                    # Chamar função para salvar no Google Sheets
                    sheets_sucesso = salvar_relatorio_google_sheets(
                        dados_para_sheets, 
                        temp_file_path
                    )
                    
                    if sheets_sucesso:
                        progress_bar.progress(90)
                        status_text.text("✅ Dados salvos no Google Sheets!")
                    else:
                        st.warning("⚠️ Não foi possível salvar dados no Google Sheets.")
                    
                    # Ler bytes do PDF para download local
                    status_text.text("📥 Preparando download...")
                    with open(temp_file_path, "rb") as f:
                        pdf_bytes = f.read()
                    
                    progress_bar.progress(100)
                    status_text.text("✅ Relatório pronto!")
                    
                    # Nome do arquivo
                    nome_arquivo = f"relatorio_{st.session_state.numero_relatorio_gerado}.pdf"
                    
                    # Criar link para download local
                    b64 = base64.b64encode(pdf_bytes).decode()
                    href = f'''
                    <a href="data:application/octet-stream;base64,{b64}" 
                       download="{nome_arquivo}" 
                       style="background-color: #4CAF50; 
                              color: white; 
                              padding: 14px 25px; 
                              text-align: center; 
                              text-decoration: none; 
                              display: inline-block;
                              border-radius: 8px;
                              font-size: 16px;
                              font-weight: bold;
                              width: 100%;
                              display: block;
                              margin-top: 15px;">
                       📥 BAIXAR RELATÓRIO COMPLETO (LOCAL)
                    </a>
                    '''
                    st.markdown(href, unsafe_allow_html=True)
                    
                    # Resumo final
                    fotos_com_comentarios = sum(1 for foto in st.session_state.fotos_info if foto.comentario.strip())
                    total_registros = len(st.session_state.contratados_data)
                    
                    # Formatar número do relatório para exibição
                    numero_formatado = st.session_state.numero_relatorio_gerado
                    if numero_formatado:
                        ano = numero_formatado[:4]
                        mat = numero_formatado[4:8]
                        seq = numero_formatado[8:]
                        numero_display = f"{ano}.{mat}.{seq}"
                    else:
                        numero_display = st.session_state.numero_relatorio_gerado
                    
                    resumo_texto = f"""
                    **📊 Resumo Final:**
                    - **Número do relatório:** {numero_display}
                    - **Agente:** {st.session_state.agente_info['NOME'] if st.session_state.agente_info else 'N/A'}
                    - **Total de fotos:** {total_fotos}
                    - **Fotos com comentários:** {fotos_com_comentarios}
                    - **Registros de contratados:** {total_registros}
                    - **Tamanho do PDF:** {len(pdf_bytes) // 1024} KB
                    """
                    
                    if drive_resultado:
                        resumo_texto += f"\n- **☁️ Google Drive:** PDF enviado com sucesso!"
                    elif drive_resultado is False:
                        resumo_texto += "\n- **⚠️ Google Drive:** Falha no envio (apenas armazenamento local)"
                    else:
                        resumo_texto += "\n- **📍 Armazenamento:** Apenas local (Google Drive não selecionado)"
                    
                    if sheets_sucesso:
                        resumo_texto += "\n- **📊 Google Sheets:** Dados salvos com sucesso!"
                    else:
                        resumo_texto += "\n- **⚠️ Google Sheets:** Dados não salvos"
                    
                    st.info(resumo_texto)
                    
                    progress_bar.empty()
                    status_text.empty()
                    
                except Exception as e:
                    st.error(f"❌ Erro ao gerar relatório: {str(e)}")
                    import traceback
                    st.error(traceback.format_exc())
                    if 'progress_bar' in locals():
                        progress_bar.empty()
                    if 'status_text' in locals():
                        status_text.empty()
                finally:
                    # Limpar arquivo temporário
                    if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except:
                            pass
        
        # Botão para NOVO RELATÓRIO
        with col_gerar2:
            if st.button("🔄 NOVO RELATÓRIO", 
                       type="secondary",
                       use_container_width=True,
                       key=f"novo_relatorio_button_{widget_counter}"):
                # Gerar novo número de relatório
                novo_numero = contador_manager.gerar_numero_relatorio(st.session_state.matricula)
                st.session_state.numero_relatorio_gerado = novo_numero
                
                # Limpar completamente o formulário
                limpar_formulario()
                
                # Resetar flag de formulário inicializado
                st.session_state.formulario_inicializado = False
                
                # Reiniciar contador de registros
                st.session_state.registro_counter = 1
                st.session_state.current_registro = limpar_campos_registro()
                st.session_state.contratados_data = []
                
                # Reiniciar contador para limpar seção 04
                st.session_state.secao04_limpa_counter = 0
                
                # Limpar link do Google Drive
                st.session_state.drive_link = ""
                
                # Incrementar o contador de widgets
                st.session_state.form_widget_counter += 1
                
                st.success(f"✅ Novo relatório iniciado: {novo_numero}")
                st.info("Todos os campos foram limpos. Você pode começar um novo registro.")
                time.sleep(1)
                st.rerun()
        
        # Botão para LIMPAR FORMULÁRIO
        with col_gerar3:
            if st.button("🗑️ LIMPAR FORMULÁRIO", 
                       type="secondary",
                       use_container_width=True,
                       key=f"limpar_formulario_button_{widget_counter}"):
                # Limpar formulário mantendo o mesmo número de relatório
                limpar_formulario()
                st.session_state.formulario_inicializado = False
                
                # Reiniciar contador de registros
                st.session_state.registro_counter = 1
                st.session_state.current_registro = limpar_campos_registro()
                st.session_state.contratados_data = []
                
                # Reiniciar contador para limpar seção 04
                st.session_state.secao04_limpa_counter = 0
                
                # Limpar link do Google Drive
                st.session_state.drive_link = ""
                
                # Incrementar o contador de widgets
                st.session_state.form_widget_counter += 1
                
                st.success("✅ Formulário limpo! Mantendo o mesmo número de relatório.")
                st.info("Todos os campos foram limpos. Você pode preencher novamente.")
                time.sleep(0.5)
                st.rerun()

    # ========== OUTROS MÓDULOS (EM DESENVOLVIMENTO) ==========
    elif opcao == "EMPRESA":
        st.title("Cadastro de Empresa")
        st.info("📋 Módulo em desenvolvimento para cadastro de empresas.")
        
    elif opcao == "EVENTOS":
        st.title("Registro de Eventos")
        st.info("🎯 Módulo em desenvolvimento para registro de eventos.")
        
    elif opcao == "AGRONOMIA":
        st.title("Histórico de Relatórios")
        st.info("📊 Módulo em desenvolvimento para consulta de relatórios históricos.")

if __name__ == "__main__":
    main()