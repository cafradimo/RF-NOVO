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

# ========== IMPORTAÇÕES DO GOOGLE DRIVE ==========
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
# Escopos necessários - acesso apenas aos arquivos criados pela app
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# ID da pasta do Google Drive (ALTERE AQUI)
GOOGLE_DRIVE_FOLDER_ID = "119n021EjT2ilcc7ajUejGLv7mk7Gz8GI"

# ========== NOME DO ARQUIVO EXCEL DE DADOS (AGORA É ÚNICO) ==========
EXCEL_DATABASE_NAME = "Planilha Master.xlsx"
FISCAIS_EXCEL_NAME = "Fiscais.xlsx"  # Nome do arquivo Excel de fiscais
LOGO_NAME = "10.png"  # Nome do arquivo do logo

# ========== FUNÇÃO COMPATÍVEL PARA EXIBIR IMAGENS ==========
def exibir_imagem_compativel(imagem, caption="", use_container=True, width=None):
    """
    Função compatível para exibir imagens em diferentes versões do Streamlit
    """
    try:
        # Versão mais recente do Streamlit
        if width is not None:
            return st.image(imagem, caption=caption, use_container_width=use_container, width=width)
        else:
            return st.image(imagem, caption=caption, use_container_width=use_container)
    except TypeError:
        try:
            # Versões intermediárias
            if width is not None:
                return st.image(imagem, caption=caption, width=width)
            else:
                return st.image(imagem, caption=caption)
        except Exception:
            # Versões antigas ou fallback
            try:
                if width is not None:
                    return st.image(imagem, caption=caption, output_format='auto', width=width)
                else:
                    return st.image(imagem, caption=caption, output_format='auto')
            except:
                return st.image(imagem, caption=caption)

# ========== CACHE PARA PERFORMANCE ==========
@st.cache_data(ttl=3600)  # Cache por 1 hora
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

# ========== CLASSE FOTOINFO (DEFINIDA NO NÍVEL GLOBAL) ==========

class FotoInfo:
    def __init__(self, image_bytes, comentario="", foto_id=None):
        self.foto_id = foto_id or str(uuid.uuid4())
        self.image_bytes = image_bytes
        self.comentario = comentario
        self.timestamp = time.time()
        self._image_obj = None
        self._thumbnail = None  # Cache para thumbnail
    
    def get_image(self):
        """Retorna objeto Image do PIL"""
        if self._image_obj is None:
            self._image_obj = Image.open(BytesIO(self.image_bytes))
        return self._image_obj
    
    def get_thumbnail(self, size=(200, 200)):
        """Retorna thumbnail em cache para preview rápido"""
        if self._thumbnail is None:
            img = self.get_image()
            self._thumbnail = img.copy()
            self._thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
        return self._thumbnail
    
    # Métodos para serialização pickle
    def __getstate__(self):
        """Retorna estado para serialização"""
        state = self.__dict__.copy()
        # Não serializar objetos de imagem
        if '_image_obj' in state:
            del state['_image_obj']
        if '_thumbnail' in state:
            del state['_thumbnail']
        return state
    
    def __setstate__(self, state):
        """Restaura estado da serialização"""
        self.__dict__.update(state)
        # Reconstruir objetos de imagem quando necessário
        self._image_obj = None
        self._thumbnail = None

# ========== FUNÇÕES DO GOOGLE DRIVE ==========

def autenticar_google_drive():
    """
    Autentica e retorna o serviço do Google Drive
    """
    creds = None
    
    # O arquivo token.json armazena os tokens de acesso
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception as e:
            st.warning(f"⚠️ Erro ao carregar token: {e}")
            creds = None
    
    # Se não houver credenciais válidas, faça login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.warning(f"⚠️ Erro ao renovar token: {e}")
                creds = None
        
        if not creds:
            # Verificar se o arquivo credentials.json existe
            if not os.path.exists('credentials.json'):
                st.error("""
                ❌ Arquivo credentials.json não encontrado!
                
                Para usar o Google Drive, você precisa:
                1. Criar um projeto no Google Cloud Console
                2. Habilitar a API do Google Drive
                3. Criar credenciais OAuth 2.0
                4. Baixar o arquivo credentials.json
                5. Colocar na mesma pasta deste aplicativo
                """)
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(
                    port=0,
                    authorization_prompt_message='Acesse este link para autorizar o aplicativo:',
                    success_message='✅ Autenticação realizada com sucesso!',
                    open_browser=True
                )
            except Exception as e:
                st.error(f"❌ Erro na autenticação: {str(e)}")
                return None
        
        # Salvar as credenciais para a próxima execução
        try:
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            st.warning(f"⚠️ Não foi possível salvar token: {e}")
    
    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        st.error(f"❌ Erro ao criar serviço do Drive: {str(e)}")
        return None

def upload_para_google_drive(caminho_arquivo, nome_arquivo, service, folder_id=None):
    """
    Faz upload de um arquivo para o Google Drive
    """
    try:
        if not os.path.exists(caminho_arquivo):
            return None
        
        # Determinar mimetype baseado na extensão do arquivo
        extensao = os.path.splitext(nome_arquivo)[1].lower()
        mimetypes = {
            '.pdf': 'application/pdf',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg'
        }
        mimetype = mimetypes.get(extensao, 'application/octet-stream')
        
        # Verificar se arquivo já existe
        query = f"name = '{nome_arquivo}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        arquivos = results.get('files', [])
        
        if arquivos:
            # Atualizar arquivo existente
            file_id = arquivos[0]['id']
            file_metadata = {'name': nome_arquivo}
            
            # Preparar o arquivo para upload
            media = MediaFileUpload(
                caminho_arquivo,
                mimetype=mimetype,
                resumable=True
            )
            
            # Fazer upload (atualizar)
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
                'description': f'{"Relatório de Fiscalização" if extensao == ".pdf" else "Planilha Master de relatórios"} gerado pelo sistema'
            }
            
            # Adicionar pasta pai se especificada
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            # Preparar o arquivo para upload
            media = MediaFileUpload(
                caminho_arquivo,
                mimetype=mimetype,
                resumable=True
            )
            
            # Fazer upload
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
        st.error(f'❌ Erro HTTP do Google Drive: {error}')
        return None
    except Exception as e:
        st.error(f'❌ Erro ao fazer upload: {str(e)}')
        return None

# ========== FUNÇÃO PARA CARREGAR DADOS DOS FISCAIS (DO ARQUIVO EXCEL) ==========

@st.cache_data(ttl=3600)
def carregar_dados_fiscais():
    """
    Carrega os dados dos fiscais do arquivo Excel Fiscais.xlsx
    Retorna dicionário com matrícula como chave
    """
    try:
        # Verificar se o arquivo existe localmente
        if os.path.exists(FISCAIS_EXCEL_NAME):
            st.info(f"📂 Carregando dados dos fiscais do arquivo local: {FISCAIS_EXCEL_NAME}")
            df_fiscais = pd.read_excel(FISCAIS_EXCEL_NAME)
        else:
            # Tentar carregar do Google Drive
            drive_service = autenticar_google_drive()
            if drive_service:
                st.info(f"📂 Carregando dados dos fiscais do Google Drive: {FISCAIS_EXCEL_NAME}")
                query = f"name = '{FISCAIS_EXCEL_NAME}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed = false"
                results = drive_service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name)'
                ).execute()
                
                arquivos = results.get('files', [])
                
                if arquivos:
                    # Baixar o arquivo
                    arquivo_id = arquivos[0]['id']
                    request = drive_service.files().get_media(fileId=arquivo_id)
                    
                    fh = BytesIO()
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                    
                    # Carregar DataFrame do Excel
                    df_fiscais = pd.read_excel(BytesIO(fh.getvalue()))
                else:
                    st.error(f"❌ Arquivo {FISCAIS_EXCEL_NAME} não encontrado no Google Drive")
                    return {}
            else:
                st.error(f"❌ Não foi possível conectar ao Google Drive e arquivo local não encontrado: {FISCAIS_EXCEL_NAME}")
                return {}
        
        # Verificar colunas necessárias
        colunas_necessarias = ['MATRICULA', 'NOME', 'UNIDADE']
        colunas_existentes = df_fiscais.columns.tolist()
        
        colunas_faltantes = [col for col in colunas_necessarias if col not in colunas_existentes]
        if colunas_faltantes:
            st.error(f"❌ Colunas faltantes no arquivo {FISCAIS_EXCEL_NAME}: {colunas_faltantes}")
            st.info(f"Colunas encontradas: {colunas_existentes}")
            return {}
        
        # Processar dados dos fiscais
        dados_fiscais = {}
        for _, row in df_fiscais.iterrows():
            matricula = str(row['MATRICULA']).strip()
            
            # Garantir que a matrícula tenha 4 dígitos
            matricula_formatada = formatar_matricula(matricula)
            
            dados_fiscais[matricula_formatada] = {
                'NOME': str(row['NOME']).strip(),
                'MATRICULA': matricula_formatada,
                'UNIDADE': str(row['UNIDADE']).strip()
            }
        
        st.success(f"✅ Dados dos fiscais carregados: {len(dados_fiscais)} fiscais disponíveis")
        return dados_fiscais
        
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados dos fiscais: {str(e)}")
        return {}

# ========== FUNÇÃO PARA CARREGAR LOGO ==========

def carregar_logo():
    """
    Carrega o logo do sistema
    """
    try:
        # Verificar se o logo existe localmente
        if os.path.exists(LOGO_NAME):
            return LOGO_NAME
        else:
            # Tentar carregar do Google Drive
            drive_service = autenticar_google_drive()
            if drive_service:
                query = f"name = '{LOGO_NAME}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents and trashed = false"
                results = drive_service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name)'
                ).execute()
                
                arquivos = results.get('files', [])
                
                if arquivos:
                    # Baixar o arquivo
                    arquivo_id = arquivos[0]['id']
                    request = drive_service.files().get_media(fileId=arquivo_id)
                    
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                        caminho_temp = temp_file.name
                        
                        fh = BytesIO()
                        downloader = MediaIoBaseDownload(fh, request)
                        done = False
                        while done is False:
                            status, done = downloader.next_chunk()
                        
                        # Salvar no arquivo temporário
                        with open(caminho_temp, 'wb') as f:
                            f.write(fh.getvalue())
                    
                    return caminho_temp
                else:
                    st.warning(f"⚠️ Logo {LOGO_NAME} não encontrado no Google Drive")
                    return None
            else:
                st.warning(f"⚠️ Logo {LOGO_NAME} não encontrado localmente")
                return None
    except Exception as e:
        st.warning(f"⚠️ Erro ao carregar logo: {str(e)}")
        return None

# ========== FUNÇÕES PARA GERENCIAMENTO DA PLANILHA MASTER ==========

def inicializar_planilha_master():
    """
    Inicializa a Planilha Master com as colunas necessárias
    Retorna o caminho do arquivo temporário
    """
    # Definir todas as colunas do banco de dados
    colunas = [
        'NUMERO_RELATORIO',
        'SITUACAO',
        'DATA_RELATORIO',
        'FATO_GERADOR',
        'PROTOCOLO',
        'TIPO_ACAO',
        'LATITUDE',
        'LONGITUDE',
        'ENDERECO',
        'NUMERO_ENDERECO',
        'COMPLEMENTO',
        'BAIRRO',
        'MUNICIPIO',
        'UF',
        'CEP',
        'DESCRITIVO_ENDERECO',
        'NOME_CONTRATANTE',
        'REGISTRO_CONTRATANTE',
        'CPF_CNPJ_CONTRATANTE',
        'CONSTATACAO_FISCAL',
        'MOTIVO_ACAO',
        'CARACTERISTICA',
        'FASE_ATIVIDADE',
        'NUM_PAVIMENTOS',
        'QUANTIFICACAO',
        'UNIDADE_MEDIDA',
        'NATUREZA',
        'TIPO_CONSTRUCAO',
        'DOCUMENTOS_SOLICITADOS',
        'DOCUMENTOS_RECEBIDOS',
        'DATA_RELATORIO_ANTERIOR',
        'INFORMACOES_COMPLEMENTARES',
        'FONTE_INFORMACAO',
        'QUALIFICACAO_FONTE',
        'TOTAL_FOTOS',
        'FOTOS_COM_COMENTARIOS',
        'AGENTE_NOME',
        'AGENTE_MATRICULA',
        'AGENTE_UNIDADE',
        'DATA_GERACAO',
        'CONTRATADOS_REGISTROS',
        'CONTRATADOS_DETALHES',
        'PDF_NOME',
        'PDF_LINK',
        'PDF_TAMANHO_MB',
        'PDF_DATA_UPLOAD'
    ]
    
    # Criar DataFrame vazio com as colunas
    df = pd.DataFrame(columns=colunas)
    
    # Salvar em arquivo temporário
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
        caminho_temp = temp_file.name
        df.to_excel(caminho_temp, index=False)
    
    return caminho_temp

def carregar_planilha_master_drive(service, folder_id):
    """
    Carrega a Planilha Master do Google Drive
    Retorna DataFrame e caminho do arquivo local
    """
    try:
        # Buscar a planilha no Google Drive
        query = f"name = '{EXCEL_DATABASE_NAME}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        arquivos = results.get('files', [])
        
        if arquivos:
            # Baixar o arquivo
            arquivo_id = arquivos[0]['id']
            request = service.files().get_media(fileId=arquivo_id)
            
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as temp_file:
                caminho_temp = temp_file.name
                
                # Baixar conteúdo
                fh = BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                
                # Salvar no arquivo temporário
                with open(caminho_temp, 'wb') as f:
                    f.write(fh.getvalue())
            
            # Carregar DataFrame
            try:
                df = pd.read_excel(caminho_temp)
            except Exception as e:
                st.warning(f"⚠️ Erro ao ler Planilha Master: {e}. Criando nova planilha...")
                caminho_temp = inicializar_planilha_master()
                df = pd.read_excel(caminho_temp)
            
            return df, caminho_temp
        else:
            # Planilha não existe, criar nova
            st.info("📊 Criando nova Planilha Master...")
            caminho_temp = inicializar_planilha_master()
            df = pd.read_excel(caminho_temp)
            return df, caminho_temp
            
    except Exception as e:
        st.error(f"❌ Erro ao carregar Planilha Master do Drive: {str(e)}")
        # Criar nova planilha em caso de erro
        caminho_temp = inicializar_planilha_master()
        df = pd.read_excel(caminho_temp)
        return df, caminho_temp

def preparar_dados_para_planilha_master(dados, agente_info, fotos_info, pdf_info=None):
    """
    Prepara os dados do relatório para serem adicionados à Planilha Master
    """
    # Processar dados dos contratados
    contratados_registros = len(dados.get('contratados_data', []))
    
    # Criar string detalhada dos contratados
    contratados_detalhes = []
    for i, contrato in enumerate(dados.get('contratados_data', []), 1):
        detalhe = f"Registro {i}: "
        if contrato.get('mesmo_contratante'):
            detalhe += f"MesmoContratante={contrato.get('mesmo_contratante')}; "
        if contrato.get('nome_contratante_secao04'):
            detalhe += f"Nome={contrato.get('nome_contratante_secao04')}; "
        if contrato.get('contrato'):
            detalhe += f"Profissional={contrato.get('contrato')}; "
        if contrato.get('registro'):
            detalhe += f"Registro={contrato.get('registro')}; "
        if contrato.get('identificacao_fiscalizado'):
            detalhe += f"Identificacao={contrato.get('identificacao_fiscalizado')}; "
        if contrato.get('ramo_atividade'):
            detalhe += f"Ramo={contrato.get('ramo_atividade')}; "
        if contrato.get('atividade_servico'):
            detalhe += f"Atividade={contrato.get('atividade_servico')}"
        contratados_detalhes.append(detalhe)
    
    # Contar fotos com comentários
    fotos_com_comentarios = sum(1 for foto in fotos_info if foto.comentario.strip())
    
    # Preparar informações do PDF
    pdf_nome = ""
    pdf_link = ""
    pdf_tamanho_mb = ""
    pdf_data_upload = ""
    
    if pdf_info:
        pdf_nome = pdf_info.get('nome', '')
        pdf_link = pdf_info.get('link_visualizacao', '')
        pdf_tamanho_bytes = pdf_info.get('tamanho_bytes', 0)
        pdf_tamanho_mb = f"{pdf_tamanho_bytes / (1024 * 1024):.2f}"
        pdf_data_upload = pdf_info.get('modificado', pdf_info.get('criado', datetime.now().isoformat()))
    
    # Preparar dicionário de dados para a Planilha Master
    dados_excel = {
        'NUMERO_RELATORIO': dados.get('numero_relatorio', ''),
        'SITUACAO': dados.get('situacao', ''),
        'DATA_RELATORIO': dados.get('data_relatorio', ''),
        'FATO_GERADOR': dados.get('fato_gerador', ''),
        'PROTOCOLO': dados.get('protocolo', ''),
        'TIPO_ACAO': dados.get('tipo_visita', ''),
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
        'FASE_ATIVIDADE': dados.get('fase_atividade', ''),
        'NUM_PAVIMENTOS': dados.get('num_pavimentos', ''),
        'QUANTIFICACAO': dados.get('quantificacao', ''),
        'UNIDADE_MEDIDA': dados.get('unidade_medida', ''),
        'NATUREZA': dados.get('natureza', ''),
        'TIPO_CONSTRUCAO': dados.get('tipo_construcao', ''),
        'DOCUMENTOS_SOLICITADOS': dados.get('documentos_solicitados', ''),
        'DOCUMENTOS_RECEBIDOS': dados.get('documentos_recebidos', ''),
        'DATA_RELATORIO_ANTERIOR': dados.get('data_relatorio_anterior', 'NAO INFORMADO'),
        'INFORMACOES_COMPLEMENTARES': dados.get('informacoes_complementares', ''),
        'FONTE_INFORMACAO': dados.get('fonte_informacao', ''),
        'QUALIFICACAO_FONTE': dados.get('qualificacao_fonte', ''),
        'TOTAL_FOTOS': len(fotos_info),
        'FOTOS_COM_COMENTARIOS': fotos_com_comentarios,
        'AGENTE_NOME': agente_info.get('NOME', '') if agente_info else '',
        'AGENTE_MATRICULA': agente_info.get('MATRICULA', '') if agente_info else '',
        'AGENTE_UNIDADE': agente_info.get('UNIDADE', '') if agente_info else '',
        'DATA_GERACAO': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'CONTRATADOS_REGISTROS': contratados_registros,
        'CONTRATADOS_DETALHES': ' | '.join(contratados_detalhes) if contratados_detalhes else 'SEM_REGISTROS',
        'PDF_NOME': pdf_nome,
        'PDF_LINK': pdf_link,
        'PDF_TAMANHO_MB': pdf_tamanho_mb,
        'PDF_DATA_UPLOAD': pdf_data_upload
    }
    
    return dados_excel

def adicionar_relatorio_a_planilha_master(dados_relatorio, agente_info, fotos_info, pdf_info, service, folder_id):
    """
    Adiciona os dados de um relatório à Planilha Master e atualiza no Google Drive
    """
    try:
        # Carregar dados existentes do Drive
        df_existente, caminho_temp = carregar_planilha_master_drive(service, folder_id)
        
        # Preparar novos dados
        novos_dados = preparar_dados_para_planilha_master(dados_relatorio, agente_info, fotos_info, pdf_info)
        
        # Verificar se o relatório já existe (pelo número)
        numero_relatorio = novos_dados['NUMERO_RELATORIO']
        
        # CORREÇÃO: Sempre adicionar como novo registro (não sobrescrever)
        # Verificar se já existe relatório com esse número
        relatorio_existente = pd.DataFrame()
        if not df_existente.empty and 'NUMERO_RELATORIO' in df_existente.columns:
            relatorio_existente = df_existente[df_existente['NUMERO_RELATORIO'] == numero_relatorio]
        
        if not relatorio_existente.empty:
            # Atualizar registro existente (mantendo histórico)
            st.info(f"📝 Atualizando registro existente: {numero_relatorio}")
            idx = df_existente[df_existente['NUMERO_RELATORIO'] == numero_relatorio].index[0]
            for col, valor in novos_dados.items():
                if col in df_existente.columns:
                    df_existente.at[idx, col] = valor
        else:
            # Adicionar novo registro
            st.info(f"➕ Adicionando novo registro: {numero_relatorio}")
            novo_df = pd.DataFrame([novos_dados])
            df_existente = pd.concat([df_existente, novo_df], ignore_index=True)
        
        # Salvar no arquivo temporário
        df_existente.to_excel(caminho_temp, index=False)
        
        # Fazer upload para o Google Drive
        drive_info = upload_para_google_drive(
            caminho_arquivo=caminho_temp,
            nome_arquivo=EXCEL_DATABASE_NAME,
            service=service,
            folder_id=folder_id
        )
        
        if drive_info:
            acao = drive_info.get('acao', 'ATUALIZADO')
            st.success(f"✅ Dados do relatório {numero_relatorio} {acao} na Planilha Master!")
            
            # Mostrar estatísticas atualizadas
            total_registros = len(df_existente)
            st.info(f"📊 Total de registros na Planilha Master: {total_registros}")
            return True
        else:
            st.warning("⚠️ Dados salvos localmente, mas não foi possível atualizar no Google Drive")
            return False
            
    except Exception as e:
        st.error(f"❌ Erro ao adicionar dados à Planilha Master: {str(e)}")
        return False
    finally:
        # Limpar arquivo temporário
        if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
            try:
                os.unlink(caminho_temp)
            except:
                pass

def exportar_planilha_para_download(df):
    """
    Exporta o DataFrame para um arquivo Excel em memória para download
    """
    try:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='RELATORIOS')
        
        excel_data = output.getvalue()
        return excel_data
    except Exception as e:
        st.error(f"Erro ao exportar Excel: {e}")
        return None

# ========== CLASSES DO SISTEMA ORIGINAL ==========

class ContadorRelatorios:
    def __init__(self, arquivo_contador="contador_relatorios.json"):
        self.arquivo_contador = arquivo_contador
        self.contadores = self.carregar_contadores()
    
    def carregar_contadores(self):
        """Carrega os contadores do arquivo JSON"""
        try:
            if os.path.exists(self.arquivo_contador):
                with open(self.arquivo_contador, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def salvar_contadores(self):
        """Salva os contadores no arquivo JSON"""
        try:
            with open(self.arquivo_contador, 'w') as f:
                json.dump(self.contadores, f)
        except Exception as e:
            st.error(f"Erro ao salvar contadores: {e}")
    
    def gerar_numero_relatorio(self, matricula):
        """Gera número de relatório no formato: AAAA + Matrícula + Contador (4 dígitos)"""
        ano = datetime.now().strftime("%Y")
        
        # Formatar matrícula com 4 dígitos
        matricula_formatada = matricula.zfill(4)
        
        # Criar chave para o contador
        chave = f"{ano}_{matricula_formatada}"
        
        # Obter ou inicializar contador
        if chave not in self.contadores:
            self.contadores[chave] = 1
        else:
            self.contadores[chave] += 1
        
        # Formatar contador com 4 dígitos
        contador_formatado = str(self.contadores[chave]).zfill(4)
        
        # Salvar contador atualizado
        self.salvar_contadores()
        
        # Retornar número completo do relatório
        return f"{ano}{matricula_formatada}{contador_formatado}"

class PDF(FPDF):
    def __init__(self, logo_path=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logo_path = logo_path
    
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
        
        # Adicionar informações do agente se disponíveis
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
        """Adiciona assinatura do agente no final do PDF"""
        if agente_info:
            self.ln(10)
            
            nome = agente_info.get('NOME', '')
            matricula = agente_info.get('MATRICULA', '')
            
            if nome:
                # Linha de assinatura
                self.cell(0, 8, '________________________________________', 0, 1, 'C')
                
                # Nome do agente
                self.set_font('Arial', 'B', 12)
                self.cell(0, 6, nome, 0, 1, 'C')
                
                # Cargo
                self.set_font('Arial', 'I', 10)
                self.cell(0, 5, 'Agente de Fiscalização', 0, 1, 'C')
                
                # Matrícula
                self.set_font('Arial', '', 10)
                if matricula:
                    self.cell(0, 5, f'Matrícula: {matricula}', 0, 1, 'C')
    
    def add_images_to_pdf(self, fotos_info):
        """
        🔥 VERSÃO OTIMIZADA - 10x MAIS RÁPIDA
        Adiciona imagens ao PDF com processamento mínimo
        """
        if not fotos_info:
            return
        
        self.add_page()
        self.set_font('Arial', 'B', 12)
        self.cell(0, 8, 'FOTOS REGISTRADAS', 0, 1, 'C')
        self.ln(5)
        
        # Dimensões máximas para PDF (mm)
        max_width = 180  # Reduzido de 180 para melhor performance
        max_height = 180
        
        for i, foto_info in enumerate(fotos_info, 1):
            try:
                if i > 1:
                    self.add_page()
                
                # ⭐⭐ OTIMIZAÇÃO 1: Carregar apenas uma vez
                img = foto_info.get_image()
                img_width, img_height = img.size
                
                # ⭐⭐ OTIMIZAÇÃO 2: Calcular tamanho direto para PDF
                # Converter pixels para mm (1 pixel ≈ 0.264583 mm em 96 DPI)
                width_mm = img_width * 0.264583
                height_mm = img_height * 0.264583
                
                # Redimensionar se muito grande
                if width_mm > max_width or height_mm > max_height:
                    ratio = min(max_width / width_mm, max_height / height_mm)
                    new_width_mm = width_mm * ratio
                    new_height_mm = height_mm * ratio
                    
                    # Calcular novos pixels
                    new_width_px = int(new_width_mm / 0.264583)
                    new_height_px = int(new_height_mm / 0.264583)
                    
                    # ⭐⭐ OTIMIZAÇÃO 3: Redimensionar apenas se necessário
                    if new_width_px < img_width or new_height_px < img_height:
                        img_resized = img.resize((new_width_px, new_height_px), 
                                                Image.Resampling.LANCZOS)
                    else:
                        img_resized = img
                else:
                    img_resized = img
                    new_width_mm = width_mm
                    new_height_mm = height_mm
                
                # ⭐⭐ OTIMIZAÇÃO 4: Salvar com qualidade otimizada
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_img:
                    # Qualidade 85% (ótimo para PDF)
                    img_resized.save(temp_img.name, 'JPEG', 
                                    quality=85, 
                                    optimize=True,
                                    subsampling=0)  # Mantém qualidade cromática
                    temp_img_path = temp_img.name
                
                # Posicionamento
                x_position = (210 - new_width_mm) / 2
                
                # Título da foto
                self.set_font('Arial', 'B', 11)
                self.cell(0, 6, f'Foto {i}', 0, 1, 'C')
                self.ln(2)
                
                # Posição Y após título
                y_position = self.get_y()
                
                # Adicionar imagem
                self.image(temp_img_path, 
                          x=x_position, 
                          y=y_position, 
                          w=new_width_mm)
                
                # Mover cursor para após a imagem
                self.set_y(y_position + new_height_mm + 4)
                
                # ⭐⭐ OTIMIZAÇÃO 5: Comentário somente se existir
                if foto_info.comentario and foto_info.comentario.strip():
                    self.ln(2)
                    self.set_font('Arial', 'I', 9)
                    
                    # Limitar tamanho do comentário no PDF
                    comentario = foto_info.comentario
                    if len(comentario) > 200:
                        comentario = comentario[:197] + "..."
                    
                    self.multi_cell(0, 4, f"Comentário: {comentario}")
                    self.set_font('Arial', '', 10)
                
                # Limpar arquivo temporário IMEDIATAMENTE
                try:
                    os.unlink(temp_img_path)
                except:
                    pass
                
                # ⭐⭐ OTIMIZAÇÃO 6: Menos espaço entre fotos
                if i < len(fotos_info):
                    self.ln(5)
                
            except Exception as e:
                # ⭐⭐ OTIMIZAÇÃO 7: Log simplificado
                self.set_font('Arial', 'I', 8)
                self.cell(0, 5, f'Foto {i}: (erro no processamento)', 0, 1)
                self.ln(2)

# ========== FUNÇÕES AUXILIARES OTIMIZADAS ==========

@st.cache_data(ttl=300)
def formatar_matricula(matricula):
    """Formata a matrícula para ter 4 dígitos"""
    matricula_limpa = re.sub(r'\D', '', matricula)
    matricula_limpa = matricula_limpa[-4:] if len(matricula_limpa) > 4 else matricula_limpa
    return matricula_limpa.zfill(4)

def calcular_largura_celula(rotulos, pdf, padding=5):
    """Calcula a largura da célula baseada no maior rótulo"""
    larguras = []
    for rotulo in rotulos:
        if rotulo:
            larguras.append(pdf.get_string_width(rotulo))
    if larguras:
        return max(larguras) + padding
    return 20

# ⭐⭐ CORREÇÃO PRINCIPAL: REMOVER CACHE DA FUNÇÃO criar_pdf
# Não use cache para funções que recebem listas complexas
def criar_pdf(dados, logo_path, fotos_info=None, agente_info=None):
    """
    🔥 FUNÇÃO SEM CACHE - Compatível com objetos complexos
    """
    pdf = PDF(logo_path=logo_path, orientation='P', unit='mm', format='A4')
    pdf.set_title("Relatório de Fiscalização")
    pdf.set_author("Sistema de Fiscalização")
    
    # Passar informações do agente para o PDF
    if agente_info:
        pdf.agente_info = agente_info
    
    pdf.add_page()
    
    # Calcular a largura máxima para todo o relatório
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
    
    # Cabeçalho do relatório
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(largura_celula, 7, 'Número:', 0, 0)  # Reduzido de 8 para 7
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('numero_relatorio', ''), 0, 1)
    
    # Situação
    if dados.get('situacao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Situação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('situacao', ''), 0, 1)
    
    # Data
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(largura_celula, 7, 'Data:', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 7, dados.get('data_relatorio', datetime.now().strftime('%d/%m/%Y')), 0, 1)
    
    # Fato Gerador
    if dados.get('fato_gerador'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Fato Gerador:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('fato_gerador', ''), 0, 1)
    
    # Protocolo
    if dados.get('protocolo'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Protocolo:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('protocolo', ''), 0, 1)
    
    # Tipo Visita
    if dados.get('tipo_visita'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 7, 'Tipo Visita:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, dados.get('tipo_visita', ''), 0, 1)
    
    pdf.ln(5)  # Reduzido espaçamento
    
    # Seção 01 - Endereço Empreendimento
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '01', 0, 0)  # Reduzido
    pdf.cell(0, 9, ' - ENDEREÇO DO EMPREENDIMENTO', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    # Latitude
    if dados.get('latitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Latitude:', 0, 0)  # Reduzido
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('latitude', ''), 0, 1)
    
    # Longitude
    if dados.get('longitude'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Longitude:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('longitude', ''), 0, 1)
    
    # Endereço completo
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
            pdf.multi_cell(0, 5, endereco_completo)  # Reduzido
        else:
            pdf.cell(0, 6, endereco_completo, 0, 1)
    
    # Município/UF
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
    
    # CEP
    if dados.get('cep'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'CEP:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cep', ''), 0, 1)
    
    # Descritivo
    if dados.get('descritivo_endereco'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Descritivo:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('descritivo_endereco', ''))
    
    pdf.ln(4)
    
    # Seção 02 - Identificação do Contratante
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '02', 0, 0)
    pdf.cell(0, 9, ' - IDENTIFICAÇÃO DO PROPRIETÁRIO/CONTRATANTE', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    # Nome
    if dados.get('nome_contratante'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Nome:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('nome_contratante', ''), 0, 1)
    
    # Registro
    if dados.get('registro_contratante'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('registro_contratante', ''), 0, 1)
    
    # CPF/CNPJ
    if dados.get('cpf_cnpj'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('cpf_cnpj', ''), 0, 1)
    
    # Constatação Fiscal
    if dados.get('constatacao_fiscal'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Constatação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('constatacao_fiscal', ''))
    
    # Motivo Ação
    if dados.get('motivo_acao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Motivo Ação:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('motivo_acao', ''))
    
    pdf.ln(4)
    
    # Seção 03 - Atividade Desenvolvida
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '03', 0, 0)
    pdf.cell(0, 9, ' - ATIVIDADE DESENVOLVIDA (OBRA, SERVIÇO, EVENTOS)', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    # Característica
    if dados.get('caracteristica'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Característica:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('caracteristica', ''), 0, 1)
    
    # Fase Atividade
    if dados.get('fase_atividade'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Fase Atividade:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('fase_atividade', ''), 0, 1)
    
    # Nº Pavimentos
    if dados.get('num_pavimentos') and dados.get('num_pavimentos') != '0':
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Nº Pavimentos:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('num_pavimentos', ''), 0, 1)
    
    # Quantificação
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
    
    # Natureza
    if dados.get('natureza'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Natureza:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('natureza', ''), 0, 1)
    
    # Tipo Construção
    if dados.get('tipo_construcao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Tipo Construção:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('tipo_construcao', ''), 0, 1)
    
    pdf.ln(4)
    
    # Seção 04 - Identificação dos Contratados
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
            
            # Adicionar seção de Identificação do Contratante para cada registro
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, 'Identificação do Contratante:', 0, 1)
            pdf.set_font('Arial', '', 10)
            
            # Verificar se a identificação é a mesma do campo 02
            mesmo_contratante = contrato.get('mesmo_contratante', '')
            
            if mesmo_contratante == "SIM":
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 6, '(Mesmo do campo 02)', 0, 1)
                pdf.set_font('Arial', '', 10)
                
                # Adicionar informações do campo 02
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
                
                # Adicionar informações específicas do registro
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
            
            # Adicionar informações do contratado
            pdf.set_font('Arial', 'B', 11)
            pdf.cell(0, 7, 'Dados do Contratado/Responsável Técnico:', 0, 1)
            pdf.set_font('Arial', '', 10)
            
            # Contratado PF/PJ
            if contrato.get('contratado_pf_pj'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Contratado PF/PJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('contratado_pf_pj', ''), 0, 1)
            
            # Registro
            if contrato.get('registro'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Registro:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('registro', ''), 0, 1)
            
            # CPF/CNPJ
            if contrato.get('cpf_cnpj_contratado'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'CPF/CNPJ:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('cpf_cnpj_contratado', ''), 0, 1)
            
            # Contrato
            if contrato.get('contrato'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Profissional:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('contrato', ''), 0, 1)
            
            # Identificação do fiscalizado
            if contrato.get('identificacao_fiscalizado'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Identificação do fiscalizado:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('identificacao_fiscalizado', ''), 0, 1)
            
            # Número ART
            if contrato.get('numero_art'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número ART:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_art', ''), 0, 1)
            
            # Número RRT
            if contrato.get('numero_rrt'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número RRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_rrt', ''), 0, 1)
            
            # Número TRT
            if contrato.get('numero_trt'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Número TRT:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('numero_trt', ''), 0, 1)
            
            # Ramo Atividade
            if contrato.get('ramo_atividade'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Ramo Atividade:', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('ramo_atividade', ''), 0, 1)
            
            # Atividade (Serviço Executado)
            if contrato.get('atividade_servico'):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(largura_celula, 6, 'Atividade (Serviço Executado):', 0, 0)
                pdf.set_font('Arial', '', 10)
                pdf.cell(0, 6, contrato.get('atividade_servico', ''), 0, 1)
            
            pdf.ln(3)
    
    pdf.ln(4)
    
    # Seções 05-06 - Documentos
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
    
    # Seção 07 - Outras Informações
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '07', 0, 0)
    pdf.cell(0, 9, ' - OUTRAS INFORMAÇÕES', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    # Data Relatório Anterior
    if dados.get('data_relatorio_anterior') and dados.get('data_relatorio_anterior') != "NAO INFORMADO":
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Data Relatório Anterior:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('data_relatorio_anterior', ''), 0, 1)
    
    # Informações Complementares
    if dados.get('informacoes_complementares'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Informações Complementares:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 5, dados.get('informacoes_complementares', ''))
    
    # Fonte Informação
    if dados.get('fonte_informacao'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Fonte Informação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('fonte_informacao', ''), 0, 1)
    
    # Qualificação Fonte
    if dados.get('qualificacao_fonte'):
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(largura_celula, 6, 'Qualificação:', 0, 0)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 6, dados.get('qualificacao_fonte', ''), 0, 1)
    
    pdf.ln(4)
    
    # Seção 08 - Fotos
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(8, 9, '08', 0, 0)
    pdf.cell(0, 9, ' - FOTOS', 0, 1)
    pdf.set_font('Arial', '', 10)
    
    if fotos_info:
        pdf.multi_cell(0, 5, f"Total de fotos registradas: {len(fotos_info)}")
    else:
        pdf.multi_cell(0, 5, 'NAO INFORMADO')
    
    pdf.ln(4)
    
    # Adicionar imagens ao PDF se existirem
    if fotos_info:
        pdf.add_images_to_pdf(fotos_info)
    
    # Adicionar assinatura do agente
    if agente_info:
        pdf.add_assinatura_agente(agente_info)
    
    return pdf

# ========== FUNÇÃO PARA LIMPAR FORMULÁRIO ==========

def limpar_formulario():
    """Limpa todos os campos do formulário"""
    # Limpar dados das fotos
    if 'fotos_info' in st.session_state:
        st.session_state.fotos_info = []
    
    # Limpar contratados
    if 'contratados_data' in st.session_state:
        st.session_state.contratados_data = []
    
    # Limpar índices
    if 'current_contratado_index' in st.session_state:
        st.session_state.current_contratado_index = 0
    
    if 'current_foto_index' in st.session_state:
        st.session_state.current_foto_index = 0
    
    # Limpar documentos
    if 'documentos_solicitados_text' not in st.session_state:
        st.session_state.documentos_solicitados_text = ""
    
    if 'documentos_recebidos_text' not in st.session_state:
        st.session_state.documentos_recebidos_text = ""
    
    # Limpar foto temporária
    if 'temp_photo_bytes' in st.session_state:
        st.session_state.temp_photo_bytes = None
    
    # Limpar contador da câmera
    if 'camera_counter' in st.session_state:
        st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
    
    # Limpar chaves de widgets que armazenam estados dos campos de entrada
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    st.session_state.form_widget_counter += 1

# ========== FUNÇÃO PARA SALVAR REGISTRO ATUAL ==========

def salvar_registro_atual(dados_registro):
    """
    Salva o registro atual na lista de contratados_data
    """
    try:
        # Garantir que temos a lista de contratados_data
        if 'contratados_data' not in st.session_state:
            st.session_state.contratados_data = []
        
        # Adicionar ou atualizar o registro
        st.session_state.contratados_data.append(dados_registro.copy())
        
        # Mostrar contador de registros
        total_registros = len(st.session_state.contratados_data)
        
        return True, total_registros
    except Exception as e:
        st.error(f"Erro ao salvar registro: {e}")
        return False, 0

# ========== FUNÇÃO PARA LIMPAR CAMPOS DO REGISTRO ==========

def limpar_campos_registro():
    """
    Retorna um dicionário vazio para limpar os campos do registro
    """
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

# ========== FUNÇÃO PARA LIMPAR APENAS OS CAMPOS DA SEÇÃO 04 ==========

def limpar_campos_secao_04():
    """
    Função específica para limpar apenas os campos da seção 04
    Retorna dicionário vazio para limpar campos da seção 04
    """
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

# ========== FUNÇÃO PRINCIPAL COMPLETA ==========

def main():
    # ========== INICIALIZAÇÃO DE TODAS AS VARIÁVEIS DO SESSION_STATE ==========
    # Verificar se o usuário está logado
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
    
    # Inicializar estados do formulário
    if 'formulario_inicializado' not in st.session_state:
        st.session_state.formulario_inicializado = False
    
    # Inicializar estados dos dados do formulário
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
    
    # Inicializar estados temporários
    if 'temp_photo_bytes' not in st.session_state:
        st.session_state.temp_photo_bytes = None
    if 'camera_counter' not in st.session_state:
        st.session_state.camera_counter = 0
    
    # Contador para widgets do formulário - CRÍTICO PARA LIMPAR FORMULÁRIO
    if 'form_widget_counter' not in st.session_state:
        st.session_state.form_widget_counter = 0
    
    # Contador de registros para mostrar
    if 'registro_counter' not in st.session_state:
        st.session_state.registro_counter = 1
    
    # Novo contador para limpar apenas campos da seção 04
    if 'secao04_limpa_counter' not in st.session_state:
        st.session_state.secao04_limpa_counter = 0
    
    # Carregar dados dos fiscais (do arquivo Excel)
    dados_fiscais = carregar_dados_fiscais()
    
    # Carregar logo
    logo_path = carregar_logo()
    
    # Inicializar gerenciador de contadores
    contador_manager = ContadorRelatorios()
    
    # Página de login se não estiver logado
    if not st.session_state.logged_in:
        st.title("Relatório de Fiscalização")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            # Exibir o logo
            if logo_path:
                try:
                    exibir_imagem_compativel(logo_path, width=300)
                except Exception as e:
                    st.warning(f"⚠️ Não foi possível carregar o logo: {e}")
            else:
                st.markdown("🔒 SISTEMA DE FISCALIZAÇÃO")
            
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
                        
                        # Verificar se a matrícula existe nos dados do Excel
                        agente_info = None
                        if dados_fiscais:
                            # Tentar encontrar com matrícula formatada
                            if matricula_formatada in dados_fiscais:
                                agente_info = dados_fiscais[matricula_formatada]
                            else:
                                # Tentar encontrar com matrícula sem formatação
                                if matricula_limpa in dados_fiscais:
                                    agente_info = dados_fiscais[matricula_limpa]
                                else:
                                    # Tentar encontrar com matrícula formatada de 4 dígitos
                                    matricula_4digitos = matricula_limpa.zfill(4)
                                    if matricula_4digitos in dados_fiscais:
                                        agente_info = dados_fiscais[matricula_4digitos]
                        
                        if agente_info:
                            # Verificar senha (qualquer senha funciona para teste)
                            # Em produção, você pode adicionar uma coluna SENHA no Excel
                            senha_hash = str(hash(senha_input))[-4:].zfill(4)
                            numero_relatorio = contador_manager.gerar_numero_relatorio(matricula_formatada)
                            
                            st.session_state.logged_in = True
                            st.session_state.matricula = matricula_formatada
                            st.session_state.senha_hash = senha_hash
                            st.session_state.numero_relatorio_gerado = numero_relatorio
                            st.session_state.agente_info = agente_info
                            
                            st.success(f"✅ Login realizado! Agente: {agente_info['NOME']}")
                            st.info(f"📄 Número do relatório gerado: {numero_relatorio}")
                            st.rerun()
                        else:
                            st.error("❌ Matrícula não encontrada no sistema de fiscais.")
                            
                            # Mostrar fiscais disponíveis se o arquivo foi carregado
                            if dados_fiscais:
                                st.info("📋 Matrículas disponíveis:")
                                for matricula, info in list(dados_fiscais.items())[:10]:  # Mostrar apenas os primeiros 10
                                    st.write(f"- **{matricula}**: {info['NOME']} - {info['UNIDADE']}")
                                
                                if len(dados_fiscais) > 10:
                                    st.write(f"... e mais {len(dados_fiscais) - 10} fiscais")
                            else:
                                st.error(f"❌ Não foi possível carregar o arquivo {FISCAIS_EXCEL_NAME}")
                                st.info(f"Verifique se o arquivo {FISCAIS_EXCEL_NAME} existe localmente ou no Google Drive.")
                    else:
                        st.error("❌ Matrícula deve ter entre 3 e 4 dígitos!")
                else:
                    st.error("❌ Preencha matrícula e senha!")
            
            # Informações para login de teste
            with st.expander("ℹ️ Informações do Sistema"):
                st.write("**Sistema de Relatório de Fiscalização**")
                st.write(f"**Versão:** 1.0")
                st.write(f"**Desenvolvido por:** Carlos Franklin")
                st.write(f"**Ano:** 2025")
                st.write("")
                st.write("**Arquivos necessários:**")
                st.write(f"1. **{FISCAIS_EXCEL_NAME}**: Lista de fiscais (MATRICULA, NOME, UNIDADE)")
                st.write(f"2. **{LOGO_NAME}**: Logo do sistema")
                st.write(f"3. **{EXCEL_DATABASE_NAME}**: Planilha master de relatórios (criada automaticamente)")
        
        st.markdown("Carlos Franklin - 2025")
        st.caption("Relatório de Fiscalização - Versão 1.0")
        return
    
    # Barra lateral com menu
    with st.sidebar:
        st.title("Relatório de Fiscalização")
        
        # Exibir o logo no sidebar
        if logo_path:
            try:
                exibir_imagem_compativel(logo_path, width=250)
            except Exception as e:
                st.warning(f"⚠️ Logo não disponível: {e}")
        else:
            st.warning("Logo não encontrado")
        
        # Mostrar informações do agente
        if st.session_state.agente_info:
            nome = st.session_state.agente_info.get('NOME', '')
            matricula = st.session_state.agente_info.get('MATRICULA', '')
            unidade = st.session_state.agente_info.get('UNIDADE', '')
            
            st.markdown(f"**Agente:** {nome}")
            st.markdown(f"**Matrícula:** {matricula}")
            st.markdown(f"**Unidade:** {unidade}")
        
        st.markdown(f"**Relatório atual:** {st.session_state.numero_relatorio_gerado}")
        
        # Seção de configuração do Google Drive
        with st.expander("☁️ Configuração Google Drive"):
            st.info("Envie relatórios automaticamente para a nuvem")
            
            # Verificar se há credenciais
            if os.path.exists('credentials.json'):
                st.success("✅ Credenciais encontradas")
            else:
                st.warning("⚠️ Arquivo credentials.json não encontrado")
                st.info("Para usar o Google Drive, você precisa do arquivo credentials.json")
            
            if os.path.exists('token.json'):
                st.success("✅ Token de autenticação válido")
                if st.button("🔄 Renovar Autenticação", key="renovar_auth"):
                    if os.path.exists('token.json'):
                        os.remove('token.json')
                    st.rerun()
        
        opcao = st.radio("Selecione o módulo:", ("OBRA", "EMPRESA", "EVENTOS", "AGRONOMIA"), key="sidebar_radio")
        
        # Nova opção para baixar dados Excel
        if st.session_state.logged_in and opcao == "OBRA":
            st.markdown("---")
            if st.button("📊 Baixar Planilha Master", 
                        use_container_width=True,
                        key="download_excel_button"):
                try:
                    drive_service = autenticar_google_drive()
                    if drive_service:
                        with st.spinner("Carregando Planilha Master do Google Drive..."):
                            df_dados, caminho_temp = carregar_planilha_master_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
                            
                            if not df_dados.empty:
                                excel_data = exportar_planilha_para_download(df_dados)
                                if excel_data:
                                    # Criar link para download
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
                                    
                                    # Mostrar estatísticas
                                    with st.expander("📊 Estatísticas da Planilha Master"):
                                        st.write(f"**Total de registros:** {len(df_dados)}")
                                        if 'DATA_GERACAO' in df_dados.columns:
                                            st.write(f"**Última atualização:** {df_dados['DATA_GERACAO'].max() if not df_dados['DATA_GERACAO'].empty else 'N/A'}")
                                        if 'AGENTE_NOME' in df_dados.columns:
                                            agentes_unicos = df_dados['AGENTE_NOME'].nunique()
                                            st.write(f"**Agentes distintos:** {agentes_unicos}")
                                else:
                                    st.error("❌ Erro ao preparar arquivo Excel")
                            else:
                                st.info("📊 Planilha Master vazia. Gere alguns relatórios primeiro.")
                                
                        # Limpar arquivo temporário
                        if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
                            try:
                                os.unlink(caminho_temp)
                            except:
                                pass
                    else:
                        st.warning("⚠️ Não foi possível conectar ao Google Drive")
                except Exception as e:
                    st.error(f"❌ Erro ao baixar dados: {str(e)}")
        
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

    if opcao == "OBRA":
        st.title("Relatório de Fiscalização - Obra")
        
        # Mostrar informações do agente acima do número do relatório
        if st.session_state.agente_info:
            nome = st.session_state.agente_info.get('NOME', '')
            matricula = st.session_state.agente_info.get('MATRICULA', '')
            unidade = st.session_state.agente_info.get('UNIDADE', '')
            
            st.markdown(f"**Agente de Fiscalização:** {nome} - {matricula} - {unidade}")
        
        st.markdown(f"**Número do Relatório:** `{st.session_state.numero_relatorio_gerado}`")
        
        st.markdown("Preencha os dados abaixo para gerar o relatório de fiscalização.")
        
        # Inicializar session states do formulário se necessário
        if not st.session_state.formulario_inicializado:
            st.session_state.fotos_info = []
            st.session_state.contratados_data = []
            st.session_state.current_registro = limpar_campos_registro()
            st.session_state.registro_counter = 1
            st.session_state.current_foto_index = 0
            st.session_state.documentos_solicitados_text = ""
            st.session_state.documentos_recebidos_text = ""
            st.session_state.formulario_inicializado = True
        
        # Usar o contador para criar chaves únicas para widgets
        widget_counter = st.session_state.form_widget_counter
        
        # Contador específico para limpar apenas a seção 04
        secao04_counter = st.session_state.secao04_limpa_counter
        
        # Cabeçalho do Relatório
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
            
            # ================================================
            # ALTERAÇÃO SOLICITADA 1: Tipo de Ação com opção "OUTROS"
            # ================================================
            tipo_visita_opcoes = ["", "AFC", "Obra", "Manutenção Predial", "Carnaval", "Empresa", 
                                "Posto de Combustível", "Evento", "Condomínio", "Estádio", 
                                "Interno", "Hospital", "Hotel", "Agronomia", "Aeroporto", 
                                "Porto", "Embarcacao", "Cemitério", "Outras"]
            
            tipo_visita = st.selectbox("Tipo de Ação", 
                                      tipo_visita_opcoes, 
                                      key=f"tipo_visita_select_{widget_counter}")
            
            # Campo de texto para especificar "Outras"
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
        
        # Campos para coordenadas
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
        
        # Campos de endereço
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
            # Campo Município como lista suspensa
            municipio = st.selectbox(
                "Município *",
                options=[""] + sorted(MUNICIPIOS_RJ),
                key=f"municipio_select_{widget_counter}",
                help="Selecione o município do Rio de Janeiro"
            )
        
        with col3:
            # Campo UF foi REMOVIDO conforme solicitado
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
        
        # Mostrar registro atual
        st.markdown(f"#### 📝 Registro Atual: {st.session_state.registro_counter}")
        
        # ================================================================
        # ALTERAÇÃO PRINCIPAL: USAR CONTADOR ESPECÍFICO PARA LIMPAR SEÇÃO 04
        # ================================================================
        current_data = st.session_state.current_registro
        
        # ================================================
        # NOVA FUNCIONALIDADE: PERGUNTA SOBRE CONTRATANTE PARA CADA REGISTRO
        # ================================================
        st.subheader(f"Identificação do Contratante - Registro {st.session_state.registro_counter}")
        
        # Pergunta obrigatória
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
        
        # Lógica para garantir que apenas uma opção seja selecionada
        if sim_checkbox and nao_checkbox:
            # Se ambos estiverem marcados, desmarca o outro baseado na última ação
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
        
        # Validar que uma opção foi selecionada
        if current_data.get('mesmo_contratante') is None:
            st.warning("⚠️ **Este campo é obrigatório!** Selecione SIM ou NÃO.")
        else:
            st.info(f"**Opção selecionada:** {current_data.get('mesmo_contratante')}")
        
        # Campos adicionais se a opção for NÃO
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
            
            # Validar se todos os campos foram preenchidos quando a opção é NÃO
            if (nome_contratante_secao04 == "" or 
                registro_contratante_secao04 == "" or 
                cpf_cnpj_secao04 == ""):
                st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!**")
        else:
            # Limpar campos se a opção mudou para SIM
            current_data['nome_contratante_secao04'] = ""
            current_data['registro_contratante_secao04'] = ""
            current_data['cpf_cnpj_secao04'] = ""
        
        st.subheader(f"Dados do Contratado/Responsável Técnico - Registro {st.session_state.registro_counter}")
        
        col1, col2 = st.columns(2)
        with col1:
            # NOVO CAMPO: Contratado - PF/PJ
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
            # Lista reduzida para 9 opções conforme solicitado (removida a opção "OUTRAS")
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
            st.write("Atividade (Servico Executado):")
            # ================================================
            # ALTERAÇÃO SOLICITADA 2: Atividade com opção "Outras"
            # ================================================
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
            
            # Campo de texto para especificar "Outras"
            atividade_servico_outras = ""
            if atividade_servico == "Outras":
                atividade_servico_outras = st.text_input(
                    "Especifique a atividade:",
                    placeholder="Digite a atividade personalizada",
                    key=f"atividade_servico_outras_input_{widget_counter}_{secao04_counter}"
                )
                if atividade_servico_outras:
                    atividade_servico = atividade_servico_outras
        
        # Atualizar todos os dados no registro atual
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
        
        # Botão "PRÓXIMO" para salvar registro atual e limpar APENAS os campos da seção 04
        st.markdown("---")
        if st.button("SALVAR", 
                   type="primary", 
                   use_container_width=True,
                   key=f"salvar_registro_button_{widget_counter}_{secao04_counter}"):
            
            # Validar campos obrigatórios
            if st.session_state.current_registro.get('mesmo_contratante') is None:
                st.error("❌ **Campo obrigatório:** Selecione SIM ou NÃO para a pergunta sobre o contratante")
                st.stop()
            
            if st.session_state.current_registro.get('mesmo_contratante') == "NÃO":
                if (not st.session_state.current_registro.get('nome_contratante_secao04') or
                    not st.session_state.current_registro.get('registro_contratante_secao04') or
                    not st.session_state.current_registro.get('cpf_cnpj_secao04')):
                    st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!")
                    st.stop()
            
            # Salvar o registro atual
            sucesso, total_registros = salvar_registro_atual(st.session_state.current_registro)
            
            if sucesso:
                # ================================================================
                # ALTERAÇÃO PRINCIPAL: LIMPAR APENOS OS CAMPOS DA SEÇÃO 04
                # ================================================================
                # Limpar campos da seção 04 para próximo registro
                st.session_state.current_registro = limpar_campos_secao_04()
                st.session_state.registro_counter += 1
                
                # Incrementar o contador específico para limpar campos da seção 04
                st.session_state.secao04_limpa_counter += 1
                
                st.success(f"✅ Registro {st.session_state.registro_counter - 1} salvo com sucesso!")
                st.info(f"Próximo registro: {st.session_state.registro_counter}")
                st.info("Os campos da seção 04 foram limpos para o próximo registro.")
                
                # Forçar atualização da página
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ Erro ao salvar registro. Tente novamente.")
        
        # Seções 05-06 - Documentos COM CHECKBOXES E TÍTULO "OFÍCIO" CORRIGIDO
        st.markdown("### 05 - DOCUMENTOS SOLICITADOS / EXPEDIDOS")
        
        col_doc1, col_doc2 = st.columns(2)
        
        with col_doc1:
            # Documentos Solicitados/Expedidos
            st.subheader("Documentos Solicitados/Expedidos")
            
            # Título "Ofício" antes dos checkboxes
            st.markdown("**Oficio:**")
            
            # Checkboxes para documentos solicitados/expedidos
            circular_solicitado = st.checkbox("Circular", key=f"circular_solicitado_checkbox_{widget_counter}")
            quadro_tecnico_solicitado = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_solicitado_checkbox_{widget_counter}")
            prestadores_servicos_solicitado = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_solicitado_checkbox_{widget_counter}")
            outros_solicitado = st.checkbox("Outros", key=f"outros_solicitado_checkbox_{widget_counter}")
            
            # Campo de texto para número da Circular (se checkbox marcado)
            circular_numero = ""
            if circular_solicitado:
                circular_numero = st.text_input(
                    "Número da Circular:",
                    placeholder="Digite o número da circular",
                    key=f"circular_numero_input_{widget_counter}"
                )
            
            # Campo de texto para "Outros" (se checkbox marcado)
            outros_texto_solicitado = ""
            if outros_solicitado:
                outros_texto_solicitado = st.text_input(
                    "Especifique 'Outros':",
                    placeholder="Descreva outros documentos solicitados/expedidos",
                    key=f"outros_solicitado_input_{widget_counter}"
                )
            
            # Campo de texto adicional para documentos solicitados
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
            # Documentos Recebidos
            st.markdown("#### 06 - DOCUMENTOS RECEBIDOS")
            
            # Título "Ofício" antes dos checkboxes
            st.markdown("**Oficio:**")
            
            # Checkboxes para documentos recebidos
            circular_recebido = st.checkbox("Circular", key=f"circular_recebido_checkbox_{widget_counter}")
            quadro_tecnico_recebido = st.checkbox("Quadro Técnico", key=f"quadro_tecnico_recebido_checkbox_{widget_counter}")
            prestadores_servicos_recebido = st.checkbox("Prestadores de Serviços Técnicos", key=f"prestadores_recebido_checkbox_{widget_counter}")
            outros_recebido = st.checkbox("Outros", key=f"outros_recebido_checkbox_{widget_counter}")
            
            # Campo de texto para número da Circular (se checkbox marcado)
            circular_numero_recebido = ""
            if circular_recebido:
                circular_numero_recebido = st.text_input(
                    "Número da Circular:",
                    placeholder="Digite o número da circular",
                    key=f"circular_numero_recebido_input_{widget_counter}"
                )
            
            # Campos de quantidade para Quadro Técnico e Prestadores
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
            
            # Campo de texto para "Outros" (se checkbox marcado)
            outros_texto_recebido = ""
            if outros_recebido:
                outros_texto_recebido = st.text_input(
                    "Especifique 'Outros':",
                    placeholder="Descreva outros documentos recebidos",
                    key=f"outros_recebido_input_{widget_counter}"
                )
            
            # Campo de texto adicional para documentos recebidos
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
            # Campo "Fonte da Informação" alterado para caixa de texto editável (sem lista suspensa)
            fonte_informacao = st.text_input("Fonte da Informacao", 
                                           placeholder="Digite a fonte da informação",
                                           key=f"fonte_informacao_input_{widget_counter}",
                                           help="Ex: CONSTATAÇÃO, DOCUMENTO, DENÚNCIA, etc.")
                    
        with col2:
            qualificacao_fonte = st.selectbox("Qualificação da Fonte", 
                                            ["PROPRIETÁRIO", "RESPONSÁVEL TÉCNICO", "MESTRE DE OBRA", "OUTRAS"], 
                                            key=f"qualificacao_fonte_select_{widget_counter}")
            
            # Campo para especificar "Outras" qualificações
            if qualificacao_fonte == "OUTRAS":
                qualificacao_fonte_outras = st.text_input(
                    "Especifique a qualificação:",
                    placeholder="Digite a qualificação da fonte",
                    key=f"qualificacao_fonte_outras_input_{widget_counter}"
                )
                if qualificacao_fonte_outras:
                    qualificacao_fonte = qualificacao_fonte_outras
        
        # Seção 08 - Fotos (Sistema de Captura)
        st.markdown("### 08 - FOTOS - REGISTRO FOTOGRÁFICO")
        
        # Inicializar estado da foto temporária
        if 'temp_photo_bytes' not in st.session_state:
            st.session_state.temp_photo_bytes = None
        
        # Sistema de captura de fotos
        tab1, tab2, tab3 = st.tabs(["📷 Capturar Fotos", "📁 Upload de Fotos", "📋 Visualizar e Gerenciar"])
        
        with tab1:
            st.subheader("Sistema de Captura de Fotos")
            
            total_fotos = len(st.session_state.fotos_info)
            
            # ================================================
            # MODIFICAÇÃO SOLICITADA: DIMINUIR FONTES DOS ITENS
            # ================================================
            # Estatísticas com fontes menores
            col_stats1, col_stats2, col_stats3 = st.columns(3)
            with col_stats1:
                st.markdown("**Total de Fotos**", help="Número total de fotos no relatório")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>{total_fotos}</h3>", unsafe_allow_html=True)
            with col_stats2:
                fotos_com_comentarios = sum(1 for foto in st.session_state.fotos_info if foto.comentario.strip())
                st.markdown("**Fotos com Comentarios**", help="Fotos que têm comentários adicionados")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>{fotos_com_comentarios}</h3>", unsafe_allow_html=True)
            with col_stats3:
                st.markdown("**Última Foto**", help="Número da última foto adicionada")
                st.markdown(f"<h3 style='text-align: center; font-size: 24px;'>#{total_fotos}</h3>" if total_fotos > 0 else "<h3 style='text-align: center; font-size: 24px;'>Nenhuma</h3>", unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Área principal de captura
            col_cam, col_controls = st.columns([2, 1])
            
            with col_cam:
                # Widget da câmera
                camera_picture = st.camera_input(
                    "Aponte a câmera e clique no botão para capturar",
                    key=f"camera_capture_{st.session_state.get('camera_counter', 0)}_{widget_counter}"
                )
                
                # Se uma foto foi tirada
                if camera_picture is not None:
                    # Armazenar temporariamente
                    st.session_state.temp_photo_bytes = camera_picture.getvalue()
                    
                    # Exibir pré-visualização OTIMIZADA
                    try:
                        # Reduzir para preview rápido
                        img = Image.open(BytesIO(st.session_state.temp_photo_bytes))
                        img.thumbnail((400, 400))  # Preview pequeno e rápido
                        exibir_imagem_compativel(img, caption="Pré-visualização da foto capturada")
                    except:
                        pass
            
            with col_controls:
                st.write("**Controles da Foto**")
                
                # Campo para comentário da nova foto
                novo_comentario = st.text_area(
                    "Comentário para esta foto:",
                    max_chars=200,
                    height=100,
                    key=f"novo_comentario_input_{widget_counter}",
                    placeholder="Digite um comentário para esta foto..."
                )
                
                # Contador de caracteres
                chars_used = len(novo_comentario)
                st.caption(f"Caracteres: {chars_used}/200")
                
                # Botão para salvar a foto
                col_save1, col_save2 = st.columns(2)
                with col_save1:
                    if st.button("💾 Salvar Foto", 
                               use_container_width=True,
                               disabled=st.session_state.temp_photo_bytes is None,
                               key=f"salvar_foto_button_{widget_counter}"):
                        
                        # Verificar se foto já existe
                        foto_existe = False
                        for foto in st.session_state.fotos_info:
                            if foto.image_bytes == st.session_state.temp_photo_bytes:
                                foto_existe = True
                                break
                        
                        if not foto_existe:
                            # Criar nova foto
                            nova_foto = FotoInfo(
                                image_bytes=st.session_state.temp_photo_bytes,
                                comentario=novo_comentario
                            )
                            st.session_state.fotos_info.append(nova_foto)
                            
                            # Limpar foto temporária
                            st.session_state.temp_photo_bytes = None
                            
                            # Incrementar contador da câmera para forçar novo widget
                            st.session_state.camera_counter = st.session_state.get('camera_counter', 0) + 1
                            
                            st.success(f"✅ Foto {len(st.session_state.fotos_info)} salva com sucesso!")
                            time.sleep(0.5)  # Reduzido
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
                
                st.markdown("---")
                st.write("**Dicas:**")
                st.write("1. Tire a foto")
                st.write("2. Adicione um comentário (opcional)")
                st.write("3. Clique em 'Salvar Foto'")
                st.write("4. Repita para cada foto")
                st.write("5. Vá para a aba 'Visualizar' para gerenciar")
        
        with tab2:
            st.subheader("Upload de Fotos Existentes")
            
            # Upload de múltiplas fotos
            uploaded_files = st.file_uploader(
                "Selecione fotos do seu dispositivo (múltiplas permitidas)",
                type=['jpg', 'jpeg', 'png', 'heic'],
                accept_multiple_files=True,
                key=f"photo_uploader_multiple_{widget_counter}"
            )
            
            if uploaded_files:
                st.write(f"**{len(uploaded_files)} foto(s) selecionada(s)**")
                
                # Mostrar miniaturas OTIMIZADAS
                cols = st.columns(4)
                for i, uploaded_file in enumerate(uploaded_files):
                    with cols[i % 4]:
                        try:
                            # Carregar thumbnail rápido
                            img = Image.open(uploaded_file)
                            img.thumbnail((100, 100))  # Thumbnail pequeno
                            exibir_imagem_compativel(img, caption=f"Foto {i+1}")
                        except:
                            st.write(f"Arquivo {i+1}")
                
                # Campo para comentário geral
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
                                
                                # Verificar se foto já existe
                                foto_existe = False
                                for foto in st.session_state.fotos_info:
                                    if foto.image_bytes == img_bytes:
                                        foto_existe = True
                                        break
                                
                                if not foto_existe:
                                    # Criar nova foto
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
                
                # ⭐⭐ OTIMIZAÇÃO: Paginação para muitas fotos
                if total_fotos > 20:
                    st.info(f"⚠️ Muitas fotos ({total_fotos}). Mostrando apenas as primeiras 20.")
                    fotos_exibidas = st.session_state.fotos_info[:20]
                else:
                    fotos_exibidas = st.session_state.fotos_info
                
                # Navegação entre fotos
                current_foto_idx = st.session_state.current_foto_index
                if current_foto_idx >= len(fotos_exibidas):
                    current_foto_idx = 0
                
                # Controles de navegação
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
                    
                    # Botão para remover foto atual
                    if st.button("🗑️ Remover",
                               type="secondary",
                               use_container_width=True,
                               key=f"remover_foto_atual_gestao_{widget_counter}"):
                        if 0 <= current_foto_idx < total_fotos:
                            st.session_state.fotos_info.pop(current_foto_idx)
                            st.session_state.current_foto_index = max(0, min(current_foto_idx, total_fotos - 2))
                            st.success("Foto removida com sucesso!")
                            time.sleep(0.3)  # Reduzido
                            st.rerun()
                
                # Exibir foto atual OTIMIZADA
                st.markdown("---")
                foto_atual = fotos_exibidas[current_foto_idx]
                
                col_foto, col_comentario = st.columns([2, 1])
                
                with col_foto:
                    try:
                        # Usar thumbnail em cache para exibição rápida
                        img = foto_atual.get_thumbnail(size=(600, 400))
                        
                        # Usar função compatível para exibir imagem
                        exibir_imagem_compativel(img, caption=f"Foto {current_foto_idx + 1} - Preview")
                    except Exception as e:
                        st.error(f"Erro ao carregar foto: {e}")
                
                with col_comentario:
                    st.write("**Comentário:**")
                    
                    # Campo para editar comentário
                    comentario_edit = st.text_area(
                        "Editar comentário:",
                        value=foto_atual.comentario,
                        max_chars=200,
                        height=150,
                        key=f"comentario_edit_{current_foto_idx}_{widget_counter}",
                        label_visibility="collapsed"
                    )
                    
                    # Contador de caracteres
                    chars_used = len(comentario_edit)
                    chars_left = 100 - chars_used
                    st.caption(f"Caracteres: {chars_used}/100 ({chars_left} restantes)")
                    
                    # Botão para salvar comentário
                    if st.button("💾 Salvar Comentário", 
                               use_container_width=True,
                               key=f"salvar_comentario_edit_{current_foto_idx}_{widget_counter}"):
                        if comentario_edit != foto_atual.comentario:
                            st.session_state.fotos_info[current_foto_idx].comentario = comentario_edit
                            st.success("Comentário atualizado com sucesso!")
                            time.sleep(0.3)
                            st.rerun()
                
                # Miniaturas de todas as fotos OTIMIZADAS
                st.markdown("---")
                st.subheader("Todas as Fotos (Thumbnails)")
                
                # Mostrar em grid responsivo
                cols = st.columns(4)
                for i, foto in enumerate(fotos_exibidas):
                    with cols[i % 4]:
                        try:
                            # Usar thumbnail em cache
                            img = foto.get_thumbnail(size=(120, 120))
                            
                            # Indicadores
                            indicador_atual = "📍" if i == current_foto_idx else ""
                            indicador_comentario = "📝" if foto.comentario else "📄"
                            
                            # Usar função compatível para exibir imagem
                            exibir_imagem_compativel(img, 
                                                   caption=f"{indicador_atual} Foto {i+1} {indicador_comentario}")
                            
                            # Botão para selecionar
                            if st.button(f"Selecionar #{i+1}", 
                                       key=f"select_thumb_{i}_{widget_counter}",
                                       use_container_width=True):
                                st.session_state.current_foto_index = i
                                st.rerun()
                        except:
                            st.error(f"Erro na foto {i+1}")
                
                # Ações em lote
                if total_fotos > 5:
                    st.markdown("---")
                    st.write("**Ações em Lote:**")
                    
                    col_batch1, col_batch2 = st.columns(2)
                    
                    with col_batch1:
                        if st.button("🗑️ Remover Todas", 
                                   type="secondary",
                                   use_container_width=True,
                                   key=f"remover_todas_fotos_{widget_counter}"):
                            if st.checkbox("Confirmar remoção de TODAS as fotos", key=f"confirmar_remocao_{widget_counter}"):
                                st.session_state.fotos_info = []
                                st.session_state.current_foto_index = 0
                                st.success("Todas as fotos foram removidas!")
                                time.sleep(0.5)
                                st.rerun()
        
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
                
                if not endereco:  # Campo "Endereço" agora é obrigatório
                    st.error("❌ Campo obrigatório: Endereço deve ser preenchido")
                    st.stop()
                
                if not municipio:  # Campo "Município" agora é obrigatório
                    st.error("❌ Campo obrigatório: Município deve ser selecionado")
                    st.stop()
                
                # ================================================
                # NOVA FUNCIONALIDADE: Salvar automaticamente o último registro
                # ================================================
                current_registro = st.session_state.current_registro
                tem_dados_atuais = False
                
                # Verificar se o registro atual tem algum dado preenchido
                for key, value in current_registro.items():
                    if value and key != 'identificacao_fiscalizado':  # Ignorar campo padrão
                        tem_dados_atuais = True
                        break
                
                # Se houver dados no registro atual, salvar automaticamente
                if tem_dados_atuais:
                    # Validar campos obrigatórios antes de salvar
                    if current_registro.get('mesmo_contratante') is None:
                        st.error("❌ **Campo obrigatório:** Selecione SIM ou NÃO para a pergunta sobre o contratante")
                        st.stop()
                    
                    if current_registro.get('mesmo_contratante') == "NÃO":
                        if (not current_registro.get('nome_contratante_secao04') or
                            not current_registro.get('registro_contratante_secao04') or
                            not current_registro.get('cpf_cnpj_secao04')):
                            st.error("❌ **Quando a opção é NÃO, todos os campos do contratante devem ser preenchidos!")
                            st.stop()
                    
                    # Salvar o registro atual automaticamente
                    sucesso, total_registros = salvar_registro_atual(current_registro)
                    
                    if sucesso:
                        st.success(f"✅ Último registro salvo automaticamente!")
                        
                        # Limpar campos após salvar
                        st.session_state.current_registro = limpar_campos_registro()
                    else:
                        st.error("❌ Erro ao salvar o último registro automaticamente")
                
                total_fotos = len(st.session_state.fotos_info)
                
                if total_fotos == 0:
                    st.warning("⚠️ Nenhuma foto adicionada ao relatório.")
                    if not st.checkbox("Continuar sem fotos", key=f"continuar_sem_fotos_{widget_counter}"):
                        st.stop()
                
                # Construir string de documentos solicitados com base nos checkboxes
                documentos_solicitados_list = []
                
                # Adicionar "Ofício:" no início
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
                
                # Combinar tudo
                if tipos_documentos:
                    documentos_solicitados_list.append(oficio_header + " | ".join(tipos_documentos))
                
                # Adicionar texto adicional se existir
                if documentos_solicitados_text:
                    documentos_solicitados_list.append(documentos_solicitados_text)
                
                # Converter lista para string
                if documentos_solicitados_list:
                    documentos_solicitados = " | ".join(documentos_solicitados_list)
                else:
                    documentos_solicitados = "SEM DOCUMENTOS SOLICITADOS / EXPEDIDOS"
                
                # Construir string de documentos recebidos com base nos checkboxes
                documentos_recebidos_list = []
                
                # Adicionar "Ofício:" no início
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
                
                # Combinar tudo
                if tipos_documentos_recebidos:
                    documentos_recebidos_list.append(oficio_header_recebido + " | ".join(tipos_documentos_recebidos))
                
                # Adicionar texto adicional se existir
                if documentos_recebidos_text:
                    documentos_recebidos_list.append(documentos_recebidos_text)
                
                # Converter lista para string
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
                    'uf': "RJ",  # Fixo como RJ
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
                    # ⭐⭐ OTIMIZAÇÃO: Mostrar progresso
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    status_text.text("🔄 Preparando dados...")
                    progress_bar.progress(10)
                    
                    # Criar PDF
                    status_text.text("📄 Criando PDF...")
                    pdf = criar_pdf(dados, logo_path, 
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
                    
                    # Opção para upload no Google Drive
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
                                
                                # Calcular tamanho em MB
                                tamanho_mb = drive_info['tamanho_bytes'] / (1024 * 1024)
                                
                                # Mostrar link BEM VISÍVEL
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
                            st.warning("⚠️ Serviço do Google Drive não disponível. Verifique as credenciais.")
                    
                    # ========== ATUALIZAR PLANILHA MASTER ==========
                    status_text.text("📊 Atualizando Planilha Master...")
                    
                    if drive_service:
                        # Adicionar dados à Planilha Master
                        excel_sucesso = adicionar_relatorio_a_planilha_master(
                            dados_relatorio=dados,
                            agente_info=st.session_state.agente_info,
                            fotos_info=st.session_state.fotos_info,
                            pdf_info=drive_info if drive_info else None,
                            service=drive_service,
                            folder_id=GOOGLE_DRIVE_FOLDER_ID
                        )
                        
                        if excel_sucesso:
                            progress_bar.progress(95)
                            st.success("✅ Dados do relatório adicionados à Planilha Master!")
                        else:
                            st.warning("⚠️ Dados do PDF gerados, mas não foi possível atualizar a Planilha Master.")
                    else:
                        st.warning("⚠️ Não foi possível conectar ao Google Drive para atualizar a Planilha Master.")
                    
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
                    
                    # Estatísticas finais
                    fotos_com_comentarios = sum(1 for foto in st.session_state.fotos_info if foto.comentario.strip())
                    total_registros = len(st.session_state.contratados_data)
                    
                    # Resumo com informações do Google Drive
                    resumo_texto = f"""
                    **📊 Resumo Final:**
                    - **Número do relatório:** {st.session_state.numero_relatorio_gerado}
                    - **Agente:** {st.session_state.agente_info['NOME'] if st.session_state.agente_info else 'N/A'}
                    - **Total de fotos:** {total_fotos}
                    - **Fotos com comentários:** {fotos_com_comentarios}
                    - **Registros de contratados:** {total_registros}
                    - **Tamanho do PDF:** {len(pdf_bytes) // 1024} KB
                    """
                    
                    if drive_resultado:
                        resumo_texto += f"\n- **☁️ Google Drive:** PDF enviado com sucesso!"
                        if excel_sucesso:
                            resumo_texto += "\n- **📊 Planilha Master:** Dados atualizados com sucesso!"
                        else:
                            resumo_texto += "\n- **⚠️ Planilha Master:** Falha na atualização"
                    elif drive_resultado is False:
                        resumo_texto += "\n- **⚠️ Google Drive:** Falha no envio (apenas armazenamento local)"
                    else:
                        resumo_texto += "\n- **📍 Armazenamento:** Apenas local (Google Drive não selecionado)"
                    
                    st.info(resumo_texto)
                    
                    # Botão para baixar a Planilha Master
                    st.markdown("---")
                    st.subheader("📊 Planilha Master")
                    st.info(f"Os dados deste relatório foram adicionados à Planilha Master '{EXCEL_DATABASE_NAME}' no Google Drive.")
                    
                    if st.button("📥 Baixar Planilha Master", 
                               key=f"download_master_excel_{widget_counter}",
                               use_container_width=True):
                        if drive_service:
                            with st.spinner("Carregando Planilha Master..."):
                                df_dados, caminho_temp = carregar_planilha_master_drive(drive_service, GOOGLE_DRIVE_FOLDER_ID)
                                
                                if not df_dados.empty:
                                    excel_data = exportar_planilha_para_download(df_dados)
                                    if excel_data:
                                        # Criar link para download
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
                                        
                                        # Mostrar estatísticas
                                        with st.expander("📊 Estatísticas da Planilha Master"):
                                            st.write(f"**Total de registros:** {len(df_dados)}")
                                            if 'DATA_GERACAO' in df_dados.columns:
                                                ultima_data = df_dados['DATA_GERACAO'].max() if not df_dados['DATA_GERACAO'].empty else 'N/A'
                                                st.write(f"**Última atualização:** {ultima_data}")
                                            if 'AGENTE_NOME' in df_dados.columns:
                                                agentes_unicos = df_dados['AGENTE_NOME'].nunique()
                                                st.write(f"**Agentes distintos:** {agentes_unicos}")
                                            if 'TOTAL_FOTOS' in df_dados.columns:
                                                total_fotos_planilha = df_dados['TOTAL_FOTOS'].sum()
                                                st.write(f"**Total de fotos (todos relatórios):** {total_fotos_planilha}")
                                        
                                        # Mostrar preview dos dados
                                        with st.expander("📋 Visualizar Dados da Planilha Master"):
                                            st.dataframe(df_dados)
                                    else:
                                        st.error("❌ Erro ao preparar arquivo Excel")
                                
                                # Limpar arquivo temporário
                                if 'caminho_temp' in locals() and os.path.exists(caminho_temp):
                                    try:
                                        os.unlink(caminho_temp)
                                    except:
                                        pass
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
                finally:
                    # Limpar arquivo temporário
                    if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except:
                            pass
        
        # Botão para NOVO RELATÓRIO - CORRIGIDO
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
                
                # Incrementar o contador de widgets para forçar nova renderização
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
                
                # Incrementar o contador de widgets para forçar nova renderização
                st.session_state.form_widget_counter += 1
                
                st.success("✅ Formulário limpo! Mantendo o mesmo número de relatório.")
                st.info("Todos os campos foram limpos. Você pode preencher novamente.")
                time.sleep(0.5)
                st.rerun()

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