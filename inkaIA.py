import os
import re
import json
import fitz
import pandas as pd
from tqdm import tqdm
from rich import print
import google.generativeai as genai
from IPython.display import display, Image
import streamlit as st
from PIL import Image
import pdfplumber
from io import BytesIO
import glob

# ========================================
# 1. Configuracion de las funciones para la lectura de facturas
# ========================================

# Configuracion de la API (usar variable de entorno en producción)
genai.configure(api_key="AIzaSyAtA779V7nuiiP5jzYi6jkN02fU8lsf1EM")

def response_json_to_dict(response_text):
    """Extrae JSON de la respuesta de Gemini"""
    match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None

def pdf_to_images(pdf_path, output_folder, pages):
    """Convierte páginas de PDF a imágenes"""
    doc = fitz.open(pdf_path)
    images = []
    for i in pages:
        pix = doc[i].get_pixmap(dpi=300)
        images.append(pix)
    return images

def extract_table_from_image(img, prompt):
    """Extrae datos de imagen usando Gemini AI"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    buffered.seek(0)
    image_bytes = buffered.read()

    response = model.generate_content([
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "image/png",
                "data": image_bytes
            }
        }
    ])
    return response.text

def extract_pdf_to_table_ventas(uploaded_files_ventas, opcion):
    """Función original para extraer ventas"""
    with pdfplumber.open(uploaded_files_ventas) as pdf:
        all_data = []

        codigos_por_empresa = {
            'WILLMACTEX S.A.C.': ['E001'], 
            'Inkaharvest': ['EB01', 'E001']
        }

        codigos_validos = codigos_por_empresa.get(opcion, [])
        if not codigos_validos:
            st.error("Empresa no reconocida. Selecciona otra opcion")
            return None
        
        for page in pdf.pages:
            text = page.extract_text()
            for line in text.split('\n'):
                if any(line.startswith(codigo) for codigo in codigos_validos):
                    parts = line.split()
                    if len(parts) < 6:
                        continue
                    fecha_emision = parts[-1]
                    numero = "".join(parts[2])
                    ruc = "".join(parts[3])
                    empresa_nombre = " ".join(parts[5:-2])
                    importe = parts[-2].replace("S/", "").replace(",", "")
                    all_data.append([fecha_emision, parts[0], numero, ruc, empresa_nombre, importe])

        if all_data:
            columns = ["Fecha de emision", "Codigo", "Numero", "RUC", "Empresa", "Importe Total"]
            df = pd.DataFrame(all_data, columns=columns)
            df['Importe Total'] = df['Importe Total'].astype(float)

            # Calcular Base Imponible e IGV solo para WILLMACTEX S.A.C.
            if opcion == "Inkaharvest":
                df['Base Imponible'] = round(df['Importe Total'], 2)

            df['Documento'] = df['Codigo'].apply(lambda x: "Factura" if x == "E001" else "Boleta")
            return df
        else:
            st.error("No se encontraron datos relevantes en el PDF.")
            return None

def extract_pdf_notas_credito_ventas(uploaded_files_nc, opcion):
    """
    NUEVA: Extrae notas de crédito de ventas desde PDF
    Las notas de crédito reducen el monto de las facturas originales
    """
    with pdfplumber.open(uploaded_files_nc) as pdf:
        all_data = []

        codigos_nc = {
            'Inkaharvest': ['EB01']
        }

        codigos_validos = codigos_nc.get(opcion, [])
        if not codigos_validos:
            st.error("Empresa no reconocida para notas de crédito")
            return None
        
        for page in pdf.pages:
            text = page.extract_text()
            for line in text.split('\n'):
                if any(line.startswith(codigo) for codigo in codigos_validos):
                    parts = line.split()
                    if len(parts) < 6:
                        continue
                    fecha_emision = parts[-1]
                    numero = "".join(parts[2])
                    ruc = "".join(parts[3])
                    empresa_nombre = " ".join(parts[5:-2])
                    importe = parts[-2].replace("S/", "").replace(",", "")
                    all_data.append([fecha_emision, parts[0], numero, ruc, empresa_nombre, importe])

        if all_data:
            columns = ["Fecha de emision", "Codigo", "Numero", "RUC", "Empresa", "Importe Total"]
            df = pd.DataFrame(all_data, columns=columns)
            df['Importe Total'] = df['Importe Total'].astype(float)

            # Para notas de crédito, el importe es negativo (reduce ventas)
            df['Importe Total'] = -df['Importe Total']

            if opcion == "Inkaharvest":
                df['Base Imponible'] = round(df['Importe Total'], 2)

            df['Documento'] = df['Codigo'].apply(lambda x: "Nota de Crédito" if x in ['E001', 'EB01'] else "Otro")
            return df
        else:
            st.warning("No se encontraron notas de crédito en el PDF.")
            return pd.DataFrame()

def consolidar_ventas_con_nc(df_ventas, df_nc):
    """
    NUEVA: Consolida ventas con notas de crédito
    """
    if df_ventas.empty and df_nc.empty:
        return pd.DataFrame(), {"error": "Ambos DataFrames están vacíos"}
    
    if df_nc.empty:
        return df_ventas, {
            "facturas": len(df_ventas), 
            "notas_credito": 0, 
            "total_facturas": df_ventas['Importe Total'].sum(),
            "total_nc": 0,
            "total_neto": df_ventas['Importe Total'].sum()
        }
    
    if df_ventas.empty:
        st.warning("⚠️ Solo hay notas de crédito sin facturas base")
        return df_nc, {
            "facturas": 0, 
            "notas_credito": len(df_nc),
            "total_facturas": 0,
            "total_nc": df_nc['Importe Total'].sum(),
            "total_neto": df_nc['Importe Total'].sum()
        }
    
    # Combinar ambos DataFrames
    df_consolidado = pd.concat([df_ventas, df_nc], ignore_index=True)
    
    # Ordenar por fecha
    df_consolidado['Fecha de emision'] = pd.to_datetime(df_consolidado['Fecha de emision'], errors='coerce')
    df_consolidado = df_consolidado.sort_values('Fecha de emision')
    
    # Calcular reporte
    total_facturas = df_ventas['Importe Total'].sum()
    total_nc = abs(df_nc['Importe Total'].sum()) if not df_nc.empty else 0
    total_neto = df_consolidado['Importe Total'].sum()
    
    reporte = {
        "facturas": len(df_ventas),
        "notas_credito": len(df_nc),
        "total_facturas": total_facturas,
        "total_nc": total_nc,
        "total_neto": total_neto,
        "reduccion_porcentaje": (total_nc / total_facturas * 100) if total_facturas > 0 else 0
    }
    
    return df_consolidado, reporte

# ========================================
# 2. NUEVAS FUNCIONES HÍBRIDAS PARA COMPRAS
# ========================================

def extract_pdf_sunat_compras(uploaded_file_compras_sunat):
    """
    NUEVA: Extrae datos de compras desde PDF descargado de SUNAT
    """
    try:
        with pdfplumber.open(uploaded_file_compras_sunat) as pdf:
            all_data = []
            
            for page in pdf.pages:
                text = page.extract_text()
                
                if not text:
                    continue
                    
                for line in text.split('\n'):
                    line = line.strip()
                    
                    if re.match(r'^E\d{3}\s*-', line):
                        try:
                            pattern = r'^(E\d{3})\s*-\s*(\d+)\s+(\d{11})\s*-\s*(.+?)\s+(S/[\d,]+\.\d{2})\s+(\d{2}/\d{2}/\d{4})'
                            match = re.match(pattern, line)
                            
                            if match:
                                tipo_doc = match.group(1)
                                num_doc = match.group(2)
                                ruc = match.group(3)
                                razon_social = match.group(4).strip()
                                importe_str = match.group(5)
                                fecha = match.group(6)
                                
                                importe = float(importe_str.replace('S/', '').replace(',', ''))
                                
                                base_imponible = round(importe / 1.18, 2)
                                igv = round(importe - base_imponible, 2)
                                tiene_igv = "SI" if igv > 0 else "NO"
                                
                                numero_completo = f"{tipo_doc}-{num_doc}"
                                
                                if tipo_doc == "E001":
                                    tipo_documento = "Factura"
                                elif tipo_doc == "E002":
                                    tipo_documento = "Boleta"
                                elif tipo_doc == "E003":
                                    tipo_documento = "Nota de Crédito"
                                elif tipo_doc == "E008":
                                    tipo_documento = "Nota de Débito"
                                else:
                                    tipo_documento = "Otro"
                                
                                all_data.append([
                                    fecha,
                                    numero_completo,
                                    ruc,
                                    razon_social,
                                    importe,
                                    base_imponible,
                                    igv,
                                    tiene_igv,
                                    tipo_documento,
                                    "PDF_SUNAT"
                                ])
                                
                        except Exception as e:
                            st.warning(f"Error procesando línea: {line[:50]}... Error: {str(e)}")
                            continue
            
            if all_data:
                columns = [
                    "FECHA EMISION", 
                    "NroDocumento", 
                    "RUC", 
                    "EMPRESA", 
                    "TOTAL PAGADO",
                    "Base Imponible",
                    "IGV 18%", 
                    "IGV", 
                    "Tipo Documento",
                    "Fuente"
                ]
                
                df = pd.DataFrame(all_data, columns=columns)
                
                df['FECHA EMISION'] = pd.to_datetime(df['FECHA EMISION'], format='%d/%m/%Y', errors='coerce')
                df['TOTAL PAGADO'] = df['TOTAL PAGADO'].astype(float)
                df['Base Imponible'] = df['Base Imponible'].astype(float)
                df['IGV 18%'] = df['IGV 18%'].astype(float)
                df['RUC'] = df['RUC'].astype(str)
                
                df = df.drop_duplicates(subset=['RUC', 'NroDocumento', 'FECHA EMISION'])
                df = df.sort_values('FECHA EMISION')
                
                return df
                
            else:
                st.warning("No se encontraron facturas válidas en el PDF de SUNAT")
                return pd.DataFrame()
                
    except Exception as e:
        st.error(f"Error procesando PDF de SUNAT: {str(e)}")
        return pd.DataFrame()

def merge_compras_hibrido(df_sunat, df_ocr):
    """
    NUEVA: Combina datos de PDF SUNAT con datos de OCR
    """
    if df_sunat.empty and df_ocr.empty:
        return pd.DataFrame(), {"error": "Ambos DataFrames están vacíos"}
    
    if df_sunat.empty:
        df_ocr['Fuente'] = 'OCR'
        return df_ocr, {"sunat": 0, "ocr": len(df_ocr), "duplicados": 0}
    
    if df_ocr.empty:
        return df_sunat, {"sunat": len(df_sunat), "ocr": 0, "duplicados": 0}
    
    if 'Fuente' not in df_ocr.columns:
        df_ocr['Fuente'] = 'OCR'
    
    df_ocr_norm = df_ocr.copy()
    
    if 'FECHA EMISION' in df_ocr_norm.columns:
        df_ocr_norm['FECHA EMISION'] = pd.to_datetime(df_ocr_norm['FECHA EMISION'], errors='coerce')
    
    duplicados = []
    for idx_ocr, row_ocr in df_ocr_norm.iterrows():
        coincidencias = df_sunat[
            (df_sunat['RUC'] == row_ocr['RUC']) & 
            (df_sunat['FECHA EMISION'].dt.date == row_ocr['FECHA EMISION'].date())
        ]
        
        if not coincidencias.empty:
            duplicados.append(idx_ocr)
    
    df_ocr_filtrado = df_ocr_norm.drop(duplicados)
    
    df_consolidado = pd.concat([df_sunat, df_ocr_filtrado], ignore_index=True)
    df_consolidado = df_consolidado.sort_values('FECHA EMISION')
    
    reporte = {
        "sunat": len(df_sunat),
        "ocr_original": len(df_ocr),
        "ocr_agregado": len(df_ocr_filtrado),
        "duplicados_removidos": len(duplicados),
        "total_consolidado": len(df_consolidado)
    }
    
    return df_consolidado, reporte

def validar_datos_compras(df):
    """
    NUEVA: Valida la calidad de los datos extraídos
    """
    if df.empty:
        return {"valido": False, "errores": ["DataFrame vacío"]}
    
    errores = []
    warnings = []
    
    rucs_invalidos = df[~df['RUC'].str.match(r'^\d{11}$', na=False)]
    if not rucs_invalidos.empty:
        errores.append(f"{len(rucs_invalidos)} RUCs inválidos")
    
    fechas_invalidas = df[df['FECHA EMISION'].isna()]
    if not fechas_invalidas.empty:
        warnings.append(f"{len(fechas_invalidas)} fechas inválidas")
    
    montos_invalidos = df[(df['TOTAL PAGADO'] <= 0) | (df['TOTAL PAGADO'].isna())]
    if not montos_invalidos.empty:
        errores.append(f"{len(montos_invalidos)} montos inválidos")
    
    estadisticas = {
        "total_registros": len(df),
        "total_importe": df['TOTAL PAGADO'].sum(),
        "total_igv": df['IGV 18%'].sum(),
        "facturas_con_igv": len(df[df['IGV'] == 'SI']),
        "rango_fechas": f"{df['FECHA EMISION'].min()} a {df['FECHA EMISION'].max()}" if not df['FECHA EMISION'].isna().all() else "Sin fechas válidas"
    }
    
    return {
        "valido": len(errores) == 0,
        "errores": errores,
        "warnings": warnings,
        "estadisticas": estadisticas
    }

# ========================================
# 3. Entorno Streamlit MEJORADO
# ========================================

st.set_page_config(
    page_title="Sistema Tributario Híbrido",
    page_icon="🧾",
    layout="wide"
)

st.sidebar.title("Menú de configuración")

with st.sidebar.expander("Mostrar filtros"):
    opcion = st.selectbox("Elige una opción", ["Inkaharvest"])

st.title(f"Sistema Tributario Híbrido - {opcion}")
st.write('''
**Versión 2.0 - Híbrida y Escalable**

Esta herramienta optimizada combina:
- **Extracción instantánea** desde PDFs de SUNAT (90% de facturas, $0 costo)
- **OCR inteligente** para facturas adicionales (solo cuando necesario)

''')

tabs = st.tabs(["🔄 Procesamiento de facturas", "📊 Reportes Consolidados"])

# ========================================
# PESTAÑA 1: PROCESAMIENTO HÍBRIDO
# ========================================
with tabs[0]:
    periodos = [
        '202501', '202502', '202503', '202504', '202505', '202506', 
        '202507', '202508', '202509', '202510', '202511', '202512'
    ]
    
    periodos_sb = st.selectbox('📅 Selecciona un periodo', periodos)
    
    # ========================================
    # SECCIÓN VENTAS (Mejorada con flags)
    # ========================================
    st.header('💰 Análisis de Ventas')

    if 'ventas' not in st.session_state:
        st.session_state.ventas = pd.DataFrame()

    if 'notas_credito' not in st.session_state:
        st.session_state.notas_credito = pd.DataFrame()
    
    if 'ventas_consolidado' not in st.session_state:
        st.session_state.ventas_consolidado = pd.DataFrame()

    # Subsección 1: Facturas y Boletas
    st.subheader('📄 Facturas y Boletas de Venta')

    # Inicializar flag de procesamiento
    if 'ventas_procesadas' not in st.session_state:
        st.session_state.ventas_procesadas = False

    uploaded_files_ventas = st.file_uploader(
        '📄 Sube archivos PDF de ventas', 
        type=["pdf"], 
        accept_multiple_files=True,
        key="ventas_upload"
    )
    
    if uploaded_files_ventas and not st.session_state.ventas_procesadas:
        with st.spinner('🔄 Procesando facturas de ventas...'):
            for pdf_file in uploaded_files_ventas:
                ventas = extract_pdf_to_table_ventas(pdf_file, opcion)
                if ventas is not None:
                    st.session_state.ventas = pd.concat([st.session_state.ventas, ventas], ignore_index=True)
            
            if not st.session_state.ventas.empty:
                st.session_state.ventas = st.session_state.ventas.drop_duplicates()
                st.session_state.ventas_procesadas = True
                st.success(f'✅ Extraídas {len(st.session_state.ventas)} facturas de ventas')
    
    elif st.session_state.ventas_procesadas:
        st.info(f'📄 {len(st.session_state.ventas)} facturas de ventas ya cargadas')
        if st.button('🔄 Limpiar y cargar nuevas facturas de ventas'):
            st.session_state.ventas = pd.DataFrame()
            st.session_state.ventas_procesadas = False
            st.rerun()

    # Subsección 2: Notas de Crédito
    st.subheader('📝 Notas de Crédito de Ventas')

    if 'nc_procesadas' not in st.session_state:
        st.session_state.nc_procesadas = False

    uploaded_files_nc = st.file_uploader(
        '📝 Sube archivos PDF de notas de crédito', 
        type=["pdf"], 
        accept_multiple_files=True,
        key="nc_upload",
        help="Solo notas de crédito que reduzcan las ventas del período"
    )
    
    if uploaded_files_nc and not st.session_state.nc_procesadas:
        with st.spinner('🔄 Procesando notas de crédito...'):
            for pdf_file in uploaded_files_nc:
                nc = extract_pdf_notas_credito_ventas(pdf_file, opcion)
                if nc is not None and not nc.empty:
                    st.session_state.notas_credito = pd.concat([st.session_state.notas_credito, nc], ignore_index=True)
            
            if not st.session_state.notas_credito.empty:
                st.session_state.notas_credito = st.session_state.notas_credito.drop_duplicates()
                st.session_state.nc_procesadas = True
                st.success(f'✅ Extraídas {len(st.session_state.notas_credito)} notas de crédito')
                    
                with st.expander("Ver notas de crédito"):
                    df_display = st.session_state.notas_credito.copy()
                    df_display['Importe Total'] = abs(df_display['Importe Total'])
                    df_display['Base Imponible'] = abs(df_display['Base Imponible']) if 'Base Imponible' in df_display.columns else 0
                    df_display['IGV'] = abs(df_display['IGV']) if 'IGV' in df_display.columns else 0
                    st.dataframe(df_display, use_container_width=True)
    
    elif st.session_state.nc_procesadas:
        st.info(f'📝 {len(st.session_state.notas_credito)} notas de crédito ya cargadas')
        if st.button('🔄 Limpiar y cargar nuevas notas de crédito'):
            st.session_state.notas_credito = pd.DataFrame()
            st.session_state.nc_procesadas = False
            st.rerun()
    
    # Subsección 3: Consolidación de Ventas
    if not st.session_state.ventas.empty or not st.session_state.notas_credito.empty:
        st.subheader('🔄 Consolidación de Ventas')
        
        if st.button('🔀 Consolidar Ventas con Notas de Crédito', use_container_width=True, type="primary"):
            df_ventas_consolidado, reporte_ventas = consolidar_ventas_con_nc(
                st.session_state.ventas, 
                st.session_state.notas_credito
            )
            
            if not df_ventas_consolidado.empty:
                st.session_state.ventas_consolidado = df_ventas_consolidado
                
                st.success("✅ Consolidación de ventas completada")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📄 Facturas/Boletas", reporte_ventas["facturas"])
                with col2:
                    st.metric("📝 Notas Crédito", reporte_ventas["notas_credito"])
                with col3:
                    st.metric("💰 Ventas Brutas S/", f"{reporte_ventas['total_facturas']:,.2f}")
                with col4:
                    st.metric("💸 Reducción S/", f"{reporte_ventas['total_nc']:,.2f}")

                with st.expander("🔍 Ver ventas consolidadas"):
                    st.dataframe(df_ventas_consolidado, use_container_width=True)
    
    st.divider()
    
    # ========================================
    # SECCIÓN COMPRAS HÍBRIDA (Mejorada con flags)
    # ========================================
    st.header('🛒 Análisis de Compras - Sistema Híbrido')
    
    if 'df_sunat_compras' not in st.session_state:
        st.session_state.df_sunat_compras = pd.DataFrame()
    if 'df_ocr_compras' not in st.session_state:
        st.session_state.df_ocr_compras = pd.DataFrame()
    if 'df_compras_consolidado' not in st.session_state:
        st.session_state.df_compras_consolidado = pd.DataFrame()
    
    # PASO 1: PDF SUNAT (Prioridad)
    st.subheader('📋 Paso 1: Extracción desde PDF SUNAT')
    
    if 'sunat_procesado' not in st.session_state:
        st.session_state.sunat_procesado = False
    
    uploaded_sunat_pdf = st.file_uploader(
        '📄 Sube tu PDF de SUNAT con facturas recibidas del período', 
        type=["pdf"], 
        key="sunat_compras",
        help="Descargar desde SUNAT > Operaciones en Línea > Consulta de Comprobantes"
    )
    
    if uploaded_sunat_pdf and not st.session_state.sunat_procesado:
        with st.spinner('🔄 Extrayendo datos desde PDF SUNAT...'):
            df_sunat = extract_pdf_sunat_compras(uploaded_sunat_pdf)
            if not df_sunat.empty:
                st.session_state.df_sunat_compras = df_sunat
                st.session_state.sunat_procesado = True
                st.success(f'✅ Extraídas {len(df_sunat)} facturas desde PDF SUNAT')
                
                with st.expander("🔍 Ver facturas extraídas de SUNAT"):
                    st.dataframe(df_sunat, use_container_width=True)
                
                validacion = validar_datos_compras(df_sunat)
                if validacion['warnings']:
                    for warning in validacion['warnings']:
                        st.warning(f"⚠️ {warning}")
    
    elif st.session_state.sunat_procesado:
        st.info(f'📋 {len(st.session_state.df_sunat_compras)} facturas SUNAT ya cargadas')
        if st.button('🔄 Limpiar y cargar nuevo PDF SUNAT'):
            st.session_state.df_sunat_compras = pd.DataFrame()
            st.session_state.sunat_procesado = False
            st.rerun()
    
    # PASO 2: OCR Complementario
    st.subheader('📸 Paso 2: Facturas Adicionales por OCR (Opcional)')
    
    if 'ocr_procesado' not in st.session_state:
        st.session_state.ocr_procesado = False
    
    if not st.session_state.df_sunat_compras.empty:
        st.info('💡 Sube solo las facturas que NO aparecen en el PDF de SUNAT')
    else:
        st.warning('⚠️ Sin PDF SUNAT, todas las facturas se procesarán por OCR (mayor costo)')
    
    uploaded_files_compras_ocr = st.file_uploader(
        '🖼️ Sube facturas adicionales (PDF, PNG, JPG, JPEG)', 
        type=["pdf", "png", "jpg", "jpeg"], 
        accept_multiple_files=True,
        key="ocr_compras"
    )
    
    if uploaded_files_compras_ocr and not st.session_state.ocr_procesado:
        todas_las_filas = []
        
        prompt = '''
Extrae los siguientes datos de una factura a partir de esta imagen:

- FECHA EMISION
- MONEDA
- TOTAL PAGADO (puede figurar como: total a pagar, importe total, total)
- IGV: si el valor es 0 o no aparece, colocar "NO", si es mayor a 0 colocar "SI"
- RUC (debe ser distinto de 20610930213)
- Empresa (debe ser distinto a INKAHARVEST S.A.C.)
- Base Imponible (Puede figurar como Valor de venta o literalmente Base Imponibe, es el que esta encima del igv)

Devuélvelo como un único bloque JSON en este formato:

{
"numero_documento": "E001-7206",
"detalle": [
    {
    "FECHA EMISION": "2025-05-28",
    "MONEDA": "SOLES",
    "RUC": "20513491990",
    "EMPRESA": "PROVEEDOR S.A.C.",
    "IGV": "SI",
    "TOTAL PAGADO": "350.00",
    "Base Imponible": "296.61"
    }
]
}

No expliques nada. Solo responde con ese bloque JSON.
        '''
        
        with st.spinner("🤖 Procesando facturas por OCR (esto consume tokens)..."):
            costo_estimado = len(uploaded_files_compras_ocr) * 0.10
            
            for uploaded_file in uploaded_files_compras_ocr:
                filename = uploaded_file.name
                ext = os.path.splitext(filename)[1].lower()

                if ext == ".pdf":
                    temp_pdf_path = f"temp_{filename}"
                    with open(temp_pdf_path, "wb") as f:
                        f.write(uploaded_file.read())

                    doc_temp = fitz.open(temp_pdf_path)
                    total_paginas = doc_temp.page_count
                    paginas = list(range(total_paginas))
                    doc_temp.close()

                    pixmaps = pdf_to_images(temp_pdf_path, output_folder=None, pages=paginas)
                    imagenes = [Image.frombytes("RGB", (pix.width, pix.height), pix.samples) for pix in pixmaps]
                    os.remove(temp_pdf_path)
                else:
                    img = Image.open(uploaded_file)
                    imagenes = [img]

                for img in imagenes:
                    texto = extract_table_from_image(img, prompt)
                    json_result = response_json_to_dict(texto)

                    if json_result and "detalle" in json_result:
                        try:
                            df = pd.DataFrame(json_result["detalle"])
                            columnas_deseadas = [
                                "FECHA EMISION", "MONEDA", "RUC", "EMPRESA", "IGV", "TOTAL PAGADO", "Base Imponible"
                            ]
                            df = df[[col for col in columnas_deseadas if col in df.columns]]
                            numero_doc = json_result.get("numero_documento", "")
                            df["NroDocumento"] = numero_doc
                            todas_las_filas.append(df)
                        except Exception as e:
                            st.warning(f"Error procesando {filename}: {e}")

        if todas_las_filas:
            df_ocr = pd.concat(todas_las_filas, ignore_index=True)
            df_ocr["IGV 18%"] = df_ocr.apply(
                lambda row: round((float(row["TOTAL PAGADO"]) / 1.18) * 0.18, 2) 
                if row["IGV"] == "SI" else 0.00, axis=1
            )
            st.session_state.df_ocr_compras = df_ocr
            st.session_state.ocr_procesado = True
            
            st.success(f'✅ Procesadas {len(df_ocr)} facturas por OCR')
            
            with st.expander("🔍 Ver facturas procesadas por OCR"):
                st.dataframe(df_ocr, use_container_width=True)
    
    elif st.session_state.ocr_procesado:
        st.info(f'🤖 {len(st.session_state.df_ocr_compras)} facturas OCR ya procesadas')
        if st.button('🔄 Limpiar y procesar nuevas facturas OCR'):
            st.session_state.df_ocr_compras = pd.DataFrame()
            st.session_state.ocr_procesado = False
            st.rerun()
    
    # CONSOLIDACIÓN HÍBRIDA
    if not st.session_state.df_sunat_compras.empty or not st.session_state.df_ocr_compras.empty:
        st.subheader('🔄 Consolidación Híbrida')
        
        if st.button('🔀 Consolidar Datos de Compras', use_container_width=True, type="primary"):
            df_consolidado, reporte = merge_compras_hibrido(
                st.session_state.df_sunat_compras, 
                st.session_state.df_ocr_compras
            )
            
            if not df_consolidado.empty:
                st.session_state.df_compras_consolidado = df_consolidado
                
                st.success("✅ Consolidación completada")
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📋 SUNAT", reporte.get("sunat", 0))
                with col2:
                    st.metric("🤖 OCR Agregado", reporte.get("ocr_agregado", 0))
                with col3:
                    st.metric("🔄 Duplicados Removidos", reporte.get("duplicados_removidos", 0))
                with col4:
                    st.metric("📊 Total Final", reporte.get("total_consolidado", 0))
                
                with st.expander("🔍 Ver datos consolidados"):
                    st.dataframe(df_consolidado, use_container_width=True)
    
    # RESUMEN Y GUARDADO
    if (not st.session_state.ventas_consolidado.empty or not st.session_state.ventas.empty) and not st.session_state.df_compras_consolidado.empty:
        st.divider()
        st.header('📊 Resumen del Período')
        
        df_ventas_final = st.session_state.ventas_consolidado if not st.session_state.ventas_consolidado.empty else st.session_state.ventas
        
        st.subheader('💰 Resumen Ventas')
        
        if not st.session_state.ventas_consolidado.empty:
            #ventas_brutas = st.session_state.ventas['Importe Total'].sum() if not st.session_state.ventas.empty else 0
            ventas_facturas = st.session_state.ventas[st.session_state.ventas['Documento'] == 'Factura']['Importe Total'].sum() if not st.session_state.ventas.empty else 0
            ventas_boleta = st.session_state.ventas[st.session_state.ventas['Documento'] == 'Boleta']['Importe Total'].sum() if not st.session_state.ventas.empty else 0
            nc_total = abs(st.session_state.notas_credito['Importe Total'].sum()) if not st.session_state.notas_credito.empty else 0
            bi_ventas = df_ventas_final['Base Imponible'].sum()
            ventas_netas = ventas_facturas + ventas_boleta
            renta_ventas = round(bi_ventas * 0.010, 0)
            
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Venta Facturas S/", f"{ventas_facturas:,.0f}")
            with c2:
                st.metric("Venta Boletas S/", f"{ventas_boleta:,.0f}")
            with c3:
                st.metric("Ventas Netas S/", f"{ventas_netas:,.0f}")

        st.subheader('Resumen Compras')

        df_compras_final = st.session_state.df_compras_consolidado
        #cantidad_facturas_compras = len(df_compras_final)
        df_compras_final['TOTAL PAGADO'] = pd.to_numeric(df_compras_final['TOTAL PAGADO'], errors='coerce')
        df_compras_final['Base Imponible'] = pd.to_numeric(df_compras_final['TOTAL PAGADO'], errors='coerce')
        total_baseImponible = round(df_compras_final['Base Imponible'].sum(), 2)
        total_baseImponible = round(df_compras_final[df_compras_final['IGV'] == "SI"]['Base Imponible'].sum(), 2)
        total_facturado_compras = round(df_compras_final['TOTAL PAGADO'].sum(), 2)
        total_igv_compras = round(df_compras_final['IGV 18%'].sum(), 0)

        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric("Compras no gravadas S/", f"{total_baseImponible:,.0f}")
        with k2:
            st.metric("IGV compras S/", f"{total_igv_compras:,.0f}")
        with k3:
            st.metric("Total Comprado S/", f"{total_facturado_compras:,.0f}")

        st.subheader('Impuestos por pagar')
        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric("📄 Total renta a pagar", f"{renta_ventas:,.0f}")

        st.subheader('💾 Guardar Reporte')
        if st.button('📁 Guardar Reporte Consolidado', use_container_width=True, type="secondary"):
            carpeta_salida = r'C:\Users\Dussand\OneDrive\Desktop\BPA\Impuestos\inkaharavest\2025\Reportes_consolidados'
            os.makedirs(carpeta_salida, exist_ok=True)
            
            nombre_archivo = f'reporte_consolidado_{periodos_sb}.xlsx'
            ruta_archivo = os.path.join(carpeta_salida, nombre_archivo)

            try:
                with pd.ExcelWriter(ruta_archivo, engine='xlsxwriter') as writer:
                    df_ventas_final.to_excel(writer, index=False, sheet_name=f'Ventas_{periodos_sb}')
                    df_compras_final.to_excel(writer, index=False, sheet_name=f'Compras_{periodos_sb}')

                st.success(f'✅ Reporte guardado: {nombre_archivo}')
                
                hojas_info = [f"Ventas: {len(df_ventas_final)} registros", 
                             f"Compras: {len(df_compras_final)} registros"]
              
                st.info("📋 Hojas incluidas: " + " | ".join(hojas_info))
                
            except Exception as e:
                st.error(f"Error guardando archivo: {e}")