from typing import Self

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
    page_title="Relatório de Diligência",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== CONFIGURAÇÃO GOOGLE DRIVE ==========
SCOPES = ['https://www.googleapis.com/auth/drive']
GOOGLE_DRIVE_FOLDER_ID = "119n021EjT2ilcc7ajUejGLv7mk7Gz8GI"
SHARED_DRIVE_ID = "0AExAXm3UxqZFUk9PVA"
EXCEL_DATABASE_NAME = "Planilha Master.xlsx"
CONTADOR_FILENAME = "contador_relatorios.json"
SENHAS_FILENAME = "Senhas.xlsx"

# ========== FUNÇÃO PARA SUBSTITUIR CARACTERES ESPECIAIS ==========
def remover_acentos(texto):
    """
    Substitui caracteres especiais não suportados pela fonte Helvetica do FPDF
    por equivalentes suportados.
    """
    if not isinstance(texto, str):
        return str(texto) if texto is not None else ""
    
    # Mapeamento de caracteres especiais para equivalentes suportados
    substituicoes = {
        'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n',
        'Á': 'A', 'À': 'A', 'Â': 'A', 'Ã': 'A', 'Ä': 'A',
        'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
        'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
        'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Õ': 'O', 'Ö': 'O',
        'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
        'Ç': 'C', 'Ñ': 'N',
        'º': 'o', 'ª': 'a',
        '—': '-', '–': '-',
        '“': '"', '”': '"', '‘': "'", '’': "'",
        '\u2013': '-',  # meia risca (en dash) para hífen
        '\u2014': '-',  # travessão (em dash) para hífen
        '\u2018': "'",  # aspas simples esquerda para aspas simples
        '\u2019': "'",  # aspas simples direita para aspas simples
        '\u201C': '"',  # aspas duplas esquerda para aspas duplas
        '\u201D': '"',  # aspas duplas direita para aspas duplas
        '\u2026': '...',  # reticências para três pontos
    }
    
    for char_especial, char_normal in substituicoes.items():
        texto = texto.replace(char_especial, char_normal)
    
    return texto

# ========== FUNÇÃO PARA ADICIONAR FONTE UNICODE AO PDF ==========
def adicionar_fonte_unicode(pdf):
    """Adiciona suporte a Unicode/acentos no PDF usando DejaVu"""
    try:
        # Tenta usar a fonte DejaVu que suporta acentos
        from fpdf.fonts import FontFace
        # Caminho para a fonte no sistema
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf", 
            "C:\\Windows\\Fonts\\DejaVuSans.ttf",
            os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf")
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                pdf.add_font('DejaVu', '', font_path, uni=True)
                return 'DejaVu'
    except Exception as e:
        pass
    return 'helvetica'

# ========== DADOS DAS MULTAS (SANITIZADOS) ==========
INFRACOES_PF = [
    "",
    "1115- Pessoas Fisicas Leigas executando atividades privativas de profissionais fiscalizados pelo sistema Confea/Crea Enquadramento art. 6o, alinea \"a\", da Lei Federal no 5.104/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"d\" da Lei Federal no 5.194/66",
    "1116- Profissionais fiscalizados pelo Sistema CONFEA / Crea executando atividades sem possuir registro Enquadramento art. 55 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"b\" da Lei Federal no 5.194/66",
    "1102- Exercicio ilegal por exercer atv. estranhas as suas atribuicoes Enquadramento art. 6o, alinea \"b\" da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"b\" da Lei Federal no 5.194/66",
    "1103- Exercicio ilegal por emprestar seu nome sem sua real participacao nos trabalhos executados Enquadramento art. 6o, alinea \"c\" da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"d\" da Lei Federal no 5.194/66",
    "1104- Exercicio ilegal por continuar em atividade, mesmo suspenso do exercicio Enquadramento art. 6o, alinea \"d\" da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"d\" da Lei Federal no 5.194/66",
    "1117- Nao manutencao de placa visivel e legivel ao publico Enquadramento art. 16 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "1118- Falta de Anotacao de Responsabilidade Tecnica - ART Enquadramento art. 1o da Lei Federal no 6.496/77 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "1119- Falta de visto Enquadramento art. 58 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "1113- Uso indevido do titulo Inobservancia do: art. 3o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "1114 - Contratacao e permissao de participar em licitacao sem prova de quitacao de debito com o Crea Enquadramento art. 68 e 69 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66"
]

INFRACOES_PJ = [
    "",
    "3207- Nao manutencao de placa visivel e legivel ao publico Enquadramento art. 16 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "3208 - Falta de Anotacao de Responsabilidade Tecnica - ART Enquadramento art. 1o da Lei Federal o 6.496/77 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "3111 - Falta de Anotacao de Responsabilidade Tecnica - ART, relativa aos servicos de Enga de Seguranca do Trabalho Trabalho relativa aos servicos de Enga de Seguranca do Trabalho Enquadramento: art. 1o da Lei Federal no 6.496/77 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "3210 - Exercicio ilegal por falta de participacao de profissional registrado no CREA-RJ Enquadramento art. 6o, alinea \"e\" da Lei Federal no 5.194/66 Inobservancia do: art. 59 e 60 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"e\" da Lei Federal no 5.195/66 Combinado com: § unico do art. 8o da Lei Federal no 5.194/66",
    "3214 - Uso de denominacao social sem Diretoria composta, em sua maioria, por profissionais registrados no CREA- RJ Inobservancia do: art. 4o e 5o da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "3215 - Falta de pagamento do salario minimo profissional enquadramento art 82 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66 Combinado com: Lei Federal no 4.950-A/66",
    "3225 - Pessoa Juridica com objetivo social relacionado as atividades privativas de profissionais fiscalizados pelo sistema CONFEA / Crea's sem registro Enquadramento art. 59 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"c\" da Lei Federal no 5.194/66",
    "3226 - Pessoa Juridica que possua secao que execute para terceiros atividades privativas de profissionais fiscalizados pelo sistema CONFEA / Crea's, sem registro Enquadramento art 60 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"c\" da Lei Federal no 5.194/66",
    "3227 - Pessoa Juridica sem objetivo social relacionado ao atividades Privativas de Profissionais fiscalizados pelo sistema CONFEA / Crea's Enquadramento art. 6o, alinea \"a\" da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"e\" da Lei Federal no 5.194/66 Combinado com: § unico do art. 8o da Lei Federal no 5.194/66",
    "3219- Falta do visto no CREA-RJ Enquadramento art. 58 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66",
    "3222 - Recusa de informacoes Enquadramento paragrafo 2o do art. 59 da Lei Federal no 5.194/66 No exercicio atv. prevista no paragrafo unico do art. 8o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"c\" da Lei Federal no 5.194/66",
    "- Exercicio ilegal pela nao participacao de profissional registrado no CREA-RJ Enquadramento art. 6o, alinea \"e\" da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"e\" da Lei Federal no 5.194/66 Combinado com: § unico do art. 8o da Lei Federal no 5.194/66",
    "3224 - Contratacao e permissao de participar em licitacao sem prova de quitacao de debito com o Crea. Enquadramento art. 68 e 69 da Lei Federal no 5.194/66 No exercicio atv. previstas no: art. 7o da Lei Federal no 5.194/66 Fundamento legal: art. 73, alinea \"a\" da Lei Federal no 5.194/66"
]

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

# ========== FUNÇÃO PARA CARREGAR SENHAS DO GOOGLE DRIVE (CORRIGIDA) ==========
@st.cache_data(ttl=300)  # Cache de 5 minutos
def carregar_senhas_do_drive(_service):
    """
    Carrega o arquivo de senhas do Google Drive e retorna um dicionário
    com matrícula como chave e senha como valor
    O parâmetro _service tem underscore para não ser hasheado pelo cache
    """
    try:
        if not _service:
            return None
        
        caminho_temp = baixar_arquivo_do_drive(_service, SENHAS_FILENAME, GOOGLE_DRIVE_FOLDER_ID)
        
        if not caminho_temp:
            return None
        
        # Lê o arquivo Excel
        df = pd.read_excel(caminho_temp, sheet_name='DADOS FISCAIS')
        
        # Remove arquivo temporário
        try:
            os.unlink(caminho_temp)
        except:
            pass
        
        # Verifica se as colunas necessárias existem
        colunas_necessarias = ['MATRICULA', 'SENHA']
        for coluna in colunas_necessarias:
            if coluna not in df.columns:
                st.error(f"Coluna '{coluna}' não encontrada no arquivo Senhas.xlsx")
                return None
        
        # Converte matrícula para string e remove espaços
        df['MATRICULA'] = df['MATRICULA'].astype(str).str.strip()
        df['SENHA'] = df['SENHA'].astype(str).str.strip()
        
        # Filtra linhas com dados válidos
        df = df[df['MATRICULA'].notna() & (df['MATRICULA'] != '') & 
                df['SENHA'].notna() & (df['SENHA'] != '')]
        
        # Cria dicionário de senhas
        senhas_dict = {}
        for _, row in df.iterrows():
            matricula = str(row['MATRICULA']).strip()
            senhas_dict[matricula] = str(row['SENHA']).strip()
        
        return senhas_dict
        
    except Exception as e:
        st.error(f"❌ Erro ao carregar senhas do Drive: {str(e)}")
        return None

# ========== FUNÇÃO PARA VERIFICAR CREDENCIAIS ==========
def verificar_credenciais(matricula, senha, senhas_dict):
    """
    Verifica se a matrícula e senha fornecidas correspondem aos dados do arquivo
    """
    if not senhas_dict:
        return False, "Erro ao carregar dados de senha"
    
    # Formata a matrícula para busca (remover zeros à esquerda para comparar)
    matricula_busca = matricula.lstrip('0')
    
    # Tenta encontrar a matrícula no dicionário
    for matricula_registro, senha_registro in senhas_dict.items():
        matricula_registro_limpa = matricula_registro.lstrip('0')
        
        if matricula_busca == matricula_registro_limpa:
            if senha == senha_registro:
                return True, "Credenciais válidas"
            else:
                return False, "Senha incorreta"
    
    return False, "Matrícula não encontrada"

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
        Retorna o número gerado com prefixo RD- e atualiza o contador permanentemente
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
        numero_base = f"{ano}{matricula_formatada}{contador_formatado}"
        numero_com_prefixo = f"RD-{numero_base}"
        
        return numero_com_prefixo, proximo_numero

# ========== FUNÇÕES PARA GERENCIAMENTO DA PLANILHA MASTER (NA NUVEM) ==========
def inicializar_planilha_master():
    colunas = [
        'NUMERO_RELATORIO', 'SITUACAO', 'DATA_RELATORIO', 'FATO_GERADOR', 'PROTOCOLO', 'TIPO_ACAO',
        'TIPO_ACAO_OUTROS',
        'LATITUDE', 'LONGITUDE', 'ENDERECO', 'NUMERO_ENDERECO', 'COMPLEMENTO', 'BAIRRO',
        'MUNICIPIO', 'UF', 'CEP', 'DESCRITIVO_ENDERECO',
        'NOME_CONTRATANTE', 'REGISTRO_CONTRATANTE', 'CPF_CNPJ_CONTRATANTE',
        'APURADO_INTRODUCAO', 'APURADO_APURADO', 'APURADO_CONCLUSAO',
        'INFORMACOES_COMPLEMENTARES',
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
                                         qualificacao_outros=""):
    try:
        df_existente, caminho_temp = carregar_planilha_master_drive(service, folder_id)
        
        novos_dados = preparar_dados_para_planilha_master(
            dados_relatorio, agente_info, fotos_info, qualificacao_outros
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

def preparar_dados_para_planilha_master(dados, agente_info, fotos_info, qualificacao_outros=""):
    
    dados_excel = {
        'NUMERO_RELATORIO': dados.get('numero_relatorio', ''),
        'SITUACAO': dados.get('situacao', ''),
        'DATA_RELATORIO': dados.get('data_relatorio', ''),
        'FATO_GERADOR': dados.get('fato_gerador', ''),
        'PROTOCOLO': dados.get('protocolo', ''),
        'TIPO_ACAO': dados.get('tipo_visita', ''),
        'TIPO_ACAO_OUTROS': "",
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
        'NOME_CONTRATANTE': dados.get('nome_interessado', ''),
        'REGISTRO_CONTRATANTE': dados.get('registro_interessado', ''),
        'CPF_CNPJ_CONTRATANTE': dados.get('cpf_cnpj', ''),
        'APURADO_INTRODUCAO': dados.get('apurado_introducao', ''),
        'APURADO_APURADO': dados.get('apurado_apurado', ''),
        'APURADO_CONCLUSAO': dados.get('apurado_conclusao', ''),
        'INFORMACOES_COMPLEMENTARES': dados.get('informacoes_complementares', ''),
        'FONTE_INFORMACAO': dados.get('fonte_informacao', ''),
        'QUALIFICACAO_FONTE': dados.get('qualificacao_fonte', ''),
        'QUALIFICACAO_FONTE_OUTROS': qualificacao_outros if dados.get('qualificacao_fonte') == "OUTRAS" else "",
        'TOTAL_FOTOS': len(fotos_info),
        'FOTOS_COM_COMENTARIOS': sum(1 for foto in fotos_info if foto.comentario.strip()),
        'AGENTE_NOME': agente_info.get('NOME', '') if agente_info else '',
        'AGENTE_MATRICULA': agente_info.get('MATRICULA', '') if agente_info else '',
        'AGENTE_UNIDADE': agente_info.get('UNIDADE', '') if agente_info else '',
        'DATA_GERACAO': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
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

# ========== CLASSE PDF COM CABEÇALHO COM LOGO E SUPORTE A ACENTOS ==========
class RelatorioPDF(FPDF):
    def __init__(self, logo_path=None, agente_info=None):
        super().__init__()
        self.logo_path = logo_path
        self.agente_info = agente_info
        self.set_auto_page_break(auto=True, margin=20)
        self.set_left_margin(10)
        self.set_right_margin(10)
        
        # Tenta adicionar fonte com suporte a Unicode
        self.fonte_unicode = adicionar_fonte_unicode(self)

    def _safe(self, texto):
        """Remove acentos e caracteres especiais (fallback)"""
        if not isinstance(texto, str):
            return str(texto) if texto is not None else ""
        return texto

    def header(self):
        """Cabeçalho do PDF com logo"""
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                largura_total = 210
                from PIL import Image as PILImage
                img = PILImage.open(self.logo_path)
                largura_original, altura_original = img.size
                altura_proporcional = (largura_total / largura_original) * altura_original
                altura_mm = altura_proporcional * 0.264583
                self.image(self.logo_path, x=0, y=5, w=largura_total)
                self.set_y(5 + altura_mm + 40)
            except Exception as e:
                self.set_y(25)
        else:
            self.set_y(25)

        self.set_font(fonte_usar, 'B', 14)
        self.cell(190, 10, 'RELATÓRIO DE DILIGÊNCIA', 0, 1, 'C')
        
        if self.agente_info:
            self.set_font(fonte_usar, '', 9)
            nome = self.agente_info.get('NOME', '')
            matricula = self.agente_info.get('MATRICULA', '')
            unidade = self.agente_info.get('UNIDADE', '')
            texto_agente = f"Agente: {nome} - {matricula} - {unidade}"
            self.cell(190, 5, texto_agente, 0, 1, 'C')
        self.ln(8)

    def footer(self):
        """Rodapé do PDF"""
        self.set_y(-15)
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        self.set_font(fonte_usar, 'I', 8)
        self.cell(190, 10, f'Página {self.page_no()}', 0, 1, 'C')

    def campo(self, label, valor):
        """Adiciona um campo com label e valor"""
        if valor is None or str(valor).strip() == "":
            return

        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        
        self.set_font(fonte_usar, 'B', 10)
        label_text = f"{label}:"
        label_width = 55
        x_inicial = self.get_x()

        self.cell(label_width, 6, label_text, 0, 0, 'L')
        self.set_x(x_inicial + label_width + 2)

        self.set_font(fonte_usar, '', 10)
        value_text = str(valor)
        self.multi_cell(133, 6, value_text, 0, 'L')
        self.ln(2)

    def campo_texto_longo(self, label, valor, altura_linha=6):
        """Método específico para campos de texto longo"""
        if valor is None or str(valor).strip() == "":
            return
        
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        
        self.set_font(fonte_usar, 'B', 10)
        label_text = f"{label}:"
        self.multi_cell(190, altura_linha, label_text, 0, 'L')
        
        self.set_font(fonte_usar, '', 10)
        value_text = str(valor)
        
        self.set_x(10)
        self.write(altura_linha, value_text)
        self.ln(8)
        self.set_x(10)

    def titulo_secao(self, texto):
        """Adiciona um título de seção com fundo cinza"""
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        self.set_font(fonte_usar, 'B', 11)
        self.set_fill_color(200, 200, 200)
        self.multi_cell(190, 8, texto, 0, 'L', fill=True)
        self.ln(4)

    def add_images_to_pdf(self, fotos_info):
        """
        Adiciona imagens ao PDF - cada foto em uma página separada
        A foto ocupa 60% da página e o comentário os 40% restantes
        """
        if not fotos_info:
            return
        
        # Dimensões da página A4 em mm: 210mm x 297mm
        altura_total_pagina = 297
        margem_superior = 50  # Espaço para cabeçalho + título da seção
        margem_inferior = 30  # Espaço para rodapé
        area_disponivel = altura_total_pagina - margem_superior - margem_inferior  # ~217mm
        
        # Define a proporção: 60% para imagem, 40% para comentário
        percentual_imagem = 0.60
        percentual_comentario = 0.40
        
        altura_max_imagem = area_disponivel * percentual_imagem
        altura_max_comentario = area_disponivel * percentual_comentario
        
        max_width = 180  # Largura máxima da imagem (centralizada)
        
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        
        for i, foto_info in enumerate(fotos_info, 1):
            # Adiciona uma nova página para cada foto
            self.add_page()
            
            # Título da seção para cada foto
            self.titulo_secao(f"04 - FOTOS REGISTRADAS - Foto {i}")
            
            self.set_font(fonte_usar, 'B', 10)
            self.cell(190, 6, f"Foto {i}:", 0, 1, 'L')
            
            # Processa a imagem
            img = foto_info.get_image()
            img_width, img_height = img.size
            
            # Converte pixels para mm
            width_mm = img_width * 0.264583
            height_mm = img_height * 0.264583
            
            # Calcula o tamanho da imagem respeitando a altura máxima (60% da página)
            if height_mm > altura_max_imagem:
                # Redimensiona para caber na altura máxima
                ratio = altura_max_imagem / height_mm
                new_height_mm = altura_max_imagem
                new_width_mm = width_mm * ratio
            else:
                new_height_mm = height_mm
                new_width_mm = width_mm
            
            # Se a largura ultrapassar o máximo, redimensiona novamente
            if new_width_mm > max_width:
                ratio = max_width / new_width_mm
                new_width_mm = max_width
                new_height_mm = new_height_mm * ratio
            
            # Converte de volta para pixels para redimensionar a imagem
            new_width_px = int(new_width_mm / 0.264583)
            new_height_px = int(new_height_mm / 0.264583)
            
            # Redimensiona a imagem
            img_resized = img.resize((new_width_px, new_height_px), Image.Resampling.LANCZOS)
            
            # Salva temporariamente
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_img:
                img_resized.save(temp_img.name, 'JPEG', quality=85)
                temp_img_path = temp_img.name
            
            # Centraliza a imagem horizontalmente
            x_position = (210 - new_width_mm) / 2
            y_position = self.get_y()
            
            # Adiciona a imagem
            self.image(temp_img_path, x=x_position, y=y_position, w=new_width_mm)
            
            # Move o cursor para depois da imagem
            self.set_y(y_position + new_height_mm + 10)
            
            # Remove arquivo temporário
            try:
                os.unlink(temp_img_path)
            except:
                pass
            
            # Área para o comentário (40% restantes)
            # Calcula quanto espaço ainda resta até o final da página
            espaco_restante = altura_total_pagina - self.get_y() - margem_inferior
            
            # Adiciona o comentário
            self.ln(5)
            
            # Comentário
            if foto_info.comentario and foto_info.comentario.strip():
                self.set_font(fonte_usar, 'I', 10)
                comentario = foto_info.comentario
                
                # Calcula a altura necessária para o comentário
                comentario_linhas = self.get_string_width(comentario) / 180
                altura_comentario = max(20, comentario_linhas * 6)
                
                # Se o comentário for muito longo, reduz a fonte
                if altura_comentario > espaco_restante:
                    self.set_font(fonte_usar, 'I', 8)
                    self.multi_cell(190, 5, f"Comentário: {comentario}")
                else:
                    self.multi_cell(190, 6, f"Comentário: {comentario}")
                
                self.set_font(fonte_usar, '', 10)
            else:
                self.set_font(fonte_usar, 'I', 10)
                self.cell(190, 6, "Comentário: Nenhum comentário adicionado", 0, 1, 'L')
                self.set_font(fonte_usar, '', 10)
            
            self.ln(4)

    def add_assinatura_agente(self, agente_info):
        """Adiciona a seção de assinatura do agente na mesma página, com espaçamento consistente"""
        fonte_usar = self.fonte_unicode if self.fonte_unicode else 'helvetica'
        
        # NÃO adiciona nova página - mantém na mesma página
        # Adiciona título da seção com mesmo espaçamento
        self.titulo_secao("06 - ASSINATURA DO AGENTE")
        
        # Mesmo espaçamento usado após as outras seções
        self.ln(4)
        
        self.ln(12)
        
        self.set_font(fonte_usar, '', 10)
        x_center = (210 - 120) / 2
        self.set_x(x_center)
        self.cell(120, 0, '', 'T')
        
        self.ln(4)
        
        nome_agente = agente_info.get('NOME', '') if agente_info else ''
        self.set_font(fonte_usar, 'B', 11)
        self.set_x(x_center)
        self.cell(120, 6, nome_agente, 0, 1, 'C')
        
        self.ln(1)
        
        self.set_font(fonte_usar, '', 10)
        self.set_x(x_center)
        self.cell(120, 5, "Agente de Fiscalização", 0, 1, 'C')
        
        self.ln(1)
        
        matricula_agente = agente_info.get('MATRICULA', '') if agente_info else ''
        self.set_font(fonte_usar, '', 10)
        self.set_x(x_center)
        self.cell(120, 5, f"Matrícula: {matricula_agente}", 0, 1, 'C')
        
        self.ln(8)
        self.set_font(fonte_usar, 'I', 9)
        data_atual = datetime.now().strftime('%d/%m/%Y')
        self.set_x(x_center)
        self.cell(120, 5, f"Data: {data_atual}", 0, 1, 'C')

# ========== FUNÇÕES AUXILIARES ==========
@st.cache_data(ttl=300)
def formatar_matricula(matricula):
    matricula_limpa = re.sub(r'\D', '', matricula)
    matricula_limpa = matricula_limpa[-4:] if len(matricula_limpa) > 4 else matricula_limpa
    return matricula_limpa.zfill(4)

# ========== FUNÇÃO CRIAR PDF ==========
def criar_pdf(dados, logo_path, fotos_info=None, agente_info=None):
    """
    Versão do criar_pdf com:
    - Fotos em páginas separadas (60% imagem, 40% comentário)
    - Seção 05 com caixas de texto editáveis
    - Seção 06 na mesma página, com espaçamento consistente
    """
    pdf = RelatorioPDF(logo_path=logo_path, agente_info=agente_info)
    pdf.add_page()

    # Dados Gerais
    pdf.campo("Número", dados.get('numero_relatorio', ''))
    pdf.campo("Data", dados.get('data_relatorio', ''))
    
    if dados.get('situacao'):
        pdf.campo("Situação", dados.get('situacao', ''))
    
    if dados.get('fato_gerador'):
        pdf.campo("Fato Gerador", dados.get('fato_gerador', ''))
    
    if dados.get('protocolo'):
        pdf.campo("Protocolo", dados.get('protocolo', ''))
    
    pdf.ln(4)

    # Seção 01 - Endereço
    pdf.titulo_secao("01 - ENDEREÇO DO EMPREENDIMENTO")
    
    if dados.get('latitude'):
        pdf.campo("Latitude", dados.get('latitude', ''))
    
    if dados.get('longitude'):
        pdf.campo("Longitude", dados.get('longitude', ''))
    
    endereco_completo = []
    if dados.get('endereco'):
        endereco_completo.append(dados.get('endereco'))
    if dados.get('numero'):
        endereco_completo.append(f"nº {dados.get('numero')}")
    if dados.get('complemento'):
        endereco_completo.append(dados.get('complemento'))
    
    if endereco_completo:
        pdf.campo("Endereço", ", ".join(endereco_completo))
    
    if dados.get('bairro'):
        pdf.campo("Bairro", dados.get('bairro', ''))
    
    municipio_uf = dados.get('municipio', '')
    if dados.get('uf'):
        municipio_uf += f" - {dados.get('uf')}"
    if municipio_uf:
        pdf.campo("Município", municipio_uf)
    
    if dados.get('cep'):
        pdf.campo("CEP", dados.get('cep', ''))
    
    if dados.get('descritivo_endereco'):
        pdf.campo("Descritivo", dados.get('descritivo_endereco', ''))
    
    pdf.ln(4)

    # Seção 02 - Interessado
    pdf.titulo_secao("02 - INTERESSADO")
    
    if dados.get('nome_interessado'):
        pdf.campo("Nome", dados.get('nome_interessado', ''))
    
    if dados.get('registro_interessado'):
        pdf.campo("Registro", dados.get('registro_interessado', ''))
    
    if dados.get('cpf_cnpj'):
        pdf.campo("CPF/CNPJ", dados.get('cpf_cnpj', ''))
    
    pdf.ln(4)

    # Seção 03 - APURADO
    pdf.titulo_secao("03 - APURADO")
    
    if dados.get('apurado_introducao'):
        pdf.campo_texto_longo("Introdução", dados.get('apurado_introducao', ''))
    
    if dados.get('apurado_apurado'):
        pdf.campo_texto_longo("O que foi apurado", dados.get('apurado_apurado', ''))
    
    if dados.get('apurado_conclusao'):
        pdf.campo_texto_longo("Conclusão", dados.get('apurado_conclusao', ''))
    
    pdf.ln(4)

    # Seção 04 - Fotos - Cada foto em página separada (60% imagem, 40% comentário)
    if fotos_info:
        pdf.add_images_to_pdf(fotos_info)
    else:
        pdf.titulo_secao("04 - FOTOS REGISTRADAS")
        pdf.campo("", "NÃO INFORMADO")
        pdf.ln(4)

    # Seção 05 - OUTRAS INFORMAÇÕES
    pdf.add_page()
    pdf.titulo_secao("05 - OUTRAS INFORMAÇÕES")
    
    # Informações Complementares
    info_complementar = dados.get('informacoes_complementares', '')
    pdf.campo_texto_longo("Informações Complementares", info_complementar if info_complementar else "NÃO INFORMADO")
    
    # Fonte de Informação
    fonte_info = dados.get('fonte_informacao', '')
    pdf.campo("Fonte de Informação", fonte_info if fonte_info else "NÃO INFORMADO")
    
    # Qualificação da Fonte
    qualificacao_fonte = dados.get('qualificacao_fonte', '')
    pdf.campo("Qualificação da Fonte", qualificacao_fonte if qualificacao_fonte else "NÃO INFORMADO")
    
    # Espaçamento consistente antes da seção 06 (mesmo padrão usado entre as seções)
    pdf.ln(8)

    # Seção 06 - Assinatura (agora na mesma página, com espaçamento consistente)
    if agente_info:
        pdf.add_assinatura_agente(agente_info)

    return pdf

# ========== FUNÇÕES PARA LIMPAR FORMULÁRIO ==========
def limpar_formulario():
    if 'fotos_info' in st.session_state:
        st.session_state.fotos_info = []
    if 'current_foto_index' not in st.session_state:
        st.session_state.current_foto_index = 0
    if 'temp_photo_bytes' in st.session_state:
        st.session_state.temp_photo_bytes = None
    if 'camera_counter' not in st.session_state:
        st.session_state.camera_counter = 0
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    st.session_state.form_widget_counter += 1

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
    if 'current_foto_index' not in st.session_state:
        st.session_state.current_foto_index = 0
    if 'temp_photo_bytes' not in st.session_state:
        st.session_state.temp_photo_bytes = None
    if 'camera_counter' not in st.session_state:
        st.session_state.camera_counter = 0
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    if 'pasta_local' not in st.session_state:
        st.session_state.pasta_local = None
    if 'contador_manager' not in st.session_state:
        st.session_state.contador_manager = None
    if 'senhas_dict' not in st.session_state:
        st.session_state.senhas_dict = None
    if 'fato_gerador_outro' not in st.session_state:
        st.session_state.fato_gerador_outro = ""
    
    dados_fiscais = carregar_dados_fiscais()
    
    # Página de login
    if not st.session_state.logged_in:
        st.title("Relatório de Diligência")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if os.path.exists("26.png"):
                exibir_imagem_compativel("26.png", width=300)
            else:
                st.markdown("🔒")
            
            # Campos de login
            matricula_input = st.text_input(
                "Matrícula (3-4 dígitos)",
                placeholder="Ex: 496 ou 0496",
                key="login_matricula"
            )
            
            senha_input = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite sua senha",
                key="login_senha"
            )
            
            # Botão de login
            if st.button("Entrar", type="primary", use_container_width=True, key="login_button"):
                if matricula_input and senha_input:
                    matricula_limpa = re.sub(r'\D', '', matricula_input)
                    
                    if len(matricula_limpa) >= 3 and len(matricula_limpa) <= 4:
                        matricula_formatada = formatar_matricula(matricula_input)
                        
                        # Inicializa o serviço do Drive para verificar senhas
                        drive_service = autenticar_google_drive()
                        
                        if drive_service:
                            # Carrega as senhas do Drive
                            senhas_dict = carregar_senhas_do_drive(drive_service)
                            
                            if senhas_dict:
                                # Verifica as credenciais
                                senha_valida, mensagem = verificar_credenciais(
                                    matricula_limpa, senha_input, senhas_dict
                                )
                                
                                if senha_valida:
                                    # Busca informações do agente no arquivo Fiscais.xlsx
                                    agente_info = None
                                    if dados_fiscais:
                                        if matricula_formatada in dados_fiscais:
                                            agente_info = dados_fiscais[matricula_formatada]
                                        elif matricula_limpa in dados_fiscais:
                                            agente_info = dados_fiscais[matricula_limpa]
                                    
                                    if agente_info:
                                        # Define a pasta local baseada na matrícula
                                        st.session_state.pasta_local = get_pasta_local(matricula_formatada)
                                        
                                        # Inicializa o contador
                                        contador_manager = ContadorRelatorios(
                                            service=drive_service, 
                                            folder_id=GOOGLE_DRIVE_FOLDER_ID
                                        )
                                        
                                        # Guarda os dados na sessão
                                        st.session_state.contador_manager = contador_manager
                                        st.session_state.logged_in = True
                                        st.session_state.matricula = matricula_formatada
                                        st.session_state.agente_info = agente_info
                                        st.session_state.senhas_dict = senhas_dict
                                        
                                        st.success(f"Login realizado! Agente: {agente_info['NOME']}")
                                        st.rerun()
                                    else:
                                        st.error("Matrícula encontrada, mas agente não cadastrado no sistema de fiscais.")
                                else:
                                    st.error(f"❌ {mensagem}")
                            else:
                                st.error("❌ Erro ao carregar dados de senha do Drive")
                        else:
                            st.error("❌ Não foi possível conectar ao Google Drive para verificar credenciais")
                    else:
                        st.error("Matrícula deve ter entre 3 e 4 dígitos!")
                else:
                    st.error("Preencha a matrícula e a senha!")
        
        st.markdown("Carlos Franklin - 2026")
        st.caption("Relatório de Diligência - Versão 2.3")
        return
    
    # Barra lateral
    with st.sidebar:
        st.title("Relatório de Diligência")
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
        
        # Exibe o número do relatório
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
        
        if os.path.exists("2026.png"):
            exibir_imagem_compativel("2026.png", width=300)
        
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
            st.session_state.senhas_dict = None
            limpar_formulario()
            st.rerun()

    # Conteúdo principal
    st.title("Relatório de Diligência")
    
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
        st.session_state.current_foto_index = 0
        st.session_state.formulario_inicializado = True
    
    widget_counter = st.session_state.form_widget_counter
    
    # ===== DADOS GERAIS =====
    st.header("DADOS GERAIS DO RELATÓRIO")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input("Número do Relatório", 
                     value=st.session_state.numero_relatorio_gerado,
                     disabled=True,
                     key=f"numero_relatorio_display_{widget_counter}")
        situacao = st.selectbox("Situação", ["", "PARALISADA", "EM ANDAMENTO", "OUTRO"], 
                               key=f"situacao_select_{widget_counter}")
    with col2:
        data_relatorio = st.date_input("Data do Relatório", value=datetime.now(), 
                                      format="DD/MM/YYYY",
                                      key=f"data_relatorio_input_{widget_counter}")
        
        # ===== SELECTBOX PARA FATO GERADOR COM OPÇÃO "OUTRO" =====
        opcoes_fato_gerador = [
            "", 
            "Denúncia Identificada", 
            "Denúncia Anônima", 
            "Ministério Público", 
            "Certidão de Acervo Técnico",
            "Outro"
        ]
        
        fato_gerador_selecionado = st.selectbox(
            "Fato Gerador", 
            options=opcoes_fato_gerador,
            key=f"fato_gerador_select_{widget_counter}"
        )
        
        # Se "Outro" for selecionado, exibe caixa de texto para digitar
        if fato_gerador_selecionado == "Outro":
            fato_gerador_outro = st.text_input(
                "Especifique o Fato Gerador",
                value=st.session_state.fato_gerador_outro,
                placeholder="Digite o fato gerador...",
                key=f"fato_gerador_outro_input_{widget_counter}"
            )
            fato_gerador = fato_gerador_outro if fato_gerador_outro else "Outro"
            st.session_state.fato_gerador_outro = fato_gerador_outro
        else:
            fato_gerador = fato_gerador_selecionado
            st.session_state.fato_gerador_outro = ""
        
    with col3:
        protocolo = st.text_input("Protocolo", placeholder="Número do protocolo", 
                                 key=f"protocolo_input_{widget_counter}")
    
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
    st.markdown("### 02 - INTERESSADO")
    nome_contratante = st.text_input("Nome do Interessado", 
                                    placeholder="Razão social ou nome completo", 
                                    key=f"nome_interessado_input_{widget_counter}")
    col1, col2 = st.columns(2)
    with col1:
        registro_contratante = st.text_input("Registro", placeholder="Número de registro", 
                                            key=f"registro_interessado_input_{widget_counter}")
    with col2:
        cpf_cnpj = st.text_input("CPF/CNPJ", placeholder="CPF ou CNPJ", 
                                key=f"cpf_cnpj_input_{widget_counter}")
    
    # ===== SEÇÃO 03 - APURADO =====
    st.markdown("### 03 - APURADO")
    apurado_introducao = st.text_area("Introdução:", 
                                      placeholder="Contextualização inicial do que motivou a fiscalização",
                                      key=f"apurado_introducao_textarea_{widget_counter}",
                                      height=100)
    apurado_apurado = st.text_area("O que foi apurado:", 
                                   placeholder="Descrição detalhada do que foi verificado e constatado durante a fiscalização",
                                   key=f"apurado_apurado_textarea_{widget_counter}",
                                   height=150)
    apurado_conclusao = st.text_area("Conclusão:", 
                                     placeholder="Conclusão final sobre a fiscalização realizada",
                                     key=f"apurado_conclusao_textarea_{widget_counter}",
                                     height=100)
    
    # ===== SEÇÃO 04 - FOTOS =====
    st.markdown("### 04 - FOTOS - REGISTRO FOTOGRÁFICO")
    
    if 'temp_photo_bytes' not in st.session_state:
        st.session_state.temp_photo_bytes = None
    
    tab1, tab2, tab3 = st.tabs(["📷 Capturar Fotos", "📁 Upload de Fotos", "📋 Visualizar e Gerenciar"])
    
    with tab1:
        st.subheader("Sistema de Captura de Fotos")
        
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
    
    # ===== CAIXAS DE TEXTO DA SEÇÃO 05 =====
    st.markdown("### 05 - OUTRAS INFORMAÇÕES")
    informacoes_complementares = st.text_area("Informações Complementares:", 
                                              placeholder="Informações adicionais relevantes...",
                                              key=f"informacoes_complementares_{widget_counter}",
                                              height=100)
    fonte_informacao = st.text_input("Fonte de Informação:", 
                                     placeholder="Ex: Denunciante, fiscalização, etc.",
                                     key=f"fonte_informacao_{widget_counter}")
    qualificacao_fonte = st.text_input("Qualificação da Fonte:", 
                                       placeholder="Ex: Testemunha, documento, etc.",
                                       key=f"qualificacao_fonte_{widget_counter}")
    
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
            
            # Prepara o dicionário de dados
            dados = {
                'numero_relatorio': st.session_state.numero_relatorio_gerado,
                'situacao': situacao,
                'data_relatorio': data_relatorio.strftime('%d/%m/%Y'),
                'fato_gerador': fato_gerador,
                'protocolo': protocolo,
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
                'nome_interessado': nome_contratante,
                'registro_interessado': registro_contratante,
                'cpf_cnpj': cpf_cnpj,
                'apurado_introducao': apurado_introducao,
                'apurado_apurado': apurado_apurado,
                'apurado_conclusao': apurado_conclusao,
                'informacoes_complementares': informacoes_complementares,
                'fonte_informacao': fonte_informacao,
                'qualificacao_fonte': qualificacao_fonte
            }
            
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                status_text.text("🔄 Preparando dados...")
                progress_bar.progress(10)
                
                status_text.text("📄 Criando PDF...")
                pdf = criar_pdf(dados, "2026.png" if os.path.exists("2026.png") else None, 
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
                            qualificacao_outros=""
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
                    
                    resumo_texto = f"""
                    **📊 Resumo Final:**
                    - **Número do relatório:** {st.session_state.numero_relatorio_gerado}
                    - **Agente:** {st.session_state.agente_info['NOME'] if st.session_state.agente_info else 'N/A'}
                    - **Total de fotos:** {total_fotos}
                    - **Fotos com comentários:** {fotos_com_comentarios}
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
            
            limpar_formulario()
            st.session_state.formulario_inicializado = False
            st.session_state.form_widget_counter += 1
            st.session_state.numero_relatorio_gerado = "A SER GERADO"
            st.session_state.numero_sequencial = 0
            st.session_state.fato_gerador_outro = ""
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
            st.session_state.form_widget_counter += 1
            st.session_state.fato_gerador_outro = ""
            st.success("✅ Formulário limpo! Mantendo o mesmo número de relatório.")
            st.info("Todos os campos foram limpos. Você pode preencher novamente.")
            time.sleep(0.5)
            st.rerun()

if __name__ == "__main__":
    main()