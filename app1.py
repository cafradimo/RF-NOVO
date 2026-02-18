import streamlit as st
import pandas as pd
from fpdf import FPDF
import base64
from io import BytesIO
from PIL import Image, ImageFilter, ImageEnhance
import os
import tempfile
from datetime import datetime
import json
import re
import time
import uuid
import pickle
import shutil

from pathlib import Path

# ========== IMPORTAÇÕES DO GOOGLE DRIVE ==========
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

# Configuração inicial da página
st.set_page_config(
    page_title="Relatório de Fiscalização",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== CONFIGURAÇÃO GOOGLE DRIVE ==========
SCOPES = ['https://www.googleapis.com/auth/drive']
GOOGLE_DRIVE_FOLDER_ID = "119n021EjT2ilcc7ajUejGLv7mk7Gz8GI"
SHARED_DRIVE_ID = "0AExAXm3UxqZFUk9PVA"
EXCEL_DATABASE_NAME = "Planilha Master.xlsx"
CONTADOR_FILENAME = "contador_relatorios.json"

# ========== FUNÇÃO PARA DETECTAR AMBIENTE ==========
def is_streamlit_cloud():
    """Detecta se está rodando no Streamlit Cloud"""
    return os.getenv('STREAMLIT_SHARING_MODE') is not None or os.getenv('STREAMLIT_SERVER_RUN_ON_SAVE') is not None

# ========== NOVA FUNÇÃO PARA GERENCIAR PASTA LOCAL ==========
def get_pasta_local(matricula):
    """
    Versão adaptada para funcionar em ambos ambientes:
    - Local: Cria pasta em Documents
    - Cloud: Cria pasta temporária (será usada apenas para processamento)
    """
    if is_streamlit_cloud():
        # No Streamlit Cloud, usa pasta temporária
        temp_dir = tempfile.gettempdir()
        nome_pasta = f"RF-CREA-RJ-{matricula}"
        caminho_pasta = os.path.join(temp_dir, nome_pasta)
        
        # Cria a pasta se não existir
        os.makedirs(caminho_pasta, exist_ok=True)
        
        return caminho_pasta
    else:
        # No ambiente local, usa a pasta Documents
        home = str(Path.home())
        possiveis_caminhos = [
            os.path.join(home, 'Documents'),
            os.path.join(home, 'Documentos'),
            os.path.join(home, 'Meus Documentos'),
            home
        ]
        
        caminho_base = None
        for caminho in possiveis_caminhos:
            if os.path.exists(caminho):
                caminho_base = caminho
                break
        
        if caminho_base is None:
            caminho_base = home
        
        nome_pasta = f"RF-CREA-RJ-{matricula}"
        caminho_pasta = os.path.join(caminho_base, nome_pasta)
        
        # Cria a pasta se não existir
        os.makedirs(caminho_pasta, exist_ok=True)
        
        return caminho_pasta

# ========== FUNÇÃO PARA DISPONIBILIZAR PDF ==========
def disponibilizar_pdf_para_download(caminho_arquivo, nome_arquivo):
    """
    Disponibiliza o PDF para download e mostra instruções
    """
    try:
        with open(caminho_arquivo, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
        
        # Botão de download
        st.download_button(
            label="📥 BAIXAR PDF",
            data=pdf_bytes,
            file_name=nome_arquivo,
            mime="application/pdf",
            key=f"download_{datetime.now().timestamp()}",
            use_container_width=True
        )
        
        # Instruções baseadas no ambiente
        if is_streamlit_cloud():
            st.info("""
            💡 **Como salvar na pasta Documents:**
            1. Clique no botão **BAIXAR PDF** acima
            2. Na janela de download, navegue até **Documentos** (Documents)
            3. Crie a pasta **RF-CREA-RJ-MATRICULA** se necessário
            4. Salve o arquivo dentro desta pasta
            """)
        else:
            st.success(f"📁 PDF também salvo em: {caminho_arquivo}")
        
        return True
    except Exception as e:
        st.error(f"❌ Erro ao disponibilizar PDF: {e}")
        return False

# ========== FUNÇÃO PARA SALVAR PDF (ADAPTADA) ==========
def salvar_pdf_adaptado(pdf, matricula, numero_relatorio):
    """
    Salva o PDF de forma adaptada ao ambiente:
    - Local: Salva na pasta Documents e disponibiliza download
    - Cloud: Salva em pasta temporária e disponibiliza download
    """
    try:
        # Obtém a pasta local (adaptada ao ambiente)
        pasta_local = get_pasta_local(matricula)
        
        # Nome do arquivo
        nome_arquivo = f"relatorio_{numero_relatorio}.pdf"
        caminho_completo = os.path.join(pasta_local, nome_arquivo)
        
        # Salva o PDF
        pdf.output(caminho_completo)
        
        # Verifica se o arquivo foi criado
        if os.path.exists(caminho_completo):
            st.success(f"✅ PDF gerado: {nome_arquivo}")
            
            # Disponibiliza para download
            disponibilizar_pdf_para_download(caminho_completo, nome_arquivo)
            
            return caminho_completo
        else:
            st.error("❌ Erro ao salvar o PDF")
            return None
            
    except Exception as e:
        st.error(f"❌ Erro ao salvar PDF: {e}")
        return None

# ========== FUNÇÃO DE AUTENTICAÇÃO PARA DRIVE COMPARTILHADO ==========
def autenticar_google_drive():
    """
    Autentica no Google Drive com suporte a:
    - OAuth 2.0 (ambiente local)
    - Service Account (Streamlit Cloud)
    - Drives compartilhados
    """
    
    if is_streamlit_cloud():
        return autenticar_service_account()
    else:
        return autenticar_oauth_local()

def autenticar_service_account():
    """Autenticação via Service Account para Streamlit Cloud"""
    try:
        if 'google_drive' not in st.secrets:
            st.sidebar.error("❌ Configuração 'google_drive' não encontrada nos secrets!")
            return None
        
        credentials_dict = st.secrets["google_drive"]["credentials"]
        
        if isinstance(credentials_dict, str):
            try:
                credentials_dict = json.loads(credentials_dict)
            except json.JSONDecodeError:
                st.sidebar.error("❌ Erro ao fazer parse das credentials JSON")
                return None
        
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=credentials)
        
        try:
            results = service.files().list(
                q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                driveId=SHARED_DRIVE_ID,
                corpora='drive',
                pageSize=10
            ).execute()
            
            files = results.get('files', [])
            return service
            
        except HttpError as e:
            st.sidebar.error(f"❌ Erro ao acessar Drive Compartilhado: {e}")
            return None
                
    except Exception as e:
        st.sidebar.error(f"❌ Erro na autenticação Service Account: {str(e)}")
        return None

def autenticar_oauth_local():
    """Autenticação OAuth 2.0 para ambiente local"""
    creds = None
    
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception as e:
            creds = None
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                creds = None
        
        if not creds:
            if not os.path.exists('credentials.json'):
                st.sidebar.error("❌ Arquivo credentials.json não encontrado!")
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', 
                    SCOPES,
                    redirect_uri='http://localhost:8501'
                )
                
                creds = flow.run_local_server(
                    port=0,
                    authorization_prompt_message='Por favor, autorize o acesso ao Google Drive',
                    success_message='✅ Autenticação realizada com sucesso!',
                    open_browser=True
                )
            except Exception as e:
                st.sidebar.error(f"❌ Erro na autenticação: {str(e)}")
                return None
        
        try:
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            pass
    
    try:
        service = build('drive', 'v3', credentials=creds)
        
        results = service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=10
        ).execute()
        
        files = results.get('files', [])
        return service
        
    except HttpError as e:
        st.sidebar.error(f"❌ Erro ao acessar Drive: {e}")
        return None
    except Exception as e:
        st.sidebar.error(f"❌ Erro ao criar serviço do Drive: {str(e)}")
        return None

# ========== FUNÇÕES DO GOOGLE DRIVE ==========
def upload_para_google_drive(caminho_arquivo, nome_arquivo, service, folder_id=None):
    """Upload com suporte a drives compartilhados"""
    try:
        if not os.path.exists(caminho_arquivo):
            return None
        
        extensao = os.path.splitext(nome_arquivo)[1].lower()
        mimetypes = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.json': 'application/json'
        }
        mimetype = mimetypes.get(extensao, 'application/octet-stream')
        
        drive_params = {
            'supportsAllDrives': True
        }
        
        if is_streamlit_cloud():
            drive_params['driveId'] = SHARED_DRIVE_ID
        
        query = f"name = '{nome_arquivo}' and trashed = false"
        if folder_id:
            query = f"name = '{nome_arquivo}' and '{folder_id}' in parents and trashed = false"
        
        list_params = {
            'q': query,
            'spaces': 'drive',
            'fields': 'files(id, name, parents)',
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True
        }
        
        if is_streamlit_cloud():
            list_params['corpora'] = 'drive'
            list_params['driveId'] = SHARED_DRIVE_ID
        
        results = service.files().list(**list_params).execute()
        arquivos = results.get('files', [])
        
        file_metadata = {'name': nome_arquivo}
        
        upload_params = {
            'body': file_metadata,
            'media_body': MediaFileUpload(caminho_arquivo, mimetype=mimetype, resumable=True),
            'fields': 'id, name, webViewLink, webContentLink, size, createdTime, modifiedTime',
            'supportsAllDrives': True
        }
        
        if is_streamlit_cloud():
            upload_params['enforceSingleParent'] = True
        
        if arquivos:
            file_id = arquivos[0]['id']
            
            file = service.files().update(
                fileId=file_id,
                **upload_params
            ).execute()
            
            current_parents = arquivos[0].get('parents', [])
            if folder_id and folder_id not in current_parents:
                move_params = {
                    'fileId': file_id,
                    'addParents': folder_id,
                    'removeParents': ','.join(current_parents),
                    'fields': 'id, parents',
                    'supportsAllDrives': True
                }
                if is_streamlit_cloud():
                    move_params['enforceSingleParent'] = True
                
                service.files().update(**move_params).execute()
            
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
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            file = service.files().create(**upload_params).execute()
            
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
        st.error(f'❌ Erro HTTP do Google Drive: {error}')
        return None
    except Exception as e:
        st.error(f'❌ Erro ao fazer upload: {str(e)}')
        return None

def baixar_arquivo_do_drive(service, nome_arquivo, folder_id):
    """Baixa um arquivo do Google Drive com suporte a drives compartilhados"""
    try:
        query = f"name = '{nome_arquivo}' and trashed = false"
        if folder_id:
            query = f"name = '{nome_arquivo}' and '{folder_id}' in parents and trashed = false"
        
        list_params = {
            'q': query,
            'spaces': 'drive',
            'fields': 'files(id, name)',
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True
        }
        
        if is_streamlit_cloud():
            list_params['corpora'] = 'drive'
            list_params['driveId'] = SHARED_DRIVE_ID
        
        results = service.files().list(**list_params).execute()
        arquivos = results.get('files', [])
        
        if arquivos:
            arquivo_id = arquivos[0]['id']
            request = service.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
            
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(nome_arquivo)[1], delete=False) as temp_file:
                caminho_temp = temp_file.name
                fh = BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                
                with open(caminho_temp, 'wb') as f:
                    f.write(fh.getvalue())
            
            return caminho_temp
        else:
            return None
            
    except Exception as e:
        st.error(f"❌ Erro ao baixar arquivo do Drive: {str(e)}")
        return None

# ========== FUNÇÃO PARA CARREGAR DADOS DOS FISCAIS ==========
@st.cache_data(ttl=3600)
def carregar_dados_fiscais():
    try:
        caminho_arquivo = os.path.join("Template", "Fiscais.xlsx")
        if os.path.exists(caminho_arquivo):
            df = pd.read_excel(caminho_arquivo, sheet_name='DADOS FISCAIS')
            colunas_necessarias = ['NOME', 'MATRICULA', 'UNIDADE']
            for coluna in colunas_necessarias:
                if coluna not in df.columns:
                    st.error(f"Coluna '{coluna}' não encontrada no arquivo Fiscais.xlsx")
                    return None
            df['MATRICULA'] = df['MATRICULA'].astype(str).str.strip()
            df = df[df['MATRICULA'].notna() & (df['MATRICULA'] != '')]
            dados_fiscais = {}
            for _, row in df.iterrows():
                matricula = str(row['MATRICULA']).strip()
                dados_fiscais[matricula] = {
                    'NOME': str(row['NOME']).strip() if pd.notna(row['NOME']) else '',
                    'MATRICULA': matricula,
                    'UNIDADE': str(row['UNIDADE']).strip() if pd.notna(row['UNIDADE']) else ''
                }
            return dados_fiscais
        else:
            return None
    except Exception as e:
        st.error(f"Erro ao carregar dados dos fiscais: {str(e)}")
        return None

# ========== CLASSE CONTADOR DE RELATÓRIOS MELHORADA ==========
class ContadorRelatorios:
    def __init__(self, service=None, folder_id=GOOGLE_DRIVE_FOLDER_ID, arquivo_contador=CONTADOR_FILENAME):
        self.service = service
        self.folder_id = folder_id
        self.arquivo_contador = arquivo_contador
        self.contadores = self.carregar_contadores()
    
    def carregar_contadores(self):
        """Carrega os contadores do Google Drive ou cria um novo"""
        if self.service:
            caminho_temp = baixar_arquivo_do_drive(self.service, self.arquivo_contador, self.folder_id)
            if caminho_temp:
                try:
                    with open(caminho_temp, 'r') as f:
                        contadores = json.load(f)
                    os.unlink(caminho_temp)
                    return contadores
                except Exception as e:
                    pass
        
        return {}
    
    def salvar_contadores(self):
        """Salva os contadores no Google Drive"""
        if not self.service:
            return False
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                json.dump(self.contadores, temp_file)
                temp_path = temp_file.name
            
            resultado = upload_para_google_drive(
                caminho_arquivo=temp_path,
                nome_arquivo=self.arquivo_contador,
                service=self.service,
                folder_id=self.folder_id
            )
            
            os.unlink(temp_path)
            return resultado is not None
            
        except Exception as e:
            return False
    
    def gerar_novo_numero(self, matricula):
        """
        Gera um novo número de relatório de forma atômica
        Retorna o número gerado e atualiza o contador permanentemente
        """
        ano = datetime.now().strftime("%Y")
        matricula_formatada = matricula.zfill(4)
        chave = f"{ano}_{matricula_formatada}"
        
        # Obtém o próximo número disponível
        if chave in self.contadores:
            proximo_numero = self.contadores[chave] + 1
        else:
            proximo_numero = 1
        
        # ATUALIZA o contador (número é realmente usado)
        self.contadores[chave] = proximo_numero
        
        # Salva no Drive imediatamente
        if self.service:
            self.salvar_contadores()
        
        contador_formatado = str(proximo_numero).zfill(4)
        
        return f"{ano}{matricula_formatada}{contador_formatado}", proximo_numero

# ========== FUNÇÕES PARA GERENCIAMENTO DA PLANILHA MASTER (NA NUVEM) ==========
def inicializar_planilha_master():
    colunas = [
        'NUMERO_RELATORIO', 'SITUACAO', 'DATA_RELATORIO', 'FATO_GERADOR', 'PROTOCOLO', 'TIPO_ACAO',
        'TIPO_ACAO_OUTROS',
        'LATITUDE', 'LONGITUDE', 'ENDERECO', 'NUMERO_ENDERECO', 'COMPLEMENTO', 'BAIRRO',
        'MUNICIPIO', 'UF', 'CEP', 'DESCRITIVO_ENDERECO',
        'NOME_CONTRATANTE', 'REGISTRO_CONTRATANTE', 'CPF_CNPJ_CONTRATANTE',
        'CONSTATACAO_FISCAL', 'MOTIVO_ACAO',
        'CARACTERISTICA', 'CARACTERISTICA_OUTROS',
        'FASE_ATIVIDADE', 'FASE_ATIVIDADE_OUTROS',
        'NUM_PAVIMENTOS', 'QUANTIFICACAO', 'UNIDADE_MEDIDA', 'UNIDADE_MEDIDA_OUTROS',
        'NATUREZA', 'NATUREZA_OUTROS',
        'TIPO_CONSTRUCAO', 'TIPO_CONSTRUCAO_OUTROS',
        'CONTRATADO_01_MESMO_CONTRATANTE',
        'CONTRATADO_01_NOME_CONTRATANTE', 'CONTRATADO_01_REGISTRO_CONTRATANTE', 'CONTRATADO_01_CPF_CNPJ_CONTRATANTE',
        'CONTRATADO_01_CONTRATADO_PF_PJ', 'CONTRATADO_01_REGISTRO', 'CONTRATADO_01_CPF_CNPJ',
        'CONTRATADO_01_PROFISSIONAL', 'CONTRATADO_01_IDENTIFICACAO_FISCALIZADO',
        'CONTRATADO_01_NUMERO_ART', 'CONTRATADO_01_NUMERO_RRT', 'CONTRATADO_01_NUMERO_TRT',
        'CONTRATADO_01_RAMO_ATIVIDADE', 'CONTRATADO_01_SERVICO_EXECUTADO', 'CONTRATADO_01_SERVICO_OUTROS',
        'CONTRATADO_01_FONTE_INFORMACAO', 'CONTRATADO_01_QUALIFICACAO_FONTE', 'CONTRATADO_01_QUALIFICACAO_OUTROS',
        'CONTRATADO_02_MESMO_CONTRATANTE',
        'CONTRATADO_02_NOME_CONTRATANTE', 'CONTRATADO_02_REGISTRO_CONTRATANTE', 'CONTRATADO_02_CPF_CNPJ_CONTRATANTE',
        'CONTRATADO_02_CONTRATADO_PF_PJ', 'CONTRATADO_02_REGISTRO', 'CONTRATADO_02_CPF_CNPJ',
        'CONTRATADO_02_PROFISSIONAL', 'CONTRATADO_02_IDENTIFICACAO_FISCALIZADO',
        'CONTRATADO_02_NUMERO_ART', 'CONTRATADO_02_NUMERO_RRT', 'CONTRATADO_02_NUMERO_TRT',
        'CONTRATADO_02_RAMO_ATIVIDADE', 'CONTRATADO_02_SERVICO_EXECUTADO', 'CONTRATADO_02_SERVICO_OUTROS',
        'CONTRATADO_02_FONTE_INFORMACAO', 'CONTRATADO_02_QUALIFICACAO_FONTE', 'CONTRATADO_02_QUALIFICACAO_OUTROS',
        'CONTRATADO_03_MESMO_CONTRATANTE',
        'CONTRATADO_03_NOME_CONTRATANTE', 'CONTRATADO_03_REGISTRO_CONTRATANTE', 'CONTRATADO_03_CPF_CNPJ_CONTRATANTE',
        'CONTRATADO_03_CONTRATADO_PF_PJ', 'CONTRATADO_03_REGISTRO', 'CONTRATADO_03_CPF_CNPJ',
        'CONTRATADO_03_PROFISSIONAL', 'CONTRATADO_03_IDENTIFICACAO_FISCALIZADO',
        'CONTRATADO_03_NUMERO_ART', 'CONTRATADO_03_NUMERO_RRT', 'CONTRATADO_03_NUMERO_TRT',
        'CONTRATADO_03_RAMO_ATIVIDADE', 'CONTRATADO_03_SERVICO_EXECUTADO', 'CONTRATADO_03_SERVICO_OUTROS',
        'CONTRATADO_03_FONTE_INFORMACAO', 'CONTRATADO_03_QUALIFICACAO_FONTE', 'CONTRATADO_03_QUALIFICACAO_OUTROS',
        'CONTRATADO_04_MESMO_CONTRATANTE',
        'CONTRATADO_04_NOME_CONTRATANTE', 'CONTRATADO_04_REGISTRO_CONTRATANTE', 'CONTRATADO_04_CPF_CNPJ_CONTRATANTE',
        'CONTRATADO_04_CONTRATADO_PF_PJ', 'CONTRATADO_04_REGISTRO', 'CONTRATADO_04_CPF_CNPJ',
        'CONTRATADO_04_PROFISSIONAL', 'CONTRATADO_04_IDENTIFICACAO_FISCALIZADO',
        'CONTRATADO_04_NUMERO_ART', 'CONTRATADO_04_NUMERO_RRT', 'CONTRATADO_04_NUMERO_TRT',
        'CONTRATADO_04_RAMO_ATIVIDADE', 'CONTRATADO_04_SERVICO_EXECUTADO', 'CONTRATADO_04_SERVICO_OUTROS',
        'CONTRATADO_04_FONTE_INFORMACAO', 'CONTRATADO_04_QUALIFICACAO_FONTE', 'CONTRATADO_04_QUALIFICACAO_OUTROS',
        'CONTRATADO_05_MESMO_CONTRATANTE',
        'CONTRATADO_05_NOME_CONTRATANTE', 'CONTRATADO_05_REGISTRO_CONTRATANTE', 'CONTRATADO_05_CPF_CNPJ_CONTRATANTE',
        'CONTRATADO_05_CONTRATADO_PF_PJ', 'CONTRATADO_05_REGISTRO', 'CONTRATADO_05_CPF_CNPJ',
        'CONTRATADO_05_PROFISSIONAL', 'CONTRATADO_05_IDENTIFICACAO_FISCALIZADO',
        'CONTRATADO_05_NUMERO_ART', 'CONTRATADO_05_NUMERO_RRT', 'CONTRATADO_05_NUMERO_TRT',
        'CONTRATADO_05_RAMO_ATIVIDADE', 'CONTRATADO_05_SERVICO_EXECUTADO', 'CONTRATADO_05_SERVICO_OUTROS',
        'CONTRATADO_05_FONTE_INFORMACAO', 'CONTRATADO_05_QUALIFICACAO_FONTE', 'CONTRATADO_05_QUALIFICACAO_OUTROS',
        'TOTAL_CONTRATADOS_REGISTROS',
        'DOCUMENTOS_SOLICITADOS', 'DOCUMENTOS_SOLICITADOS_OFICIO_NUMERO',
        'DOCUMENTOS_SOLICITADOS_QUADRO_TECNICO', 'DOCUMENTOS_SOLICITADOS_PRESTADORES',
        'DOCUMENTOS_SOLICITADOS_OUTROS', 'DOCUMENTOS_SOLICITADOS_OUTROS_TEXTO',
        'DOCUMENTOS_SOLICITADOS_DETALHES',
        'DOCUMENTOS_RECEBIDOS', 'DOCUMENTOS_RECEBIDOS_OFICIO_NUMERO',
        'DOCUMENTOS_RECEBIDOS_QUADRO_TECNICO', 'DOCUMENTOS_RECEBIDOS_QUADRO_TECNICO_QUANTIDADE',
        'DOCUMENTOS_RECEBIDOS_PRESTADORES', 'DOCUMENTOS_RECEBIDOS_PRESTADORES_QUANTIDADE',
        'DOCUMENTOS_RECEBIDOS_OUTROS', 'DOCUMENTOS_RECEBIDOS_OUTROS_TEXTO',
        'DOCUMENTOS_RECEBIDOS_DETALHES',
        'DATA_RELATORIO_ANTERIOR', 'INFORMACOES_COMPLEMENTARES',
        'FONTE_INFORMACAO', 'QUALIFICACAO_FONTE', 'QUALIFICACAO_FONTE_OUTROS',
        'TOTAL_FOTOS', 'FOTOS_COM_COMENTARIOS',
        'AGENTE_NOME', 'AGENTE_MATRICULA', 'AGENTE_UNIDADE',
        'DATA_GERACAO'
    ]
    
    df = pd.DataFrame(columns=colunas)
    
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
        caminho_temp = temp_file.name
        df.to_excel(caminho_temp, index=False)
    
    return caminho_temp

def carregar_planilha_master_drive(service, folder_id):
    try:
        query = f"name = '{EXCEL_DATABASE_NAME}' and trashed = false"
        if folder_id:
            query = f"name = '{EXCEL_DATABASE_NAME}' and '{folder_id}' in parents and trashed = false"
        
        list_params = {
            'q': query,
            'spaces': 'drive',
            'fields': 'files(id, name)',
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True
        }
        
        if is_streamlit_cloud():
            list_params['corpora'] = 'drive'
            list_params['driveId'] = SHARED_DRIVE_ID
        
        results = service.files().list(**list_params).execute()
        arquivos = results.get('files', [])
        
        if arquivos:
            arquivo_id = arquivos[0]['id']
            request = service.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
            
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
                caminho_temp = temp_file.name
                fh = BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                
                with open(caminho_temp, 'wb') as f:
                    f.write(fh.getvalue())
            
            try:
                df = pd.read_excel(caminho_temp)
            except Exception as e:
                caminho_temp = inicializar_planilha_master()
                df = pd.read_excel(caminho_temp)
            
            return df, caminho_temp
        else:
            caminho_temp = inicializar_planilha_master()
            df = pd.read_excel(caminho_temp)
            return df, caminho_temp
            
    except Exception as e:
        st.error(f"❌ Erro ao carregar Planilha Master do Drive: {str(e)}")
        caminho_temp = inicializar_planilha_master()
        df = pd.read_excel(caminho_temp)
        return df, caminho_temp

def adicionar_relatorio_a_planilha_master(dados_relatorio, agente_info, fotos_info, service, folder_id,
                                         tipo_visita_outros="",
                                         caracteristica_outros="", fase_atividade_outros="",
                                         unidade_medida_outros="", natureza_outros="",
                                         tipo_construcao_outros="",
                                         circular_numero="", outros_texto_solicitado="",
                                         circular_numero_recebido="", quadro_tecnico_quantidade="",
                                         prestadores_quantidade="", outros_texto_recebido="",
                                         qualificacao_outros=""):
    try:
        df_existente, caminho_temp = carregar_planilha_master_drive(service, folder_id)
        
        novos_dados = preparar_dados_para_planilha_master(
            dados_relatorio, agente_info, fotos_info,
            tipo_visita_outros, caracteristica_outros, fase_atividade_outros,
            unidade_medida_outros, natureza_outros, tipo_construcao_outros,
            circular_numero, outros_texto_solicitado,
            circular_numero_recebido, quadro_tecnico_quantidade,
            prestadores_quantidade, outros_texto_recebido,
            qualificacao_outros
        )
        
        numero_relatorio = novos_dados['NUMERO_RELATORIO']
        
        relatorio_existente = pd.DataFrame()
        if not df_existente.empty and 'NUMERO_RELATORIO' in df_existente.columns:
            relatorio_existente = df_existente[df_existente['NUMERO_RELATORIO'] == numero_relatorio]
        
        if not relatorio_existente.empty:
            idx = df_existente[df_existente['NUMERO_RELATORIO'] == numero_relatorio].index[0]
            for col, valor in novos_dados.items():
                if col in df_existente.columns:
                    df_existente.at[idx, col] = valor
        else:
            novo_df = pd.DataFrame([novos_dados])
            df_existente = pd.concat([df_existente, novo_df], ignore_index=True)
        
        df_existente.to_excel(caminho_temp, index=False)
        
        drive_info = upload_para_google_drive(
            caminho_arquivo=caminho_temp,
            nome_arquivo=EXCEL_DATABASE_NAME,
            service=service,
            folder_id=folder_id
        )
        
        if drive_info:
            return True
        else:
            return False
            
    except Exception as e:
        st.error(f"❌ Erro ao adicionar dados à Planilha Master: {str(e)}")
        return False
    finally:
        if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
            try:
                os.unlink(caminho_temp)
            except:
                pass

def preparar_dados_para_planilha_master(dados, agente_info, fotos_info, 
                                        tipo_visita_outros="",
                                        caracteristica_outros="", fase_atividade_outros="",
                                        unidade_medida_outros="", natureza_outros="",
                                        tipo_construcao_outros="",
                                        circular_numero="", outros_texto_solicitado="",
                                        circular_numero_recebido="", quadro_tecnico_quantidade="",
                                        prestadores_quantidade="", outros_texto_recebido="",
                                        qualificacao_outros=""):
    total_contratados = len(dados.get('contratados_data', []))
    
    dados_excel = {
        'NUMERO_RELATORIO': dados.get('numero_relatorio', ''),
        'SITUACAO': dados.get('situacao', ''),
        'DATA_RELATORIO': dados.get('data_relatorio', ''),
        'FATO_GERADOR': dados.get('fato_gerador', ''),
        'PROTOCOLO': dados.get('protocolo', ''),
        'TIPO_ACAO': dados.get('tipo_visita', ''),
        'TIPO_ACAO_OUTROS': tipo_visita_outros if dados.get('tipo_visita') == "Outras" else "",
        'LATITUDE': dados.get('latitude', ''),
        'LONGITUDE': dados.get('longitude', ''),
        'ENDERECO': dados.get('endereco', ''),
        'NUMERO_ENDERECO': dados.get('numero', ''),
        'COMPLEMENTO': dados.get('complemento', ''),
        'BAIRRO': dados.get('bairro', ''),
        'MUNICIPIO': dados.get('municipio', ''),
        'UF': dados.get('uf', 'RJ'),
        'CEP': dados.get('cep', ''),
        'DESCRITIVO_ENDERECO': dados.get('descritivo_endereco', ''),
        'NOME_CONTRATANTE': dados.get('nome_contratante', ''),
        'REGISTRO_CONTRATANTE': dados.get('registro_contratante', ''),
        'CPF_CNPJ_CONTRATANTE': dados.get('cpf_cnpj', ''),
        'CONSTATACAO_FISCAL': dados.get('constatacao_fiscal', ''),
        'MOTIVO_ACAO': dados.get('motivo_acao', ''),
        'CARACTERISTICA': dados.get('caracteristica', ''),
        'CARACTERISTICA_OUTROS': caracteristica_outros if dados.get('caracteristica') == "OUTRAS" else "",
        'FASE_ATIVIDADE': dados.get('fase_atividade', ''),
        'FASE_ATIVIDADE_OUTROS': fase_atividade_outros if dados.get('fase_atividade') == "OUTRAS" else "",
        'NUM_PAVIMENTOS': dados.get('num_pavimentos', ''),
        'QUANTIFICACAO': dados.get('quantificacao', ''),
        'UNIDADE_MEDIDA': dados.get('unidade_medida', ''),
        'UNIDADE_MEDIDA_OUTROS': unidade_medida_outros if dados.get('unidade_medida') == "OUTRAS" else "",
        'NATUREZA': dados.get('natureza', ''),
        'NATUREZA_OUTROS': natureza_outros if dados.get('natureza') == "OUTRAS" else "",
        'TIPO_CONSTRUCAO': dados.get('tipo_construcao', ''),
        'TIPO_CONSTRUCAO_OUTROS': tipo_construcao_outros if dados.get('tipo_construcao') == "OUTRAS" else "",
        'DOCUMENTOS_SOLICITADOS': dados.get('documentos_solicitados', ''),
        'DOCUMENTOS_SOLICITADOS_OFICIO_NUMERO': circular_numero,
        'DOCUMENTOS_SOLICITADOS_QUADRO_TECNICO': "SIM" if dados.get('quadro_tecnico_solicitado') else "NÃO",
        'DOCUMENTOS_SOLICITADOS_PRESTADORES': "SIM" if dados.get('prestadores_servicos_solicitado') else "NÃO",
        'DOCUMENTOS_SOLICITADOS_OUTROS': "SIM" if dados.get('outros_solicitado') else "NÃO",
        'DOCUMENTOS_SOLICITADOS_OUTROS_TEXTO': outros_texto_solicitado,
        'DOCUMENTOS_SOLICITADOS_DETALHES': dados.get('documentos_solicitados_text', ''),
        'DOCUMENTOS_RECEBIDOS': dados.get('documentos_recebidos', ''),
        'DOCUMENTOS_RECEBIDOS_OFICIO_NUMERO': circular_numero_recebido,
        'DOCUMENTOS_RECEBIDOS_QUADRO_TECNICO': "SIM" if dados.get('quadro_tecnico_recebido') else "NÃO",
        'DOCUMENTOS_RECEBIDOS_QUADRO_TECNICO_QUANTIDADE': quadro_tecnico_quantidade,
        'DOCUMENTOS_RECEBIDOS_PRESTADORES': "SIM" if dados.get('prestadores_servicos_recebido') else "NÃO",
        'DOCUMENTOS_RECEBIDOS_PRESTADORES_QUANTIDADE': prestadores_quantidade,
        'DOCUMENTOS_RECEBIDOS_OUTROS': "SIM" if dados.get('outros_recebido') else "NÃO",
        'DOCUMENTOS_RECEBIDOS_OUTROS_TEXTO': outros_texto_recebido,
        'DOCUMENTOS_RECEBIDOS_DETALHES': dados.get('documentos_recebidos_text', ''),
        'DATA_RELATORIO_ANTERIOR': dados.get('data_relatorio_anterior', 'NAO INFORMADO'),
        'INFORMACOES_COMPLEMENTARES': dados.get('informacoes_complementares', ''),
        'FONTE_INFORMACAO': dados.get('fonte_informacao', ''),
        'QUALIFICACAO_FONTE': dados.get('qualificacao_fonte', ''),
        'QUALIFICACAO_FONTE_OUTROS': qualificacao_outros if dados.get('qualificacao_fonte') == "OUTRAS" else "",
        'TOTAL_FOTOS': len(fotos_info),
        'FOTOS_COM_COMENTARIOS': sum(1 for foto in fotos_info if foto.comentario.strip()),
        'AGENTE_NOME': agente_info.get('NOME', '') if agente_info else '',
        'AGENTE_MATRICULA': agente_info.get('MATRICULA', '') if agente_info else '',
        'AGENTE_UNIDADE': agente_info.get('UNIDADE', '') if agente_info else '',
        'DATA_GERACAO': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'TOTAL_CONTRATADOS_REGISTROS': total_contratados
    }
    
    contratados_data = dados.get('contratados_data', [])
    
    for i in range(1, 6):
        prefix = f'CONTRATADO_{i:02d}'
        
        if i <= len(contratados_data):
            contrato = contratados_data[i-1]
            
            servico_outros = ""
            if contrato.get('servico_executado') == "Outras":
                servico_outros = contrato.get('servico_executado_outras', '')
            
            qualificacao_outros_contratado = ""
            if contrato.get('qualificacao_fonte_secao04') == "OUTRAS":
                qualificacao_outros_contratado = contrato.get('qualificacao_outras_secao04', '')
            
            dados_excel.update({
                f'{prefix}_MESMO_CONTRATANTE': contrato.get('mesmo_contratante', ''),
                f'{prefix}_NOME_CONTRATANTE': contrato.get('nome_contratante_secao04', ''),
                f'{prefix}_REGISTRO_CONTRATANTE': contrato.get('registro_contratante_secao04', ''),
                f'{prefix}_CPF_CNPJ_CONTRATANTE': contrato.get('cpf_cnpj_secao04', ''),
                f'{prefix}_CONTRATADO_PF_PJ': contrato.get('contratado_pf_pj', ''),
                f'{prefix}_REGISTRO': contrato.get('registro', ''),
                f'{prefix}_CPF_CNPJ': contrato.get('cpf_cnpj_contratado', ''),
                f'{prefix}_PROFISSIONAL': contrato.get('contrato', ''),
                f'{prefix}_IDENTIFICACAO_FISCALIZADO': contrato.get('identificacao_fiscalizado', ''),
                f'{prefix}_NUMERO_ART': contrato.get('numero_art', ''),
                f'{prefix}_NUMERO_RRT': contrato.get('numero_rrt', ''),
                f'{prefix}_NUMERO_TRT': contrato.get('numero_trt', ''),
                f'{prefix}_RAMO_ATIVIDADE': contrato.get('ramo_atividade', ''),
                f'{prefix}_SERVICO_EXECUTADO': contrato.get('servico_executado', ''),
                f'{prefix}_SERVICO_OUTROS': servico_outros,
                f'{prefix}_FONTE_INFORMACAO': contrato.get('fonte_informacao_secao04', ''),
                f'{prefix}_QUALIFICACAO_FONTE': contrato.get('qualificacao_fonte_secao04', ''),
                f'{prefix}_QUALIFICACAO_OUTROS': qualificacao_outros_contratado
            })
        else:
            dados_excel.update({
                f'{prefix}_MESMO_CONTRATANTE': '',
                f'{prefix}_NOME_CONTRATANTE': '',
                f'{prefix}_REGISTRO_CONTRATANTE': '',
                f'{prefix}_CPF_CNPJ_CONTRATANTE': '',
                f'{prefix}_CONTRATADO_PF_PJ': '',
                f'{prefix}_REGISTRO': '',
                f'{prefix}_CPF_CNPJ': '',
                f'{prefix}_PROFISSIONAL': '',
                f'{prefix}_IDENTIFICACAO_FISCALIZADO': '',
                f'{prefix}_NUMERO_ART': '',
                f'{prefix}_NUMERO_RRT': '',
                f'{prefix}_NUMERO_TRT': '',
                f'{prefix}_RAMO_ATIVIDADE': '',
                f'{prefix}_SERVICO_EXECUTADO': '',
                f'{prefix}_SERVICO_OUTROS': '',
                f'{prefix}_FONTE_INFORMACAO': '',
                f'{prefix}_QUALIFICACAO_FONTE': '',
                f'{prefix}_QUALIFICACAO_OUTROS': ''
            })
    
    return dados_excel

def exportar_planilha_para_download(df):
    try:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='RELATORIOS')
        excel_data = output.getvalue()
        return excel_data
    except Exception as e:
        st.error(f"Erro ao exportar Excel: {e}")
        return None

# ========== FUNÇÃO COMPATÍVEL PARA EXIBIR IMAGENS ==========
def exibir_imagem_compativel(imagem, caption="", use_container=True, width=None):
    try:
        if width is not None:
            return st.image(imagem, caption=caption, use_container_width=use_container, width=width)
        else:
            return st.image(imagem, caption=caption, use_container_width=use_container)
    except TypeError:
        try:
            if width is not None:
                return st.image(imagem, caption=caption, width=width)
            else:
                return st.image(imagem, caption=caption)
        except Exception:
            try:
                if width is not None:
                    return st.image(imagem, caption=caption, output_format='auto', width=width)
                else:
                    return st.image(imagem, caption=caption, output_format='auto')
            except:
                return st.image(imagem, caption=caption)

# ========== CACHE PARA PERFORMANCE ==========
@st.cache_data(ttl=3600)
def carregar_municipios_cache():
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
            self._thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
        return self._thumbnail
    
    def __getstate__(self):
        state = self.__dict__.copy()
        if '_image_obj' in state:
            del state['_image_obj']
        if '_thumbnail' in state:
            del state['_thumbnail']
        return state
    
    def __setstate__(self, state):
        self.__dict__.update(state)
        self._image_obj = None
        self._thumbnail = None

# ========== CLASSES DO SISTEMA ORIGINAL ==========
class PDF(FPDF):
    def __init__(self, logo_path=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logo_path = logo_path
        self.set_auto_page_break(auto=True, margin=15)
        self.set_left_margin(10)
        self.set_right_margin(10)
    
    def header(self):
        self.set_font('Arial', 'B', 14)
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                img_width = 40
                x_position = (210 - img_width) / 2
                self.image(self.logo_path, x=x_position, y=10, w=img_width)
                self.ln(15)
            except Exception as e:
                st.error(f"Erro ao carregar logo: {e}")
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
                    img_resized = img.resize((new_width_px, new_height_px), Image.Resampling.LANCZOS)
                else:
                    img_resized = img
                    new_width_mm = width_mm
                    new_height_mm = height_mm
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_img:
                    img_resized.save(temp_img.name, 'JPEG', quality=85, optimize=True, subsampling=0)
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
                    self.multi_cell(0, 4, f"Comentário: {foto_info.comentario}")
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
    
    def add_section_title(self, number, title):
        self.set_fill_color(200, 200, 200)
        self.set_text_color(0, 0, 0)
        self.set_font('Arial', 'B', 12)
        self.cell(0, 9, f'{number} - {title}', 0, 1, 'L', fill=True)
        self.ln(2)

# ========== FUNÇÕES AUXILIARES ==========
@st.cache_data(ttl=300)
def formatar_matricula(matricula):
    matricula_limpa = re.sub(r'\D', '', matricula)
    matricula_limpa = matricula_limpa[-4:] if len(matricula_limpa) > 4 else matricula_limpa
    return matricula_limpa.zfill(4)

def criar_pdf(dados, logo_path, fotos_info=None, agente_info=None):
    pdf = PDF(logo_path=logo_path, orientation='P', unit='mm', format='A4')
    pdf.set_title("Relatório de Fiscalização")
    pdf.set_author("Sistema de Fiscalização")
    
    if agente_info:
        pdf.agente_info = agente_info
    
    pdf.add_page()
    
    label_width = 50
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(label_width, 7, 'Número:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('numero_relatorio', ''), 0, 1)
    
    if dados.get('situacao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 7, 'Situação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('situacao', ''), 0, 1)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(label_width, 7, 'Data:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('data_relatorio', datetime.now().strftime('%d/%m/%Y')), 0, 1)
    
    if dados.get('fato_gerador'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 7, 'Fato Gerador:', 0, 0)
        pdf.set_font('Arial', '', 10)
        x_pos = pdf.get_x()
        y_pos = pdf.get_y()
        pdf.set_xy(x_pos, y_pos)
        pdf.multi_cell(0, 7, dados.get('fato_gerador', ''))
    
    if dados.get('protocolo'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 7, 'Protocolo:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('protocolo', ''), 0, 1)
    
    if dados.get('tipo_visita'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 7, 'Tipo Visita:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('tipo_visita', ''), 0, 1)
    
    pdf.ln(5)
    
    # Seção 01
    pdf.add_section_title("01", "ENDEREÇO DO EMPREENDIMENTO")
    pdf.set_font('Arial', '', 10)
    
    if dados.get('latitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Latitude:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('latitude', ''), 0, 1)
    
    if dados.get('longitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Longitude:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('longitude', ''), 0, 1)
    
    endereco = dados.get('endereco', '')
    numero = dados.get('numero', '')
    complemento = dados.get('complemento', '')
    
    if endereco or numero:
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Endereço:', 0, 0)
        pdf.set_font('Arial', '', 10)
        endereco_completo = ""
        if endereco:
            endereco_completo += f"{endereco}"
        if numero:
            endereco_completo += f", nº: {numero}"
        if complemento:
            endereco_completo += f" / {complemento}"
        x_pos = pdf.get_x()
        y_pos = pdf.get_y()
        pdf.set_xy(x_pos, y_pos)
        pdf.multi_cell(0, 5, endereco_completo)
    
    if dados.get('bairro'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Bairro:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('bairro', ''), 0, 1)
    
    municipio = dados.get('municipio', '')
    uf = dados.get('uf', '')
    if municipio:
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Município:', 0, 0)
        pdf.set_font('Arial', '', 10)
        municipio_uf = municipio
        if uf:
            municipio_uf += f" - {uf}"
        pdf.cell(0, 6, municipio_uf, 0, 1)
    
    if dados.get('cep'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'CEP:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cep', ''), 0, 1)
    
    if dados.get('descritivo_endereco'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Descritivo:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('descritivo_endereco', ''))
    
    pdf.ln(4)
    
    # Seção 02
    pdf.add_section_title("02", "IDENTIFICAÇÃO DO PROPRIETÁRIO/CONTRATANTE")
    pdf.set_font('Arial', '', 10)
    
    if dados.get('nome_contratante'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Nome:', 0, 0)
        pdf.set_font('Arial', '', 10)
        x_pos = pdf.get_x()
        y_pos = pdf.get_y()
        pdf.set_xy(x_pos, y_pos)
        pdf.multi_cell(0, 5, dados.get('nome_contratante', ''))
    
    if dados.get('registro_contratante'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Registro:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('registro_contratante', ''), 0, 1)
    
    if dados.get('cpf_cnpj'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'CPF/CNPJ:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cpf_cnpj', ''), 0, 1)
    
    if dados.get('constatacao_fiscal'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Constatação do Fiscal:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('constatacao_fiscal', ''))
    
    if dados.get('motivo_acao'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Motivo da Ação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('motivo_acao', ''))
    
    pdf.ln(4)
    
    # Seção 03
    pdf.add_section_title("03", "ATIVIDADE DESENVOLVIDA (OBRA, SERVIÇO, EVENTOS)")
    pdf.set_font('Arial', '', 10)
    
    if dados.get('caracteristica'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Característica:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('caracteristica', ''), 0, 1)
    
    if dados.get('fase_atividade'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Fase Atividade:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('fase_atividade', ''), 0, 1)
    
    if dados.get('num_pavimentos') and dados.get('num_pavimentos') != '0':
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Nº Pavimentos:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('num_pavimentos', ''), 0, 1)
    
    quantificacao = dados.get('quantificacao', '')
    unidade_medida = dados.get('unidade_medida', '')
    if quantificacao:
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Quantificação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        quant_text = quantificacao
        if unidade_medida:
            quant_text += f" {unidade_medida}"
        pdf.cell(0, 6, quant_text, 0, 1)
    
    if dados.get('natureza'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Natureza:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('natureza', ''), 0, 1)
    
    if dados.get('tipo_construcao'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Tipo Construção:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('tipo_construcao', ''), 0, 1)
    
    pdf.ln(4)
    
    # Seção 04
    pdf.add_section_title("04", "IDENTIFICAÇÃO DOS CONTRATADOS, RESPONSÁVEIS TÉCNICOS E/OU FISCALIZADOS")
    pdf.set_font('Arial', '', 10)
    
    contratados_data = dados.get('contratados_data', [])
    
    if not contratados_data:
        pdf.multi_cell(0, 5, 'SEM CONTRATADOS E RESPONSÁVEIS TÉCNICOS')
    else:
        for i, contrato in enumerate(contratados_data, 1):
            if pdf.get_y() > 250:
                pdf.add_page()
            
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
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'Nome:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    x_pos = pdf.get_x()
                    y_pos = pdf.get_y()
                    pdf.set_xy(x_pos, y_pos)
                    pdf.multi_cell(0, 5, dados.get('nome_contratante', ''))
                
                if dados.get('registro_contratante'):
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'Registro:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, dados.get('registro_contratante', ''), 0, 1)
                
                if dados.get('cpf_cnpj'):
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'CPF/CNPJ:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, dados.get('cpf_cnpj', ''), 0, 1)
            
            elif mesmo_contratante == "NÃO":
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 6, '(Informações específicas para este registro)', 0, 1)
                pdf.set_font('Arial', '', 10)
                
                if contrato.get('nome_contratante_secao04'):
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'Nome:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    x_pos = pdf.get_x()
                    y_pos = pdf.get_y()
                    pdf.set_xy(x_pos, y_pos)
                    pdf.multi_cell(0, 5, contrato.get('nome_contratante_secao04', ''))
                
                if contrato.get('registro_contratante_secao04'):
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'Registro:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, contrato.get('registro_contratante_secao04', ''), 0, 1)
                
                if contrato.get('cpf_cnpj_secao04'):
                    pdf.set_x(10)
                    pdf.set_font('Arial', 'B', 10)
                    pdf.cell(label_width, 6, 'CPF/CNPJ:', 0, 0)
                    pdf.set_font('Arial', '', 10)
                    pdf.cell(0, 6, contrato.get('cpf_cnpj_secao04', ''), 0, 1)
            
            pdf.ln(2)
            
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, 'Dados do Contratado/Responsável Técnico:', 0, 1)
            pdf.set_font('Arial', '', 10)
            
            if contrato.get('contratado_pf_pj'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Contratado PF/PJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                x_pos = pdf.get_x()
                y_pos = pdf.get_y()
                pdf.set_xy(x_pos, y_pos)
                pdf.multi_cell(0, 5, contrato.get('contratado_pf_pj', ''))
            
            if contrato.get('registro'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Registro:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('registro', ''), 0, 1)
            
            if contrato.get('cpf_cnpj_contratado'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'CPF/CNPJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('cpf_cnpj_contratado', ''), 0, 1)
            
            if contrato.get('contrato'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Profissional:', 0, 0)
                pdf.set_font('Arial', '', 10)
                x_pos = pdf.get_x()
                y_pos = pdf.get_y()
                pdf.set_xy(x_pos, y_pos)
                pdf.multi_cell(0, 5, contrato.get('contrato', ''))
            
            if contrato.get('identificacao_fiscalizado'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Identificação do fiscalizado:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('identificacao_fiscalizado', ''), 0, 1)
            
            if contrato.get('numero_art'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Número ART:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_art', ''), 0, 1)
            
            if contrato.get('numero_rrt'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Número RRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_rrt', ''), 0, 1)
            
            if contrato.get('numero_trt'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Número TRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_trt', ''), 0, 1)
            
            if contrato.get('ramo_atividade'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Ramo Atividade:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('ramo_atividade', ''), 0, 1)
            
            if contrato.get('servico_executado'):
                pdf.set_x(10)
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(label_width, 6, 'Serviço Executado:', 0, 0)
                pdf.set_font('Arial', '', 10)
                
                servico_valor = contrato.get('servico_executado', '')
                
                if servico_valor == "Outras" and contrato.get('servico_executado_outras'):
                    servico_valor = contrato.get('servico_executado_outras', '')
                
                x_pos = pdf.get_x()
                y_pos = pdf.get_y()
                pdf.set_xy(x_pos, y_pos)
                pdf.multi_cell(0, 5, servico_valor)
            
            pdf.ln(3)
            
            pdf.set_x(10)
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(label_width, 6, 'Fonte de Informação:', 0, 1)
            pdf.set_font('Arial', '', 10)
            pdf.multi_cell(0, 5, contrato.get('fonte_informacao_secao04', '') or '')
            
            pdf.set_x(10)
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(label_width, 6, 'Qualificação da Fonte:', 0, 1)
            pdf.set_font('Arial', '', 10)
            pdf.cell(0, 6, contrato.get('qualificacao_fonte_secao04', '') or '', 0, 1)
            
            pdf.ln(3)
    
    pdf.ln(4)
    
    # Seções 05-06
    pdf.add_section_title("05", "DOCUMENTOS SOLICITADOS / EXPEDIDOS")
    pdf.set_font('Arial', '', 10)
    
    documentos_solicitados = dados.get('documentos_solicitados', '')
    if documentos_solicitados and documentos_solicitados != "SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS":
        pdf.multi_cell(0, 5, documentos_solicitados)
    else:
        pdf.multi_cell(0, 5, 'SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS')
    
    pdf.ln(4)
    
    pdf.add_section_title("06", "DOCUMENTOS RECEBIDOS")
    pdf.set_font('Arial', '', 10)
    
    documentos_recebidos = dados.get('documentos_recebidos', '')
    if documentos_recebidos and documentos_recebidos != "SEM DOCUMENTOS RECEBIDOS":
        pdf.multi_cell(0, 5, documentos_recebidos)
    else:
        pdf.multi_cell(0, 5, 'SEM DOCUMENTOS RECEBIDOS')
    
    pdf.ln(4)
    
    # Seção 07
    pdf.add_section_title("07", "OUTRAS INFORMAÇÕES")
    pdf.set_font('Arial', '', 10)
    
    if dados.get('data_relatorio_anterior') and dados.get('data_relatorio_anterior') != "NAO INFORMADO":
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Data Relatório Anterior:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('data_relatorio_anterior', ''), 0, 1)
    
    if dados.get('informacoes_complementares'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Informações Complementares:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('informacoes_complementares', ''))
    
    if dados.get('fonte_informacao'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Fonte de Informação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('fonte_informacao', ''))
    
    if dados.get('qualificacao_fonte'):
        pdf.set_x(10)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(label_width, 6, 'Qualificação da Fonte:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('qualificacao_fonte', ''), 0, 1)
    
    pdf.ln(4)
    
    # Seção 08
    pdf.add_section_title("08", "FOTOS")
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

# ========== FUNÇÕES PARA LIMPAR FORMULÁRIO ==========
def limpar_formulario():
    if 'fotos_info' in st.session_state:
        st.session_state.fotos_info = []
    if 'contratados_data' in st.session_state:
        st.session_state.contratados_data = []
    if 'current_foto_index' not in st.session_state:
        st.session_state.current_foto_index = 0
    if 'documentos_solicitados_text' not in st.session_state:
        st.session_state.documentos_solicitados_text = ""
    if 'documentos_recebidos_text' not in st.session_state:
        st.session_state.documentos_recebidos_text = ""
    if 'temp_photo_bytes' in st.session_state:
        st.session_state.temp_photo_bytes = None
    if 'camera_counter' not in st.session_state:
        st.session_state.camera_counter = 0
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    st.session_state.form_widget_counter += 1

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
        'servico_executado': "",
        'servico_executado_outras': "",
        'fonte_informacao_secao04': "",
        'qualificacao_fonte_secao04': "",
        'qualificacao_outras_secao04': ""
    }

def limpar_campos_secao_04():
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
        'servico_executado': "",
        'servico_executado_outras': "",
        'fonte_informacao_secao04': "",
        'qualificacao_fonte_secao04': "",
        'qualificacao_outras_secao04': ""
    }

# ========== FUNÇÃO PRINCIPAL ==========
def main():
    # Inicialização do session_state
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'matricula' not in st.session_state:
        st.session_state.matricula = ""
    if 'numero_relatorio_gerado' not in st.session_state:
        st.session_state.numero_relatorio_gerado = "A SER GERADO"
    if 'numero_sequencial' not in st.session_state:
        st.session_state.numero_sequencial = 0
    if 'agente_info' not in st.session_state:
        st.session_state.agente_info = None
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
    if 'pasta_local' not in st.session_state:
        st.session_state.pasta_local = None
    if 'contador_manager' not in st.session_state:
        st.session_state.contador_manager = None
    
    dados_fiscais = carregar_dados_fiscais()
    
    # Página de login
    if not st.session_state.logged_in:
        st.title("Relatório de Fiscalização")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if os.path.exists("10.png"):
                exibir_imagem_compativel("10.png", width=300)
            else:
                st.markdown("🔒")
            
            matricula_input = st.text_input(
                "Matrícula (3-4 dígitos)",
                placeholder="Ex: 496 ou 0496",
                key="login_matricula"
            )
            
            if st.button("Entrar", type="primary", use_container_width=True, key="login_button"):
                if matricula_input:
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
                            # Define a pasta local baseada na matrícula
                            st.session_state.pasta_local = get_pasta_local(matricula_formatada)
                            
                            # Inicializa o serviço do Drive e o contador
                            drive_service = autenticar_google_drive()
                            if drive_service:
                                contador_manager = ContadorRelatorios(service=drive_service, folder_id=GOOGLE_DRIVE_FOLDER_ID)
                            else:
                                st.warning("⚠️ Usando contador local (sem sincronia com a nuvem)")
                                contador_manager = ContadorRelatorios(service=None)
                            
                            # GUARDA O MANAGER NA SESSÃO
                            st.session_state.contador_manager = contador_manager
                            
                            # NÃO GERA NÚMERO NO LOGIN - apenas prepara o sistema
                            st.session_state.logged_in = True
                            st.session_state.matricula = matricula_formatada
                            st.session_state.agente_info = agente_info
                            
                            st.success(f"Login realizado! Agente: {agente_info['NOME']}")
                            st.rerun()
                        else:
                            st.error("Matrícula não encontrada no sistema de fiscais.")
                    else:
                        st.error("Matrícula deve ter entre 3 e 4 dígitos!")
                else:
                    st.error("Preencha a matrícula!")
        
        st.markdown("Carlos Franklin - 2025")
        st.caption("Relatório de Fiscalização - Versão 2.1 (Adaptado para Cloud)")
        return
    
    # Barra lateral
    with st.sidebar:
        st.title("Relatório de Fiscalização")
        if st.session_state.agente_info:
            nome = st.session_state.agente_info.get('NOME', '')
            matricula = st.session_state.agente_info.get('MATRICULA', '')
            unidade = st.session_state.agente_info.get('UNIDADE', '')
            st.markdown(f"**Agente:** {nome}")
            st.markdown(f"**Matrícula:** {matricula}")
            st.markdown(f"**Unidade:** {unidade}")
            if st.session_state.pasta_local:
                if is_streamlit_cloud():
                    st.markdown(f"📁 **Pasta temporária:**")
                    st.caption(st.session_state.pasta_local)
                else:
                    st.markdown(f"📁 **PDFs salvos em:**")
                    st.caption(st.session_state.pasta_local)
        
        # Exibe o número do relatório (pode ser "A SER GERADO")
        st.markdown(f"**Relatório atual:** `{st.session_state.numero_relatorio_gerado}`")
        
        # Mostra ambiente atual
        if is_streamlit_cloud():
            st.info("☁️ Executando no Streamlit Cloud")
            st.warning("""
            ⚠️ **Como salvar os PDFs:**
            - Use o botão **BAIXAR PDF**
            - Salve manualmente em Documents
            """)
        else:
            st.info("💻 Executando localmente")
            st.success("✅ PDFs salvos automaticamente em Documents")
        
        if st.session_state.logged_in:
            st.markdown("---")
            if st.button("📊 Baixar Planilha Master", use_container_width=True, key="download_excel_button"):
                try:
                    drive_service = autenticar_google_drive()
                    if drive_service:
                        with st.spinner("Carregando Planilha Master..."):
                            df_dados, caminho_temp = carregar_planilha_master_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
                            if not df_dados.empty:
                                excel_data = exportar_planilha_para_download(df_dados)
                                if excel_data:
                                    b64 = base64.b64encode(excel_data).decode()
                                    href = f'''
                                    <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" 
                                       download="{EXCEL_DATABASE_NAME}" 
                                       style="background-color: #2196F3; 
                                              color: white; 
                                              padding: 10px 20px; 
                                              text-align: center; 
                                              text-decoration: none; 
                                              display: inline-block;
                                              border-radius: 5px;
                                              font-size: 14px;
                                              font-weight: bold;
                                              width: 100%;
                                              display: block;
                                      margin-top: 10px;">
                                       📥 BAIXAR PLANILHA MASTER
                                    </a>
                                    '''
                                    st.markdown(href, unsafe_allow_html=True)
                                    st.success(f"✅ Planilha Master com {len(df_dados)} registros pronto para download!")
                        
                        if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
                            try:
                                os.unlink(caminho_temp)
                            except:
                                pass
                    else:
                        st.warning("⚠️ Não foi possível conectar ao Google Drive")
                except Exception as e:
                    st.error(f"❌ Erro ao baixar dados: {str(e)}")
        
        if os.path.exists("10.png"):
            exibir_imagem_compativel("10.png", width=300)
        
        if st.button("Sair", type="secondary", use_container_width=True, key="logout_button"):
            st.session_state.logged_in = False
            st.session_state.matricula = ""
            st.session_state.numero_relatorio_gerado = "A SER GERADO"
            st.session_state.numero_sequencial = 0
            st.session_state.agente_info = None
            st.session_state.formulario_inicializado = False
            st.session_state.form_widget_counter = 0
            st.session_state.pasta_local = None
            st.session_state.contador_manager = None
            limpar_formulario()
            st.rerun()

    # Conteúdo principal
    st.title("Relatório de Fiscalização - Obra")
    
    if st.session_state.agente_info:
        nome = st.session_state.agente_info.get('NOME', '')
        matricula = st.session_state.agente_info.get('MATRICULA', '')
        unidade = st.session_state.agente_info.get('UNIDADE', '')
        st.markdown(f"**Agente de Fiscalização:** {nome} - {matricula} - {unidade}")
    
    st.markdown(f"**Número do Relatório:** `{st.session_state.numero_relatorio_gerado}`")
    
    if st.session_state.numero_relatorio_gerado == "A SER GERADO":
        st.info("ℹ️ O número do relatório será gerado automaticamente ao clicar em 'GERAR RELATÓRIO PDF'")
    
    if is_streamlit_cloud():
        st.info("""
        📁 **Instruções para salvar o PDF:**
        - Clique em **GERAR RELATÓRIO PDF**
        - Use o botão **BAIXAR PDF** que aparecerá
        - Na janela de download, navegue até **Documentos**
        - Crie a pasta **RF-CREA-RJ-MATRICULA** e salve lá
        """)
    else:
        st.markdown(f"📁 **Os PDFs serão salvos em:** `{st.session_state.pasta_local}`")
    
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
    
    # ===== DADOS GERAIS =====
    st.header("DADOS GERAIS DO RELATÓRIO")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input("Número do Relatório", 
                     value=st.session_state.numero_relatorio_gerado,
                     disabled=True,
                     key=f"numero_relatorio_display_{widget_counter}")
        situacao = st.selectbox("Situação", ["", "CADASTRADO", "EM ANDAMENTO", "CONCLUÍDO", "CANCELADO"], 
                               key=f"situacao_select_{widget_counter}")
    with col2:
        data_relatorio = st.date_input("Data do Relatório", value=datetime.now(), 
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
    
    # ===== SEÇÃO 01 =====
    st.markdown("### 01 - ENDEREÇO DO EMPREENDIMENTO")
    
    st.subheader("Coordenadas do Local")
    col_lat, col_lon = st.columns(2)
    with col_lat:
        latitude_input = st.text_input("Latitude *", placeholder="Ex: -22.550520", 
                                     key=f"latitude_input_{widget_counter}")
    with col_lon:
        longitude_input = st.text_input("Longitude *", placeholder="Ex: -43.633308", 
                                      key=f"longitude_input_{widget_counter}")
    
    st.subheader("Endereço do Empreendimento")
    col_endereco, col_numero = st.columns([3, 1])
    with col_endereco:
        endereco = st.text_input("Endereço *", placeholder="Nome completo do endereço", 
                               key=f"endereco_input_{widget_counter}")
    with col_numero:
        numero = st.text_input("Nº", placeholder="Número ou S/N", 
                             key=f"numero_input_{widget_counter}")
    
    complemento = st.text_input("Complemento/Referência", placeholder="Ponto de referência ou complemento", 
                               key=f"complemento_input_{widget_counter}")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        bairro = st.text_input("Bairro:", placeholder="Nome", 
                              key=f"bairro_input_{widget_counter}")
    with col2:
        municipio = st.selectbox("Município *", options=[""] + sorted(MUNICIPIOS_RJ), 
                               key=f"municipio_select_{widget_counter}")
    with col3:
        st.text_input("UF", value="RJ", max_chars=2, disabled=True, 
                     key=f"uf_input_{widget_counter}", placeholder="RJ")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        cep = st.text_input("CEP", placeholder="00000-000", max_chars=9, 
                           key=f"cep_input_{widget_counter}")
    with col2:
        descritivo_endereco = st.text_area("Descritivo do Endereço", 
                                          placeholder="Descrição adicional do endereço", 
                                          key=f"descritivo_endereco_textarea_{widget_counter}")
    
    # ===== SEÇÃO 02 =====
    st.markdown("### 02 - IDENTIFICAÇÃO DO PROPRIETÁRIO/CONTRATANTE")
    nome_contratante = st.text_input("Nome do Proprietário/Contratante", 
                                    placeholder="Razão social ou nome completo", 
                                    key=f"nome_contratante_input_{widget_counter}")
    col1, col2 = st.columns(2)
    with col1:
        registro_contratante = st.text_input("Registro", placeholder="Número de registro", 
                                            key=f"registro_contratante_input_{widget_counter}")
    with col2:
        cpf_cnpj = st.text_input("CPF/CNPJ", placeholder="CPF ou CNPJ", 
                                key=f"cpf_cnpj_input_{widget_counter}")
    
    constatacao_fiscal = st.text_area("Constatação do Fiscal: Possível Ilícito ", 
                                     placeholder="Utilizar para possíveis autuações", 
                                     key=f"constatacao_fiscal_textarea_{widget_counter}")
    motivo_acao = st.text_area("Motivo da Ação:", 
                              placeholder="Motivo que originou a fiscalização", 
                              key=f"motivo_acao_textarea_{widget_counter}")
    
    # ===== SEÇÃO 03 =====
    st.markdown("### 03 - ATIVIDADE DESENVOLVIDA")
    col1, col2 = st.columns(2)
    with col1:
        caracteristica = st.selectbox("Característica:", 
                                    ["", "CONSTRUÇÃO", "REFORMA", "AMPLIAÇÃO", "DEMOLIÇÃO", "MANUTENÇÃO", "OUTRAS"], 
                                    key=f"caracteristica_select_{widget_counter}")
        
        caracteristica_outros = ""
        if caracteristica == "OUTRAS":
            caracteristica_outros = st.text_input(
                "Especifique a característica:",
                placeholder="Digite a característica da atividade",
                key=f"caracteristica_outras_input_{widget_counter}"
            )
            if caracteristica_outros:
                caracteristica = caracteristica_outros
        
        fase_atividade = st.selectbox("Fase da Atividade:",
                                    ["", "FUNDAÇÃO", "REVESTIMENTO", "ACABAMENTO", "ESTRUTURA", "LAJE", "OUTRAS"], 
                                    key=f"fase_atividade_select_{widget_counter}")
        
        fase_atividade_outros = ""
        if fase_atividade == "OUTRAS":
            fase_atividade_outros = st.text_input(
                "Especifique a fase:",
                placeholder="Digite a fase da atividade",
                key=f"fase_atividade_outras_input_{widget_counter}"
            )
            if fase_atividade_outros:
                fase_atividade = fase_atividade_outros
        
        natureza = st.selectbox("Natureza:",
                               ["", "RESIDENCIAL", "COMERCIAL", "PÚBLICA", "MISTA", "OUTRAS"], 
                               key=f"natureza_select_{widget_counter}")
        
        natureza_outros = ""
        if natureza == "OUTRAS":
            natureza_outros = st.text_input(
                "Especifique a natureza:",
                placeholder="Digite a natureza da obra",
                key=f"natureza_outras_input_{widget_counter}"
            )
            if natureza_outros:
                natureza = natureza_outros
                
    with col2:
        num_pavimentos = st.number_input("Nº de Pavimentos:", min_value=0, value=0,
                                        key=f"num_pavimentos_input_{widget_counter}")
        quantificacao = st.text_input("Quantificação:", placeholder="Ex: 5000",
                                     key=f"quantificacao_input_{widget_counter}")
        unidade_medida = st.selectbox("Unidade de Medida:",
                                    ["", "Metro", "m²", "m³", "UN", "Kg", "TON", "KVA", "Km", "OUTRAS"], 
                                    key=f"unidade_medida_select_{widget_counter}")
        
        unidade_medida_outros = ""
        if unidade_medida == "OUTRAS":
            unidade_medida_outros = st.text_input(
                "Especifique a unidade de medida:",
                placeholder="Digite a unidade de medida",
                key=f"unidade_medida_outras_input_{widget_counter}"
            )
            if unidade_medida_outros:
                unidade_medida = unidade_medida_outros
        
        tipo_construcao = st.selectbox("Tipo de Construcao:",
                                     [" ", "ALVENARIA e CONCRETO", "CONCRETO", "ALVENARIA", "METÁLICA", "MISTA", "MADEIRA", "OUTRAS"], 
                                     key=f"tipo_construcao_select_{widget_counter}")
        
        tipo_construcao_outros = ""
        if tipo_construcao == "OUTRAS":
            tipo_construcao_outros = st.text_input(
                "Especifique o tipo de construção:",
                placeholder="Digite o tipo de construção",
                key=f"tipo_construcao_outras_input_{widget_counter}"
            )
            if tipo_construcao_outros:
                tipo_construcao = tipo_construcao_outros
    
    # ===== SEÇÃO 04 =====
    st.markdown("### 04 - IDENTIFICAÇÃO DOS CONTRATADOS, RESPONSÁVEIS TÉCNICOS")
    
    st.markdown(f"#### 📝 Registro Atual: {st.session_state.registro_counter}")
    
    current_data = st.session_state.current_registro
    
    st.subheader(f"Identificação do Contratante - Registro {st.session_state.registro_counter}")
    st.markdown("**A identificação do Contratante é a mesma do campo 02?**")
    
    col_sim, col_nao = st.columns(2)
    with col_sim:
        sim_checkbox = st.checkbox("SIM", value=(current_data.get('mesmo_contratante') == "SIM"),
                                 key=f"mesmo_contratante_sim_{widget_counter}_{secao04_counter}")
    with col_nao:
        nao_checkbox = st.checkbox("NÃO", value=(current_data.get('mesmo_contratante') == "NÃO"),
                                 key=f"mesmo_contratante_nao_{widget_counter}_{secao04_counter}")
    
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
            nome_contratante_secao04 = st.text_input("Nome do Contratante *",
                value=current_data.get('nome_contratante_secao04', ''),
                placeholder="Razão social ou nome completo",
                key=f"nome_contratante_secao04_input_{widget_counter}_{secao04_counter}"
            )
            current_data['nome_contratante_secao04'] = nome_contratante_secao04
        with col_registro:
            registro_contratante_secao04 = st.text_input("Registro *",
                value=current_data.get('registro_contratante_secao04', ''),
                placeholder="Número de registro",
                key=f"registro_contratante_secao04_input_{widget_counter}_{secao04_counter}"
            )
            current_data['registro_contratante_secao04'] = registro_contratante_secao04
        with col_cpf:
            cpf_cnpj_secao04 = st.text_input("CPF/CNPJ *",
                value=current_data.get('cpf_cnpj_secao04', ''),
                placeholder="CPF ou CNPJ",
                key=f"cpf_cnpj_secao04_input_{widget_counter}_{secao04_counter}"
            )
            current_data['cpf_cnpj_secao04'] = cpf_cnpj_secao04
        
        if (nome_contratante_secao04 == "" or registro_contratante_secao04 == "" or cpf_cnpj_secao04 == ""):
            st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!**")
    else:
        current_data['nome_contratante_secao04'] = ""
        current_data['registro_contratante_secao04'] = ""
        current_data['cpf_cnpj_secao04'] = ""
    
    st.subheader(f"Dados do Contratado/Responsável Técnico - Registro {st.session_state.registro_counter}")
    
    col1, col2 = st.columns(2)
    with col1:
        contratado_pf_pj = st.text_input("Contratado/Responsável Técnico:",
                                       value=current_data.get('contratado_pf_pj', ''),
                                       key=f"contratado_pf_pj_{widget_counter}_{secao04_counter}",
                                       placeholder="Nome/Razão Social")
        current_data['contratado_pf_pj'] = contratado_pf_pj
        
        registro = st.text_input("Registro:",
                               value=current_data.get('registro', ''),
                               key=f"registro_{widget_counter}_{secao04_counter}",
                               placeholder="Número de registro")
        current_data['registro'] = registro
        
        cpf_cnpj_contratado = st.text_input("CPF/CNPJ:",
                                          value=current_data.get('cpf_cnpj_contratado', ''),
                                          key=f"cpf_cnpj_{widget_counter}_{secao04_counter}",
                                          placeholder="CPF ou CNPJ do contratado")
        current_data['cpf_cnpj_contratado'] = cpf_cnpj_contratado
        
    with col2:
        contrato = st.text_input("Profissional:",
                               value=current_data.get('contrato', ''),
                               key=f"contrato_{widget_counter}_{secao04_counter}",
                               placeholder="Nome do profissional")
        current_data['contrato'] = contrato
        
        st.write("Identificação do fiscalizado:")
        identificacao_options = [" ", "Com Placa", "Sem Placa"]
        identificacao_fiscalizado = st.selectbox(
            "Selecione a identificação:",
            options=identificacao_options,
            index=identificacao_options.index(current_data.get('identificacao_fiscalizado', ' ')) if current_data.get('identificacao_fiscalizado', ' ') in identificacao_options else 0,
            key=f"identificacao_select_{widget_counter}_{secao04_counter}",
            label_visibility="collapsed"
        )
        current_data['identificacao_fiscalizado'] = identificacao_fiscalizado
        
        numero_art = st.text_input("Número ART:",
                                 value=current_data.get('numero_art', ''),
                                 key=f"art_{widget_counter}_{secao04_counter}",
                                 placeholder="Número da Anotação de Responsabilidade Técnica")
        current_data['numero_art'] = numero_art
        
        numero_rrt = st.text_input("Número RRT:",
                                 value=current_data.get('numero_rrt', ''),
                                 key=f"rrt_{widget_counter}_{secao04_counter}",
                                 placeholder="Número do Registro de Responsabilidade Técnica")
        current_data['numero_rrt'] = numero_rrt
    
    col3, col4 = st.columns(2)
    with col3:
        numero_trt = st.text_input("Número TRT:",
                                 value=current_data.get('numero_trt', ''),
                                 key=f"trt_{widget_counter}_{secao04_counter}",
                                 placeholder="Número do Termo de Responsabilidade Técnica")
        current_data['numero_trt'] = numero_trt
        
        st.write("Ramo Atividade:")
        ramo_options = ["", "1050 - Engª Civil", "2010 - Engª Elétrica", "3020 - Engª Mecânica", 
                       "4010 - Arquitetura", "5010 - Engª Florestal", "6010 - Geologia", 
                       "7010 - Segurança do Trabalho", "8010 - Química", "9010 - Agrimensura"]
        ramo_atividade = st.selectbox(
            "Selecione o ramo de atividade:",
            options=ramo_options,
            index=ramo_options.index(current_data.get('ramo_atividade', '')) if current_data.get('ramo_atividade', '') in ramo_options else 0,
            key=f"ramo_select_{widget_counter}_{secao04_counter}",
            label_visibility="collapsed"
        )
        current_data['ramo_atividade'] = ramo_atividade
        
    with col4:
        st.write("Serviço Executado:")
        atividade_options = ["", "Projeto Cálculo Estrutural", "Execução de Obra", 
                           "Projeto de Construcao", "Projeto e Execução de Obra", "Outras"]
        
        servico_executado = st.selectbox(
            "Selecione o serviço:",
            options=atividade_options,
            index=atividade_options.index(current_data.get('servico_executado', '')) if current_data.get('servico_executado', '') in atividade_options else 0,
            key=f"servico_executado_select_{widget_counter}_{secao04_counter}",
            label_visibility="collapsed"
        )
        current_data['servico_executado'] = servico_executado
        
        if 'servico_executado_outras' not in current_data:
            current_data['servico_executado_outras'] = ''
        
        if servico_executado == "Outras":
            servico_executado_outras = st.text_input(
                "Especifique o serviço:",
                value=current_data.get('servico_executado_outras', ''),
                placeholder="Digite o serviço personalizado",
                key=f"servico_executado_outras_input_{widget_counter}_{secao04_counter}"
            )
            current_data['servico_executado_outras'] = servico_executado_outras
        else:
            current_data['servico_executado_outras'] = ''
        
        st.markdown("---")
        st.write("**Fonte de Informação e Qualificação:**")
        
        fonte_informacao_secao04 = st.text_input(
            "Fonte de Informação:",
            value=current_data.get('fonte_informacao_secao04', ''),
            placeholder="Digite a fonte da informação",
            key=f"fonte_informacao_secao04_input_{widget_counter}_{secao04_counter}"
        )
        current_data['fonte_informacao_secao04'] = fonte_informacao_secao04
        
        qualificacao_opcoes = ["", "PROPRIETÁRIO", "RESPONSÁVEL TÉCNICO", "MESTRE DE OBRA", "OUTRAS"]
        qualificacao_fonte_secao04 = st.selectbox(
            "Qualificação da Fonte:",
            options=qualificacao_opcoes,
            index=qualificacao_opcoes.index(current_data.get('qualificacao_fonte_secao04', '')) if current_data.get('qualificacao_fonte_secao04', '') in qualificacao_opcoes else 0,
            key=f"qualificacao_fonte_secao04_select_{widget_counter}_{secao04_counter}"
        )
        current_data['qualificacao_fonte_secao04'] = qualificacao_fonte_secao04
        
        qualificacao_outras_secao04 = ""
        if qualificacao_fonte_secao04 == "OUTRAS":
            qualificacao_outras_secao04 = st.text_input(
                "Especifique a qualificação:",
                value=current_data.get('qualificacao_outras_secao04', ''),
                placeholder="Digite a qualificação da fonte",
                key=f"qualificacao_outras_input_{widget_counter}_{secao04_counter}"
            )
            current_data['qualificacao_outras_secao04'] = qualificacao_outras_secao04
            if qualificacao_outras_secao04:
                current_data['qualificacao_fonte_secao04'] = qualificacao_outras_secao04
    
    # Atualiza o session_state com todos os dados atuais
    st.session_state.current_registro = current_data.copy()
    
    st.markdown("---")
    if st.button("SALVAR", type="primary", use_container_width=True,
               key=f"salvar_registro_button_{widget_counter}_{secao04_counter}"):
        
        if st.session_state.current_registro.get('mesmo_contratante') is None:
            st.error("❌ **Campo obrigatório:** Selecione SIM ou NÃO para a pergunta sobre o contratante")
            st.stop()
        
        if st.session_state.current_registro.get('mesmo_contratante') == "NÃO":
            if (not st.session_state.current_registro.get('nome_contratante_secao04') or
                not st.session_state.current_registro.get('registro_contratante_secao04') or
                not st.session_state.current_registro.get('cpf_cnpj_secao04')):
                st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!**")
                st.stop()
        
        current_data = st.session_state.current_registro.copy()
        
        if current_data.get('servico_executado') == "Outras" and current_data.get('servico_executado_outras'):
            current_data['servico_executado'] = "Outras"
        
        sucesso, total_registros = salvar_registro_atual(current_data)
        
        if sucesso:
            st.session_state.current_registro = limpar_campos_secao_04()
            st.session_state.registro_counter += 1
            st.session_state.secao04_limpa_counter += 1
            st.success(f"✅ Registro {st.session_state.registro_counter - 1} salvo com sucesso!")
            st.info(f"Próximo registro: {st.session_state.registro_counter}")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("❌ Erro ao salvar registro. Tente novamente.")
    
    # ===== SEÇÕES 05-06 =====
    st.markdown("### 05 - DOCUMENTOS SOLICITADOS / EXPEDIDOS")
    
    col_doc1, col_doc2 = st.columns(2)
    
    with col_doc1:
        st.subheader("Documentos Solicitados/Expedidos")
        st.markdown("**Ofício:**")
        
        circular_solicitado = st.checkbox("Nº", key=f"circular_solicitado_checkbox_{widget_counter}")
        quadro_tecnico_solicitado = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_solicitado_checkbox_{widget_counter}")
        prestadores_servicos_solicitado = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_solicitado_checkbox_{widget_counter}")
        outros_solicitado = st.checkbox("Outros", key=f"outros_solicitado_checkbox_{widget_counter}")
        
        circular_numero = ""
        if circular_solicitado:
            circular_numero = st.text_input("Número do Ofício:", placeholder="Digite o número do Ofício",
                                          key=f"circular_numero_input_{widget_counter}")
        
        outros_texto_solicitado = ""
        if outros_solicitado:
            outros_texto_solicitado = st.text_input("Especifique 'Outros':", placeholder="Descreva outros documentos solicitados/expedidos",
                                                  key=f"outros_solicitado_input_{widget_counter}")
        
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
        st.markdown("**Ofício:**")
        
        circular_recebido = st.checkbox("Nº", key=f"circular_recebido_checkbox_{widget_counter}")
        quadro_tecnico_recebido = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_recebido_checkbox_{widget_counter}")
        prestadores_servicos_recebido = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_recebido_checkbox_{widget_counter}")
        outros_recebido = st.checkbox("Outros", key=f"outros_recebido_checkbox_{widget_counter}")
        
        circular_numero_recebido = ""
        if circular_recebido:
            circular_numero_recebido = st.text_input("Número do Ofício:", placeholder="Digite o número do Ofício",
                                                   key=f"circular_numero_recebido_input_{widget_counter}")
        
        quadro_tecnico_quantidade = ""
        if quadro_tecnico_recebido:
            quadro_tecnico_quantidade = st.text_input("Quantidade (Quadro Técnico):", placeholder="Quantidade",
                                                    key=f"quadro_tecnico_quantidade_input_{widget_counter}")
        
        prestadores_quantidade = ""
        if prestadores_servicos_recebido:
            prestadores_quantidade = st.text_input("Quantidade (Prestadores de Serviços Técnicos):", placeholder="Quantidade",
                                                 key=f"prestadores_quantidade_input_{widget_counter}")
        
        outros_texto_recebido = ""
        if outros_recebido:
            outros_texto_recebido = st.text_input("Especifique 'Outros':", placeholder="Descreva outros documentos recebidos",
                                                key=f"outros_recebido_input_{widget_counter}")
        
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
    
    # ===== SEÇÃO 07 =====
    st.markdown("### 07 - OUTRAS INFORMAÇÕES")
    data_relatorio_anterior = st.text_input("Data do Relatório Anterior", 
                                          placeholder="Data do relatório anterior se houver", 
                                          key=f"data_relatorio_anterior_input_{widget_counter}")
    informacoes_complementares = st.text_area("Informações Complementares", 
                                            placeholder="Informações adicionais sobre a fiscalização", 
                                            key=f"informacoes_complementares_textarea_{widget_counter}")
    
    fonte_informacao = st.text_input("Fonte de Informação:", placeholder="Fonte da informação",
                                   key=f"fonte_informacao_input_{widget_counter}")
    
    qualificacao_fonte = st.selectbox("Qualificação da Fonte:", 
                                    ["", "PROPRIETÁRIO", "RESPONSÁVEL TÉCNICO", "MESTRE DE OBRA", "OUTRAS"],
                                    key=f"qualificacao_fonte_select_{widget_counter}")
    
    qualificacao_outros = ""
    if qualificacao_fonte == "OUTRAS":
        qualificacao_outros = st.text_input("Especifique a qualificação:",
                                          placeholder="Digite a qualificação da fonte",
                                          key=f"qualificacao_outras_input_{widget_counter}")
        if qualificacao_outros:
            qualificacao_fonte = qualificacao_outros
    
    # ===== SEÇÃO 08 =====
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
                    exibir_imagem_compativel(img, caption="Pré-visualização da foto capturada")
                except:
                    pass
        
        with col_controls:
            st.write("**Controles da Foto**")
            novo_comentario = st.text_area("Comentário para esta foto:", max_chars=200, height=100,
                                         key=f"novo_comentario_input_{widget_counter}",
                                         placeholder="Digite um comentário para esta foto...")
            chars_used = len(novo_comentario)
            st.caption(f"Caracteres: {chars_used}/200")
            
            col_save1, col_save2 = st.columns(2)
            with col_save1:
                if st.button("💾 Salvar Foto", use_container_width=True,
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
                if st.button("🔄 Nova Foto", use_container_width=True,
                           key=f"nova_foto_button_{widget_counter}"):
                    st.session_state.temp_photo_bytes = None
                    st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
                    st.rerun()
            
            st.markdown("---")
            st.write("**Dicas:**")
            st.write("1. Tire a foto")
            st.write("2. Adicione um comentário (opcional)")
            st.write("3. Clique em 'Salvar Foto'")
            st.write("4. Repita para cada foto")
    
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
                        exibir_imagem_compativel(img, caption=f"Foto {i+1}")
                    except:
                        st.write(f"Arquivo {i+1}")
            
            upload_comentario = st.text_area("Comentário para todas as fotos (opcional):",
                                           max_chars=200, height=80,
                                           key=f"upload_comentario_geral_{widget_counter}",
                                           placeholder="Este comentário será aplicado a todas as fotos...")
            
            col_process1, col_process2 = st.columns(2)
            with col_process1:
                if st.button("📤 Adicionar Todas as Fotos", type="primary", use_container_width=True,
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
                if st.button("🗑️ Limpar Seleção", type="secondary", use_container_width=True,
                           key=f"limpar_selecao_upload_{widget_counter}"):
                    st.rerun()
    
    with tab3:
        st.subheader("Visualizar e Gerenciar Fotos")
        total_fotos = len(st.session_state.fotos_info)
        
        if total_fotos == 0:
            st.warning("Nenhuma foto registrada ainda.")
            st.info("Use as abas '📷 Capturar Fotos' ou '📁 Upload de Fotos' para adicionar fotos.")
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
                    if st.button("⬅️ Anterior", disabled=current_foto_idx == 0,
                               use_container_width=True, key=f"nav_anterior_gestao_{widget_counter}"):
                        st.session_state.current_foto_index = max(0, current_foto_idx - 1)
                        st.rerun()
                with col_counter:
                    st.markdown(f"### Foto {current_foto_idx + 1} de {len(fotos_exibidas)}")
                with col_next:
                    if st.button("Próxima ➡️", disabled=current_foto_idx == len(fotos_exibidas) - 1,
                               use_container_width=True, key=f"nav_proxima_gestao_{widget_counter}"):
                        st.session_state.current_foto_index = min(len(fotos_exibidas) - 1, current_foto_idx + 1)
                        st.rerun()
            with col_info:
                st.write("**Ações:**")
                if st.button("🗑️ Remover", type="secondary", use_container_width=True,
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
                    exibir_imagem_compativel(img, caption=f"Foto {current_foto_idx + 1} - Preview")
                except Exception as e:
                    st.error(f"Erro ao carregar foto: {e}")
            with col_comentario:
                st.write("**Comentário:**")
                comentario_edit = st.text_area("Editar comentário:", value=foto_atual.comentario,
                                             max_chars=200, height=150,
                                             key=f"comentario_edit_{current_foto_idx}_{widget_counter}",
                                             label_visibility="collapsed")
                chars_used = len(comentario_edit)
                chars_left = 200 - chars_used
                st.caption(f"Caracteres: {chars_used}/200 ({chars_left} restantes)")
                if st.button("💾 Salvar Comentário", use_container_width=True,
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
                        exibir_imagem_compativel(img, caption=f"{indicador_atual} Foto {i+1} {indicador_comentario}")
                        if st.button(f"Selecionar #{i+1}", key=f"select_thumb_{i}_{widget_counter}",
                                   use_container_width=True):
                            st.session_state.current_foto_index = i
                            st.rerun()
                    except:
                        st.error(f"Erro na foto {i+1}")
            
            if total_fotos > 5:
                st.markdown("---")
                st.write("**Ações em Lote:**")
                col_batch1, col_batch2 = st.columns(2)
                with col_batch1:
                    if st.button("🗑️ Remover Todas", type="secondary", use_container_width=True,
                               key=f"remover_todas_fotos_{widget_counter}"):
                        if st.checkbox("Confirmar remoção de TODAS as fotos", key=f"confirmar_remocao_{widget_counter}"):
                            st.session_state.fotos_info = []
                            st.session_state.current_foto_index = 0
                            st.success("Todas as fotos foram removidas!")
                            time.sleep(0.5)
                            st.rerun()
    
    # ===== BOTÕES DE AÇÃO =====
    st.markdown("---")
    col_gerar1, col_gerar2, col_gerar3 = st.columns([1, 1, 1])
    
    with col_gerar1:
        if st.button("📄 GERAR RELATÓRIO PDF", type="primary", use_container_width=True,
                   key=f"gerar_relatorio_final_{widget_counter}"):
            
            # Verificação dos campos obrigatórios
            if not latitude_input or not longitude_input:
                st.error("❌ Campos obrigatórios: Latitude e Longitude devem ser preenchidos")
                st.stop()
            if not endereco:
                st.error("❌ Campo obrigatório: Endereço deve ser preenchido")
                st.stop()
            if not municipio:
                st.error("❌ Campo obrigatório: Município deve ser selecionado")
                st.stop()
            
            # Verifica se há dados não salvos na Seção 04
            current_registro = st.session_state.current_registro
            tem_dados_atuais = False
            for key, value in current_registro.items():
                if value and key not in ['identificacao_fiscalizado', 'servico_executado_outras']:
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
                        st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!**")
                        st.stop()
                
                current_data_copy = current_registro.copy()
                
                sucesso, total_registros = salvar_registro_atual(current_data_copy)
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
            
            # GERA O NÚMERO DO RELATÓRIO APENAS AGORA!
            if st.session_state.contador_manager:
                numero_completo, numero_seq = st.session_state.contador_manager.gerar_novo_numero(
                    st.session_state.matricula
                )
                st.session_state.numero_relatorio_gerado = numero_completo
                st.session_state.numero_sequencial = numero_seq
            
            # Processamento dos documentos
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
            
            documentos_solicitados = " | ".join(documentos_solicitados_list) if documentos_solicitados_list else "SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS"
            
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
            
            documentos_recebidos = " | ".join(documentos_recebidos_list) if documentos_recebidos_list else "SEM DOCUMENTOS RECEBIDOS"
            
            # Prepara o dicionário de dados
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
                'quadro_tecnico_solicitado': quadro_tecnico_solicitado,
                'prestadores_servicos_solicitado': prestadores_servicos_solicitado,
                'outros_solicitado': outros_solicitado,
                'documentos_solicitados_text': documentos_solicitados_text,
                'quadro_tecnico_recebido': quadro_tecnico_recebido,
                'prestadores_servicos_recebido': prestadores_servicos_recebido,
                'outros_recebido': outros_recebido,
                'documentos_recebidos_text': documentos_recebidos_text
            }
            
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                status_text.text("🔄 Preparando dados...")
                progress_bar.progress(10)
                
                status_text.text("📄 Criando PDF...")
                pdf = criar_pdf(dados, "10.png" if os.path.exists("10.png") else None, 
                              st.session_state.fotos_info, st.session_state.agente_info)
                progress_bar.progress(40)
                
                status_text.text("💾 Salvando PDF...")
                caminho_pdf = salvar_pdf_adaptado(
                    pdf, 
                    st.session_state.matricula, 
                    st.session_state.numero_relatorio_gerado
                )
                
                if caminho_pdf:
                    progress_bar.progress(70)
                    
                    status_text.text("📊 Atualizando Planilha Master na nuvem...")
                    
                    drive_service = autenticar_google_drive()
                    
                    excel_sucesso = False
                    if drive_service:
                        excel_sucesso = adicionar_relatorio_a_planilha_master(
                            dados_relatorio=dados,
                            agente_info=st.session_state.agente_info,
                            fotos_info=st.session_state.fotos_info,
                            service=drive_service,
                            folder_id=GOOGLE_DRIVE_FOLDER_ID,
                            tipo_visita_outros=tipo_visita_outros,
                            caracteristica_outros=caracteristica_outros,
                            fase_atividade_outros=fase_atividade_outros,
                            unidade_medida_outros=unidade_medida_outros,
                            natureza_outros=natureza_outros,
                            tipo_construcao_outros=tipo_construcao_outros,
                            circular_numero=circular_numero,
                            outros_texto_solicitado=outros_texto_solicitado,
                            circular_numero_recebido=circular_numero_recebido,
                            quadro_tecnico_quantidade=quadro_tecnico_quantidade,
                            prestadores_quantidade=prestadores_quantidade,
                            outros_texto_recebido=outros_texto_recebido,
                            qualificacao_outros=qualificacao_outros
                        )
                        
                        if excel_sucesso:
                            progress_bar.progress(90)
                            st.success("✅ Dados do relatório adicionados à Planilha Master na nuvem!")
                        else:
                            st.warning("⚠️ Dados do PDF gerados, mas não foi possível atualizar a Planilha Master na nuvem.")
                    else:
                        st.warning("⚠️ Não foi possível conectar ao Google Drive para atualizar a Planilha Master.")
                    
                    progress_bar.progress(100)
                    status_text.text("✅ Relatório pronto!")
                    
                    fotos_com_comentarios = sum(1 for foto in st.session_state.fotos_info if foto.comentario.strip())
                    total_registros = len(st.session_state.contratados_data)
                    
                    resumo_texto = f"""
                    **📊 Resumo Final:**
                    - **Número do relatório:** {st.session_state.numero_relatorio_gerado}
                    - **Agente:** {st.session_state.agente_info['NOME'] if st.session_state.agente_info else 'N/A'}
                    - **Total de fotos:** {total_fotos}
                    - **Fotos com comentários:** {fotos_com_comentarios}
                    - **Registros de contratados:** {total_registros}
                    """
                    
                    if is_streamlit_cloud():
                        resumo_texto += f"\n- **📁 Pasta temporária:** {caminho_pdf}"
                    else:
                        resumo_texto += f"\n- **📁 PDF salvo em:** {caminho_pdf}"
                    
                    if excel_sucesso:
                        resumo_texto += "\n- **📊 Planilha Master:** Dados atualizados com sucesso na nuvem!"
                    
                    st.info(resumo_texto)
                    
                    st.markdown("---")
                    st.subheader("📊 Planilha Master na Nuvem")
                    st.info(f"Os dados deste relatório foram adicionados à Planilha Master no Google Drive.")
                    
                    if st.button("📥 Baixar Planilha Master da Nuvem", key=f"download_master_excel_{widget_counter}",
                               use_container_width=True):
                        drive_service = autenticar_google_drive()
                        if drive_service:
                            with st.spinner("Carregando Planilha Master..."):
                                df_dados, caminho_temp = carregar_planilha_master_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
                                if not df_dados.empty:
                                    excel_data = exportar_planilha_para_download(df_dados)
                                    if excel_data:
                                        b64_excel = base64.b64encode(excel_data).decode()
                                        href_excel = f'''
                                        <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64_excel}" 
                                           download="{EXCEL_DATABASE_NAME}" 
                                           style="background-color: #2196F3; 
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
                                                  margin-top: 10px;">
                                           📥 BAIXAR PLANILHA MASTER ({len(df_dados)} registros)
                                        </a>
                                        '''
                                        st.markdown(href_excel, unsafe_allow_html=True)
                                        
                                        with st.expander("📊 Estatísticas da Planilha Master"):
                                            st.write(f"**Total de registros:** {len(df_dados)}")
                                            if 'DATA_GERACAO' in df_dados.columns:
                                                ultima_data = df_dados['DATA_GERACAO'].max() if not df_dados['DATA_GERACAO'].empty else 'N/A'
                                                st.write(f"**Última atualização:** {ultima_data}")
                                            if 'AGENTE_NOME' in df_dados.columns:
                                                agentes_unicos = df_dados['AGENTE_NOME'].nunique()
                                                st.write(f"**Agentes distintos:** {agentes_unicos}")
                                        
                                        with st.expander("📋 Visualizar Dados da Planilha Master"):
                                            st.dataframe(df_dados)
                                    
                                    if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
                                        try:
                                            os.unlink(caminho_temp)
                                        except:
                                            pass
                                else:
                                    st.warning("Planilha Master vazia ou não encontrada")
                        else:
                            st.warning("⚠️ Não foi possível conectar ao Google Drive para baixar a Planilha Master.")
                    
                    progress_bar.empty()
                    status_text.empty()
                
            except Exception as e:
                st.error(f"❌ Erro ao gerar relatório: {str(e)}")
                if 'progress_bar' in locals():
                    progress_bar.empty()
                if 'status_text' in locals():
                    status_text.empty()
    
    with col_gerar2:
        if st.button("🔄 NOVO RELATÓRIO", type="secondary", use_container_width=True,
                   key=f"novo_relatorio_button_{widget_counter}"):
            
            # Mantém o mesmo contador_manager, mas não gera número ainda
            limpar_formulario()
            st.session_state.formulario_inicializado = False
            st.session_state.registro_counter = 1
            st.session_state.current_registro = limpar_campos_registro()
            st.session_state.contratados_data = []
            st.session_state.secao04_limpa_counter = 0
            st.session_state.form_widget_counter += 1
            st.session_state.numero_relatorio_gerado = "A SER GERADO"
            st.session_state.numero_sequencial = 0
            st.success(f"✅ Novo relatório iniciado!")
            if not is_streamlit_cloud():
                st.info(f"📁 Os PDFs serão salvos em: {st.session_state.pasta_local}")
            time.sleep(1)
            st.rerun()
    
    with col_gerar3:
        if st.button("🗑️ LIMPAR FORMULÁRIO", type="secondary", use_container_width=True,
                   key=f"limpar_formulario_button_{widget_counter}"):
            limpar_formulario()
            st.session_state.formulario_inicializado = False
            st.session_state.registro_counter = 1
            st.session_state.current_registro = limpar_campos_registro()
            st.session_state.contratados_data = []
            st.session_state.secao04_limpa_counter = 0
            st.session_state.form_widget_counter += 1
            st.success("✅ Formulário limpo! Mantendo o mesmo número de relatório.")
            st.info("Todos os campos foram limpos. Você pode preencher novamente.")
            time.sleep(0.5)
            st.rerun()

if __name__ == "__main__":
    main()