import streamlit as st
import pandas as pd
import numpy as np
import io
import requests
import plotly.express as px
from google.oauth2 import service_account
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
st.title("⚖️ Auditoría Inteligente: Solicitudes vs. Facturación")
st.markdown("Monitor gerencial de sobre-pedidos, capital inmovilizado y apoyo de ventas.")

# ==========================================
# 1. CONEXIÓN AL ARCHIVO MAESTRO EN DRIVE
# ==========================================
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
        st.error(f"⚠️ Error al generar credenciales. Verifica secrets.toml: {e}")
        st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def cargar_base_maestra():
    # LINK EXACTO AL ARCHIVO GENERADO POR COLAB EN GOOGLE SHEETS
    URL_DRIVE = "https://docs.google.com/spreadsheets/d/1ql3_qPjMK167EfWVuQK1m-Cjm3a6TPy4/export?format=csv&gid=1282153862"
    headers_robot = get_auth_headers()
    
    try:
        res = requests.get(URL_DRIVE, headers=headers_robot)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            
            # Limpieza básica por si Google Sheets añade formatos raros al exportar
            numeric_cols = ['CANT_SOLICITADA', 'CANT_FACTURADA', 'CANT_FACTURADA_APOYO', 
                            'PIEZAS_NO_FACTURADAS', 'EXISTENCIA', 'CAPITAL_INMOVILIZADO']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            return df
        else:
            st.error(f"⚠️ Error de acceso al servidor de Google. Código HTTP: {res.status_code}")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"⚠️ Error crítico al leer la Base Maestra: {e}")
        return pd.DataFrame()

# ==========================================
# 2. INTERFAZ GRÁFICA Y CARGA DE DATOS
# ==========================================
with st.spinner("🤖 Conectando con la Base Maestra..."):
    base_final = cargar_base_maestra()

if base_final.empty:
    st.warning("No se encontraron datos en el archivo maestro o aún no ha sido procesado por Colab.")
    st.stop()

# --- FILTROS GLOBALES (OPCIONALES PERO ÚTILES) ---
st.sidebar.header("Filtros del Dashboard")
lista_vendedores = ["Todos"] + sorted(base_final['VENDEDOR'].dropna().unique().tolist())
filtro_vendedor = st.sidebar.selectbox("Filtrar por Vendedor:", lista_vendedores)

if filtro_vendedor != "Todos":
    base_final = base_final[base_final['VENDEDOR'] == filtro_vendedor]

# --- MÉTRICAS GLOBALES SUPERIORES ---
st.markdown("---")
# Filtramos solo lo que está realmente estancado o falta por facturar para el capital rojo
mask_riesgo = base_final['ALERTA'].isin(["🚨 ESTANCADO", "⚠️ FALTA POR FACTURAR", "❌ SIN STOCK SUFICIENTE PARA VENTA"])
df_riesgo = base_final[mask_riesgo].copy()

total_pdte = base_final['PIEZAS_NO_FACTURADAS'].sum()
capital_riesgo = df_riesgo['CAPITAL_INMOVILIZADO'].sum()
total_apoyo = base_final['CANT_FACTURADA_APOYO'].sum()

col1, col2, col3 = st.columns(3)
col1.metric("📦 Total Piezas Pendiente", f"{total_pdte:,.0f}")
col2.metric("💸 Capital en Riesgo", f"${capital_riesgo:,.2f}")
col3.metric("🤝 Piezas de Apoyo (Otros Asesores)", f"{total_apoyo:,.0f}")
st.markdown("---")

# --- DEFINICIÓN DE COLUMNAS PARA VISTAS ---
columnas_vista = [
    'VENDEDOR', 'NP', 'DESCRIPCIÓN', 'TIPO DE PEDIDO', 'DEMANDA', 'FECHA_SOLICITUD', 
    'INGRESO DE COMPRA', 'FECHA_VENTA', 'CANT_SOLICITADA', 'CANT_FACTURADA', 
    'CANT_FACTURADA_APOYO', 'PIEZAS_NO_FACTURADAS', 'EXISTENCIA', 'CAPITAL_INMOVILIZADO', 'ALERTA'
]
cols_finales = [c for c in columnas_vista if c in base_final.columns]

# --- TABLA 1: SOLO FOCOS ROJOS (Riesgo y Apoyos) ---
st.subheader("🚨 Focos de Atención (Estancados y Falta de Stock)")
mask_alertas = base_final['ALERTA'] != "✅ CUMPLIDO"
df_alertas = base_final[mask_alertas]

if not df_alertas.empty:
    st.dataframe(
        df_alertas[cols_finales].style.format({
            'CANT_SOLICITADA': '{:,.0f}',
            'CANT_FACTURADA': '{:,.0f}',
            'CANT_FACTURADA_APOYO': '{:,.0f}',
            'PIEZAS_NO_FACTURADAS': '{:,.0f}',
            'EXISTENCIA': '{:,.0f}',
            'CAPITAL_INMOVILIZADO': '${:,.2f}'
        }), 
        use_container_width=True, 
        hide_index=True
    )
else:
    st.success("¡Excelente! No hay alertas pendientes. Todo está Cumplido.")

st.markdown("---")

# --- TABLA 2: HISTÓRICO COMPLETO ---
st.subheader("📋 Base Maestra Completa")
st.dataframe(
    base_final[cols_finales].style.format({
        'CANT_SOLICITADA': '{:,.0f}',
        'CANT_FACTURADA': '{:,.0f}',
        'CANT_FACTURADA_APOYO': '{:,.0f}',
        'PIEZAS_NO_FACTURADAS': '{:,.0f}',
        'EXISTENCIA': '{:,.0f}',
        'CAPITAL_INMOVILIZADO': '${:,.2f}'
    }), 
    use_container_width=True, 
    hide_index=True
)
st.markdown("---")

# --- GRÁFICOS E INDICADORES DE DESEMPEÑO ---
colA, colB = st.columns(2)

with colA:
    st.subheader("🎯 Desempeño de Venta por Asesor")
    
    # Filtro de desempeño: Se evalúa si ya facturó, si recibió apoyo, o si hay stock para surtir
    mask_evaluable = (base_final['CANT_FACTURADA'] > 0) | (base_final['CANT_FACTURADA_APOYO'] > 0) | (base_final['EXISTENCIA'] >= base_final['CANT_SOLICITADA'])
    df_evaluable = base_final[mask_evaluable]
    
    if not df_evaluable.empty:
        desempeno = df_evaluable.groupby('VENDEDOR').agg(
            PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum'),
            PIEZAS_FACT_PROPIAS=('CANT_FACTURADA', 'sum'),
            PIEZAS_APOYO=('CANT_FACTURADA_APOYO', 'sum')
        ).reset_index()
        
        # Tasa de éxito considerando solo sus propias ventas
        desempeno['TASA DE ÉXITO (PROPIA)'] = np.where(
            desempeno['PIEZAS_SOLICITADAS'] > 0,
            desempeno['PIEZAS_FACT_PROPIAS'] / desempeno['PIEZAS_SOLICITADAS'],
            0
        )
        desempeno = desempeno.sort_values(by='TASA DE ÉXITO (PROPIA)', ascending=False)
        
        st.dataframe(
            desempeno.style.format({
                'PIEZAS_SOLICITADAS': '{:,.0f}', 
                'PIEZAS_FACT_PROPIAS': '{:,.0f}',
                'PIEZAS_APOYO': '{:,.0f}',
                'TASA DE ÉXITO (PROPIA)': '{:.1%}'
            }), 
            use_container_width=True, 
            hide_index=True
        )

with colB:
    st.subheader("📊 Calidad de Pedidos (Por Demanda)")
    calidad = base_final.groupby('DEMANDA').agg(
        TOTAL_PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum')
    ).reset_index()
    calidad = calidad.sort_values(by='TOTAL_PIEZAS_SOLICITADAS', ascending=False)
    
    if not calidad.empty:
        mapa_colores = {
            "ALTA": "#11734b",       
            "MEDIA": "#ffb703",      
            "BAJA": "#fb8500",       
            "OBSOLETO": "#b10202"    
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
