# Relatório de Fiscalização

Aplicativo Streamlit para geração de relatórios de fiscalização.

## Configuração para Streamlit Cloud

1. **Secrets do Streamlit:**
   - `GOOGLE_DRIVE_FOLDER_ID`: ID da pasta do Google Drive
   - `GOOGLE_CREDENTIALS`: JSON das credenciais do Service Account
   - `LOGO_BASE64`: Logo em base64 (opcional)

2. **Arquivos necessários no Google Drive:**
   - `Fiscais.xlsx` na pasta configurada
   - A pasta deve ter permissões para o Service Account

3. **Configuração do Service Account:**
   - Criar no Google Cloud Console
   - Ativar Google Drive API
   - Compartilhar pasta com o email do Service Account