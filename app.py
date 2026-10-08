import streamlit as st
import pandas as pd
import numpy as np
import io
import datetime
import gc
import requests
import plotly.express as px
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
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

CREDENTIALS = {
    "CRA REFACCIONES": "REFACCIONES2026."
}

def check_login(user, password):
    if CREDENTIALS.get(user) == password:
        st.session_state['authenticated'] = True
        st.rerun()
    else:
        st.error("🚫 Contraseña incorrecta")

if not st.session_state['authenticated']:
    st.title("🔒 Acceso Restringido")
    st.markdown("### Por favor identifícate para continuar")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        selected_user = st.selectbox("Selecciona Usuario:", list(CREDENTIALS.keys()))
    with col2:
        input_pass = st.text_input("Contraseña:", type="password")
        
    if st.button("Ingresar al Sistema"):
        check_login(selected_user, input_pass)
        
    st.info("Si necesitas acceso, contacta al administrador.")
    st.stop()

# ==========================================
# INICIO DEL DASHBOARD
# ==========================================
st.title("⚖️ Auditoría: Solicitudes de Compra vs. Facturación Real")
st.markdown("Monitor de sobre-pedidos, capital inmovilizado y efectividad por vendedor (Ignorando solicitudes de los últimos 5 días para dar margen de venta).")

# ==========================================
# 1. AUTENTICACIÓN DEL ROBOT EN LA NUBE
# ==========================================
@st.cache_resource
def get_drive_service():
    try:
        gcp_creds = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            gcp_creds, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"⚠️ Error al conectar el Robot API: Verifica tus secrets.toml. Detalle: {e}")
        st.stop()

@st.cache_resource
def get_auth_headers():
    try:
        gcp_creds = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            gcp_creds, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        return {"Authorization": f"Bearer {creds.token}"}
    except Exception as e:
        st.error(f"⚠️ Error al generar Headers del Robot: {e}")
        st.stop()

# ==========================================
# 2. FUNCIONES DE EXTRACCIÓN (DRIVE API)
# ==========================================
def descargar_archivo_drive(drive_service, file_id):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while not done: 
            status, done = downloader.next_chunk()
        file.seek(0)
        return file
    except Exception as e:
        print(f"Error al descargar archivo de Drive: {e}")
        return None

def buscar_archivos_ventas(drive_service, master_sales_id, agencia, anios):
    archivos_encontrados = []
    if not master_sales_id: return []
    for anio in anios:
        query = f"name contains '{agencia}' and name contains '{anio}' and name contains 'MASTER' and '{master_sales_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        archivos_encontrados.extend(results.get('files', []))
    return archivos_encontrados

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_inventario_filtrado(_drive_service, inventory_folder_id):
    if not inventory_folder_id: return pd.DataFrame()
    try:
        query = f"name contains 'INVENTARIO_CRA' and '{inventory_folder_id}' in parents and trashed=false"
        results = _drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files = results.get('files', [])
        
        if not files:
            query2 = f"name contains 'CRA_REFACCIONES' and '{inventory_folder_id}' in parents and trashed=false"
            results2 = _drive_service.files().list(q=query2, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            files = results2.get('files', [])
            
        if not files: return pd.DataFrame()
            
        content = descargar_archivo_drive(_drive_service, files[0]['id'])
        if content:
            engine = 'xlrd' if 'xls' in files[0]['name'].lower() and 'xlsx' not in files[0]['name'].lower() else 'openpyxl'
            df_inv = pd.read_excel(content, engine=engine)
            df_inv.columns = df_inv.columns.str.upper().str.strip()
            
            if 'NP' in df_inv.columns:
                df_inv['NP'] = df_inv['NP'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            if 'EXISTENCIA' in df_inv.columns:
                df_inv['EXISTENCIA'] = pd.to_numeric(df_inv['EXISTENCIA'], errors='coerce').fillna(0)
            if 'COSTO_UNITARIO' in df_inv.columns:
                df_inv['COSTO_UNITARIO'] = pd.to_numeric(df_inv['COSTO_UNITARIO'], errors='coerce').fillna(0)
            
            # Blindaje por si la columna de fecha de compra no existe en la base
            if 'FEC_ULT_COMPRA' not in df_inv.columns:
                df_inv['FEC_ULT_COMPRA'] = pd.NaT
            
            mask_filtro = (df_inv['SUCURSAL'].astype(str).str.strip().str.upper() == 'CUAUTITLAN') & \
                          (df_inv['ALMACEN'].astype(str).str.strip().str.upper() == 'ALM. GENERAL')
            return df_inv[mask_filtro].copy()
    except Exception as e:
        print(f"Error cargando inventario: {e}")
    return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_demanda_cuautitlan(_drive_service):
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
            
            if len(df_demanda.columns) >= 6:
                df_demanda = df_demanda.iloc[:, [0, 5]].copy()
                df_demanda.columns = ['NP', 'DEMANDA']
                
                df_demanda['NP'] = df_demanda['NP'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                return df_demanda.drop_duplicates(subset=['NP'])
    except Exception as e:
        print(f"Error cargando archivo DEMANDA_CUAUTITLAN: {e}")
    return pd.DataFrame(columns=['NP', 'DEMANDA'])

@st.cache_data(ttl=3600, show_spinner=False)
def descargar_ventas_optimizadas(_drive_service, master_sales_id):
    hoy = datetime.datetime.now()
    fecha_fin = hoy + relativedelta(days=1)
    fecha_inicio = hoy - relativedelta(years=1)
    anios_drive = list(set([fecha_inicio.year, fecha_fin.year]))
    
    sucursales = ["CUAUTITLAN", "TULTITLAN", "BAJIO"]
    files_metadata = []
    for suc in sucursales:
        files_metadata.extend(buscar_archivos_ventas(_drive_service, master_sales_id, suc, anios_drive))
        
    dfs = []
    for file_meta in files_metadata:
        content = descargar_archivo_drive(_drive_service, file_meta['id'])
        if content:
            try:
                engine = 'xlrd' if 'xls' in file_meta['name'].lower() and 'xlsx' not in file_meta['name'].lower() else 'openpyxl'
                df_temp = pd.read_excel(content, engine=engine)
                df_temp.columns = df_temp.columns.str.upper().str.strip()
                cols_utiles = [c for c in df_temp.columns if c in ['NP', 'VENDEDOR', 'FECHA', 'CANTIDAD', 'FACTURA']]
                dfs.append(df_temp[cols_utiles].copy())
                del df_temp 
            except Exception: pass
            finally:
                content.close()
                del content
                gc.collect() 
                
    if not dfs: return pd.DataFrame()
    
    df_global = pd.concat(dfs, ignore_index=True)
    del dfs 
    gc.collect()
    
    df_global['FECHA'] = pd.to_datetime(df_global['FECHA'], dayfirst=True, errors='coerce')
    mask = (df_global['FECHA'] >= fecha_inicio) & (df_global['FECHA'] <= fecha_fin)
    df_global = df_global[mask].copy()
    
    df_global['NP'] = df_global['NP'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df_global['CANTIDAD'] = pd.to_numeric(df_global['CANTIDAD'], errors='coerce').fillna(0)
    
    return df_global

# ==========================================
# 3. MOTOR ETL: CRUCES Y REGLAS DE NEGOCIO
# ==========================================
def procesar_cruce_maestro(df_sol, df_ven, df_alm, df_dem):
    df_sol = df_sol.rename(columns={'N° DE PARTE': 'NP', 'CANTIDAD': 'CANT_SOLICITADA', 'FECHA': 'FECHA_SOLICITUD'})
    df_ven = df_ven.rename(columns={'FECHA': 'FECHA_VENTA', 'CANTIDAD': 'CANT_VENDIDA'})
    
    df_sol['NP'] = df_sol['NP'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    df_sol['FECHA_SOLICITUD_DT'] = pd.to_datetime(df_sol['FECHA_SOLICITUD'], dayfirst=True, errors='coerce')
    
    # REGLA DE 5 DÍAS DE ANTIGÜEDAD
    fecha_limite = pd.Timestamp.now().normalize() - pd.Timedelta(days=5)
    df_sol = df_sol[df_sol['FECHA_SOLICITUD_DT'] <= fecha_limite].copy()
    
    if df_sol.empty:
        return df_sol 
    
    # CRUCE 1: SOLICITUD VS VENTAS REALES
    cruce_ventas = pd.merge(df_sol, df_ven[['VENDEDOR', 'NP', 'FECHA_VENTA', 'CANT_VENDIDA']], 
                            on=['VENDEDOR', 'NP'], how='left')
    
    ventas_validas = cruce_ventas[cruce_ventas['FECHA_VENTA'] >= cruce_ventas['FECHA_SOLICITUD_DT']]
    ventas_agrupadas = ventas_validas.groupby(['VENDEDOR', 'NP', 'FECHA_SOLICITUD_DT'])['CANT_VENDIDA'].sum().reset_index()
    ventas_agrupadas = ventas_agrupadas.rename(columns={'CANT_VENDIDA': 'CANT_FACTURADA', 'FECHA_SOLICITUD_DT': 'FECHA_SOLICITUD'})
    
    base = pd.merge(df_sol, ventas_agrupadas, on=['VENDEDOR', 'NP', 'FECHA_SOLICITUD'], how='left')
    base['CANT_FACTURADA'] = base['CANT_FACTURADA'].fillna(0)
    base['CANT_SOLICITADA'] = pd.to_numeric(base['CANT_SOLICITADA'], errors='coerce').fillna(0)
    
    # TOPE DE FACTURACIÓN
    base['CANT_FACTURADA'] = np.minimum(base['CANT_FACTURADA'], base['CANT_SOLICITADA'])
    base['PIEZAS_NO_FACTURADAS'] = (base['CANT_SOLICITADA'] - base['CANT_FACTURADA']).clip(lower=0)
    
    # CRUCE 2: VALIDACIÓN CON ALMACÉN FÍSICO Y EXTRACCIÓN DE FECHA COMPRA
    if not df_alm.empty:
        alm_agrupado = df_alm.groupby('NP').agg(
            EXISTENCIA=('EXISTENCIA', 'sum'), 
            COSTO_UNITARIO=('COSTO_UNITARIO', 'max'),
            FEC_ULT_COMPRA=('FEC_ULT_COMPRA', 'max') # Extrayendo la fecha de ingreso
        ).reset_index()
        base = pd.merge(base, alm_agrupado, on='NP', how='left')
    else:
        base['EXISTENCIA'] = 0
        base['COSTO_UNITARIO'] = 0
        base['FEC_ULT_COMPRA'] = pd.NaT
        
    base['EXISTENCIA'] = base['EXISTENCIA'].fillna(0)
    base['COSTO_UNITARIO'] = base['COSTO_UNITARIO'].fillna(0)
    
    # VALORACIÓN JUSTA DEL CAPITAL
    piezas_a_valorar = np.minimum(base['PIEZAS_NO_FACTURADAS'], base['EXISTENCIA'])
    base['CAPITAL_INMOVILIZADO'] = piezas_a_valorar * base['COSTO_UNITARIO']
    
    riesgo = (base['PIEZAS_NO_FACTURADAS'] > 0) & (base['EXISTENCIA'] >= base['CANT_SOLICITADA'])
    base['ALERTA'] = np.where(riesgo, "🚨 ESTANCADO (EN ALM. GENERAL)", "✅ CUMPLIDO")
    
    # CRUCE 3: CLASIFICACIÓN DE DEMANDA (Reemplazando Sin Clasificación por OBSOLETO)
    if not df_dem.empty:
        base = pd.merge(base, df_dem, on='NP', how='left')
    else:
        base['DEMANDA'] = "OBSOLETO"
        
    base['DEMANDA'] = base['DEMANDA'].fillna("OBSOLETO").replace("SIN CLASIFICACION", "OBSOLETO")
    
    # --- FORMATEO DE FECHAS (Sin horas, solo DD/MM/AAAA) ---
    base['INGRESO DE COMPRA'] = pd.to_datetime(base['FEC_ULT_COMPRA'], errors='coerce').dt.strftime('%d/%m/%Y').fillna("Sin Registro")
    base['FECHA_SOLICITUD'] = base['FECHA_SOLICITUD_DT'].dt.strftime('%d/%m/%Y').fillna("Sin Fecha")
    
    return base

# ==========================================
# 4. INTERFAZ GRÁFICA DEL DASHBOARD
# ==========================================
URL_DRIVE = "https://docs.google.com/spreadsheets/d/1n03PpyyqR60ZTjlXvIwHH73BfmkLxs1M8pHpC8J_gjE/export?format=csv&gid=851435359"

if st.button("🚀 Extraer Datos y Auditar Vendedores", type="primary"):
    with st.spinner("🤖 Robot extrayendo archivos (esto tomará un minuto, optimizando memoria)..."):
        drive_service = get_drive_service()
        headers_robot = get_auth_headers()
        
        MASTER_SALES_ID = st.secrets["general"].get("master_sales_id")
        INVENTORY_FOLDER_ID = st.secrets["general"].get("inventory_folder_id")
        
        try:
            res = requests.get(URL_DRIVE, headers=headers_robot)
            if res.status_code == 200:
                df_drive = pd.read_csv(io.StringIO(res.text), header=1) 
            else:
                st.error(f"Error de acceso. Código HTTP: {res.status_code}")
                st.stop()
        except Exception as e:
            st.error(f"Error crítico al leer el Google Sheet restringido: {e}")
            st.stop()
            
        df_ventas = descargar_ventas_optimizadas(drive_service, MASTER_SALES_ID)
        df_almacen = cargar_inventario_filtrado(drive_service, INVENTORY_FOLDER_ID)
        df_demanda = cargar_demanda_cuautitlan(drive_service)
        
        base_final = procesar_cruce_maestro(df_drive, df_ventas, df_almacen, df_demanda)
        
        if base_final.empty:
            st.success("✅ No hay solicitudes procesables. Todas las peticiones tienen menos de 5 días de antigüedad.")
            st.stop()
            
        st.markdown("---")
        
        # --- TABLA 1 (FILTRO DE RIESGO: PREPARADA ANTES DE LAS MÉTRICAS) ---
        mask_pendientes = (base_final['PIEZAS_NO_FACTURADAS'] > 0) & (base_final['EXISTENCIA'] >= base_final['CANT_SOLICITADA'])
        df_pendientes = base_final[mask_pendientes].copy()
        
        # --- NUEVAS MÉTRICAS GLOBALES SUPERIORES ---
        total_pdte_facturar = base_final['PIEZAS_NO_FACTURADAS'].sum()
        capital_atorado = df_pendientes['CAPITAL_INMOVILIZADO'].sum() # Extrae estrictamente la sumatoria de la Tabla 1
        
        col1, col2 = st.columns(2)
        col1.metric("📦 Total Piezas Pendiente Facturar", f"{total_pdte_facturar:,.0f}")
        col2.metric("💸 Capital Estancado (Riesgo Rojo)", f"${capital_atorado:,.2f}")
        
        # Agregamos INGRESO DE COMPRA justo después de FECHA_SOLICITUD
        columnas_vista = [
            'VENDEDOR', 'NP', 'DESCRIPCIÓN', 'DEMANDA', 'FECHA_SOLICITUD', 'INGRESO DE COMPRA',
            'CANT_SOLICITADA', 'CANT_FACTURADA', 'PIEZAS_NO_FACTURADAS', 
            'EXISTENCIA', 'CAPITAL_INMOVILIZADO', 'ALERTA'
        ]
        cols_finales = [c for c in columnas_vista if c in base_final.columns]
        
        # --- MOSTRAR TABLA 1: SOLO ESTANCADOS ---
        st.subheader("🚨 Detalle de Solicitudes Pendientes (Riesgo Almacén)")
        if not df_pendientes.empty:
            st.dataframe(
                df_pendientes[cols_finales].style.format({
                    'CANT_SOLICITADA': '{:,.0f}',
                    'CANT_FACTURADA': '{:,.0f}',
                    'PIEZAS_NO_FACTURADAS': '{:,.0f}',
                    'EXISTENCIA': '{:,.0f}',
                    'CAPITAL_INMOVILIZADO': '${:,.2f}'
                }), 
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.success("¡Excelente! No hay piezas estancadas por solicitudes no facturadas.")
            
        st.markdown("---")
        
        # --- MOSTRAR TABLA 2: HISTÓRICO COMPLETO ---
        st.subheader("📋 Historial Completo de Solicitudes")
        st.dataframe(
            base_final[cols_finales].style.format({
                'CANT_SOLICITADA': '{:,.0f}',
                'CANT_FACTURADA': '{:,.0f}',
                'PIEZAS_NO_FACTURADAS': '{:,.0f}',
                'EXISTENCIA': '{:,.0f}',
                'CAPITAL_INMOVILIZADO': '${:,.2f}'
            }), 
            use_container_width=True, 
            hide_index=True
        )
        
        st.markdown("---")
        
        # --- INDICADORES DE DESEMPEÑO Y CALIDAD ---
        colA, colB = st.columns(2)
        
        with colA:
            st.subheader("🎯 Desempeño de Venta por Asesor")
            
            # FILTRO ESTRICTO DE DESEMPEÑO: Solo se evalúa si ya facturó ALGO o si realmente HAY stock para surtir
            mask_evaluable = (base_final['CANT_FACTURADA'] > 0) | (base_final['EXISTENCIA'] >= base_final['CANT_SOLICITADA'])
            df_evaluable = base_final[mask_evaluable]
            
            desempeno = df_evaluable.groupby('VENDEDOR').agg(
                PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum'),
                PIEZAS_FACTURADAS=('CANT_FACTURADA', 'sum')
            ).reset_index()
            
            desempeno['TASA DE ÉXITO'] = np.where(
                desempeno['PIEZAS_SOLICITADAS'] > 0,
                desempeno['PIEZAS_FACTURADAS'] / desempeno['PIEZAS_SOLICITADAS'],
                0
            )
            desempeno = desempeno.sort_values(by='TASA DE ÉXITO', ascending=False)
            
            st.dataframe(
                desempeno.style.format({
                    'PIEZAS_SOLICITADAS': '{:,.0f}', 
                    'PIEZAS_FACTURADAS': '{:,.0f}',
                    'TASA DE ÉXITO': '{:.1%}'
                }), 
                use_container_width=True, 
                hide_index=True
            )
            
        with colB:
            st.subheader("📊 Calidad del Pedido (Clasificación de Demanda)")
            calidad = base_final.groupby('DEMANDA').agg(
                TOTAL_PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum')
            ).reset_index()
            calidad = calidad.sort_values(by='TOTAL_PIEZAS_SOLICITADAS', ascending=False)
            
            # Asignación estricta de semáforo de colores para la demanda usando Plotly
            mapa_colores = {
                "ALTA": "#11734b",       # Verde fuerte
                "MEDIA": "#ffb703",      # Naranja/Amarillo
                "BAJA": "#fb8500",       # Naranja oscuro
                "OBSOLETO": "#b10202"    # Rojo Peligro
            }
            
            fig = px.bar(
                calidad, 
                x="DEMANDA", 
                y="TOTAL_PIEZAS_SOLICITADAS", 
                color="DEMANDA",
                color_discrete_map=mapa_colores,
                text="TOTAL_PIEZAS_SOLICITADAS"
            )
            fig.update_traces(textposition="outside", textfont=dict(size=14, color="white"))
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Piezas Solicitadas", margin=dict(t=20, b=0))
            
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(
                calidad.style.format({'TOTAL_PIEZAS_SOLICITADAS': '{:,.0f}'}), 
                use_container_width=True, 
                hide_index=True
            )
