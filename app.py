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

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

CREDENTIALS = {"CRA REFACCIONES": "REFACCIONES2026."}

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
    with col1: selected_user = st.selectbox("Selecciona Usuario:", list(CREDENTIALS.keys()))
    with col2: input_pass = st.text_input("Contraseña:", type="password")
    if st.button("Ingresar al Sistema"): check_login(selected_user, input_pass)
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
        st.error(f"⚠️ Error al generar credenciales: {e}")
        st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def cargar_base_maestra():
    FILE_ID = "1ql3_qPjMK167EfWVuQK1m-Cjm3a6TPy4"
    URL_DRIVE = f"https://www.googleapis.com/drive/v3/files/{FILE_ID}?alt=media"
    headers_robot = get_auth_headers()
    
    try:
        res = requests.get(URL_DRIVE, headers=headers_robot)
        if res.status_code == 200:
            df = pd.read_excel(io.BytesIO(res.content))
            
            # Limpiador de formatos
            numeric_cols = ['CANT_SOLICITADA', 'CANT_FACTURADA', 'CANT_FACTURADA_APOYO', 
                            'PIEZAS_NO_FACTURADAS', 'EXISTENCIA', 'CAPITAL_INMOVILIZADO']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # Maquillaje de Emojis
            mapa_emojis = {
                "CUMPLIDO": "✅ CUMPLIDO",
                "ESTANCADO": "🚨 ESTANCADO",
                "FALTA POR FACTURAR": "⚠️ FALTA POR FACTURAR",
                "APOYO DE VENTA": "🤝 APOYO DE VENTA",
                "SIN STOCK SUFICIENTE": "❌ SIN STOCK"
            }
            if 'ALERTA' in df.columns:
                df['ALERTA'] = df['ALERTA'].map(mapa_emojis).fillna(df['ALERTA'])
                
            return df
        else:
            st.error("Error de acceso al servidor de Google.")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Error crítico al leer la Base Maestra: {e}")
        return pd.DataFrame()

# ==========================================
# 2. CARGA DE DATOS Y FILTROS GLOBALES
# ==========================================
with st.spinner("🤖 Conectando con la Base Maestra..."):
    base_final = cargar_base_maestra()

if base_final.empty:
    st.warning("No se encontraron datos en el archivo maestro.")
    st.stop()

st.sidebar.header("Filtros Globales")
lista_vendedores = ["Todos"] + sorted(base_final['VENDEDOR'].dropna().unique().tolist())
filtro_vendedor = st.sidebar.selectbox("Vendedor:", lista_vendedores)

if filtro_vendedor != "Todos":
    base_final = base_final[base_final['VENDEDOR'] == filtro_vendedor]

# ==========================================
# 3. MÉTRICAS GLOBALES SUPERIORES
# ==========================================
st.markdown("---")
mask_riesgo = base_final['ALERTA'].isin(["🚨 ESTANCADO", "⚠️ FALTA POR FACTURAR", "🤝 APOYO DE VENTA"])
df_riesgo = base_final[mask_riesgo].copy()

total_pdte = base_final['PIEZAS_NO_FACTURADAS'].sum()
capital_riesgo = df_riesgo['CAPITAL_INMOVILIZADO'].sum()
total_apoyo = base_final['CANT_FACTURADA_APOYO'].sum()

total_solicitado = base_final['CANT_SOLICITADA'].sum()
total_facturado = base_final['CANT_FACTURADA'].sum()
efectividad_global = (total_facturado / total_solicitado) * 100 if total_solicitado > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("📦 Total Piezas Faltantes", f"{total_pdte:,.0f}")
col2.metric("💸 Capital en Riesgo (Estancado)", f"${capital_riesgo:,.2f}")
col3.metric("🤝 Piezas Vendidas en Apoyo", f"{total_apoyo:,.0f}")
col4.metric("📈 Efectividad Sucursal", f"{efectividad_global:.1f}%")
st.markdown("---")

columnas_vista = [
    'VENDEDOR', 'NP', 'DESCRIPCIÓN', 'TIPO DE PEDIDO', 'DEMANDA', 'FECHA_SOLICITUD', 
    'INGRESO DE COMPRA', 'FECHA_VENTA', 'CANT_SOLICITADA', 'CANT_FACTURADA', 
    'CANT_FACTURADA_APOYO', 'PIEZAS_NO_FACTURADAS', 'EXISTENCIA', 'CAPITAL_INMOVILIZADO', 'ALERTA'
]
cols_finales = [c for c in columnas_vista if c in base_final.columns]

# ==========================================
# 4. GRÁFICOS GERENCIALES
# ==========================================
row1_col1, row1_col2 = st.columns(2)

with row1_col1:
    st.subheader("📊 Capital en Riesgo por Vendedor")
    if capital_riesgo > 0:
        grafico_capital = df_riesgo.groupby('VENDEDOR')['CAPITAL_INMOVILIZADO'].sum().reset_index()
        grafico_capital = grafico_capital[grafico_capital['CAPITAL_INMOVILIZADO'] > 0]
        fig_cap = px.bar(grafico_capital, x='VENDEDOR', y='CAPITAL_INMOVILIZADO', text_auto='.2s', color_discrete_sequence=['#d90429'])
        fig_cap.update_layout(xaxis_title="", yaxis_title="MXN ($)", margin=dict(t=20, b=0))
        st.plotly_chart(fig_cap, use_container_width=True)
    else:
        st.success("No hay capital en riesgo actualmente.")

with row1_col2:
    st.subheader("🔥 Top 5 Refacciones Críticas (Dinero Estancado)")
    if capital_riesgo > 0:
        # Modificado para incluir VENDEDOR y DEMANDA
        top_refacciones = df_riesgo.groupby(['VENDEDOR', 'NP', 'DESCRIPCIÓN', 'DEMANDA'])['CAPITAL_INMOVILIZADO'].sum().reset_index()
        top_refacciones = top_refacciones.sort_values(by='CAPITAL_INMOVILIZADO', ascending=False).head(5)
        st.dataframe(
            top_refacciones.style.format({'CAPITAL_INMOVILIZADO': '${:,.2f}'}),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("Sin refacciones críticas.")
st.markdown("---")

row2_col1, row2_col2 = st.columns(2)

with row2_col1:
    st.subheader("🎯 Desempeño de Venta por Asesor")
    mask_evaluable = (base_final['CANT_FACTURADA'] > 0) | (base_final['CANT_FACTURADA_APOYO'] > 0) | (base_final['EXISTENCIA'] >= base_final['CANT_SOLICITADA'])
    df_evaluable = base_final[mask_evaluable]
    
    if not df_evaluable.empty:
        desempeno = df_evaluable.groupby('VENDEDOR').agg(
            PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum'),
            PIEZAS_FACT_PROPIAS=('CANT_FACTURADA', 'sum'),
            PIEZAS_APOYO=('CANT_FACTURADA_APOYO', 'sum')
        ).reset_index()
        
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
            use_container_width=True, hide_index=True
        )

with row2_col2:
    st.subheader("🍩 Distribución de Solicitudes (Por Demanda)")
    calidad = base_final.groupby('DEMANDA').agg(
        TOTAL_PIEZAS_SOLICITADAS=('CANT_SOLICITADA', 'sum')
    ).reset_index()
    
    if not calidad.empty:
        mapa_colores = {
            "ALTA": "#11734b",       
            "MEDIA": "#ffb703",      
            "BAJA": "#fb8500",       
            "OBSOLETO": "#b10202"    
        }
        
        # Nuevo Gráfico de Dona para ver la distribución
        fig_pie = px.pie(
            calidad, 
            names="DEMANDA", 
            values="TOTAL_PIEZAS_SOLICITADAS", 
            color="DEMANDA",
            color_discrete_map=mapa_colores,
            hole=0.4 # Esto lo convierte en dona
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(showlegend=False, margin=dict(t=20, b=0))
        
        st.plotly_chart(fig_pie, use_container_width=True)

st.markdown("---")

# ==========================================
# 5. TABLAS DE AUDITORÍA
# ==========================================
st.subheader("🚨 Detalle de Focos de Atención (Riesgos y Apoyos)")
# Filtro actualizado: Solo mostrar Estancado, Falta por facturar y Apoyo (se excluye SIN STOCK)
mask_alertas_focos = base_final['ALERTA'].isin(["🚨 ESTANCADO", "⚠️ FALTA POR FACTURAR", "🤝 APOYO DE VENTA"])
df_alertas_focos = base_final[mask_alertas_focos].sort_values(by='CAPITAL_INMOVILIZADO', ascending=False)

if not df_alertas_focos.empty:
    st.dataframe(
        df_alertas_focos[cols_finales].style.format({
            'CANT_SOLICITADA': '{:,.0f}', 'CANT_FACTURADA': '{:,.0f}',
            'CANT_FACTURADA_APOYO': '{:,.0f}', 'PIEZAS_NO_FACTURADAS': '{:,.0f}',
            'EXISTENCIA': '{:,.0f}', 'CAPITAL_INMOVILIZADO': '${:,.2f}'
        }), 
        use_container_width=True, hide_index=True
    )
else:
    st.success("¡Excelente! No hay alertas estancadas o con falta de facturación.")

st.markdown("---")
with st.expander("Ver Base Maestra Completa (Histórico)"):
    st.dataframe(
        base_final[cols_finales].style.format({
            'CANT_SOLICITADA': '{:,.0f}', 'CANT_FACTURADA': '{:,.0f}',
            'CANT_FACTURADA_APOYO': '{:,.0f}', 'PIEZAS_NO_FACTURADAS': '{:,.0f}',
            'EXISTENCIA': '{:,.0f}', 'CAPITAL_INMOVILIZADO': '${:,.2f}'
        }), 
        use_container_width=True, hide_index=True
    )
