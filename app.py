import streamlit as st
import pandas as pd
import numpy as np
import io
import datetime
import gc
import requests
from dateutil.relativedelta import relativedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.auth.transport.requests

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(page_title="Auditoría de Pedidos vs Ventas", layout="wide", page_icon="⚖️")

# ==========================================
# 🔐 SISTEMA DE PROTECCIÓN (LOGIN)
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_demanda_cuautitlan(_drive_service):
    # ID de la carpeta exacta que proporcionaste
    folder_id = "1rjtSHBSrHWeBj771lAUJwN4uGGHhdHwo"
    try:
        query = f"name contains 'DEMANDA_CUAUTITLAN' and '{folder_id}' in parents and trashed=false"
        results = _drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        
        if not files: return pd.DataFrame()
            
        content = descargar_archivo_drive(_drive_service, files[0]['id'])
        if content:
            engine = 'xlrd' if 'xls' in files[0]['name'].lower() and 'xlsx' not in files[0]['name'].lower() else 'openpyxl'
            df_demanda = pd.read_excel(content, engine=engine)
            
            # EXTRACCIÓN ESTRICTA POR POSICIÓN: Columna A (0) y Columna F (5)
            if len(df_demanda.columns) >= 6:
                df_demanda = df_demanda.iloc[:, [0, 5]].copy()
                df_demanda.columns = ['NP', 'DEMANDA'] # Renombramos a la fuerza
                
                # Limpieza
                df_demanda['NP'] = df_demanda['NP'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                return df_demanda.drop_duplicates(subset=['NP'])
    except Exception as e:
        print(f"Error cargando archivo DEMANDA_CUAUTITLAN: {e}")
    return pd.DataFrame(columns=['NP', 'DEMANDA'])
