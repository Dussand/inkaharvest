import telebot
import pandas as pd
import re
import os
import json
import fitz
import google.generativeai as genai
from datetime import datetime
from PIL import Image
from io import BytesIO

# Token del bot
TOKEN = "8354742024:AAGKKxsSmk6Gg5DN49xEGC1mDfTuy6wBh3Y"
bot = telebot.TeleBot(TOKEN)

# Configurar Gemini AI
genai.configure(api_key="AIzaSyCWjbDeokKP7xQ-Egl2PzuQVWtBPosgwok")

# Funciones auxiliares de OCR
def response_json_to_dict(response_text):
    """Extrae JSON de la respuesta de Gemini"""
    match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None

def pdf_to_images(pdf_path, pages):
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

def extract_pdf_ocr_compras(pdf_path):
    """
    Extrae facturas usando OCR con IA
    """
    prompt = '''
    Extrae los siguientes datos de una factura a partir de esta imagen:

    - FECHA EMISION
    - MONEDA
    - TOTAL PAGADO (puede figurar como: total a pagar, importe total, total)
    - IGV: si el valor es 0 o no aparece, colocar "NO", si es mayor a 0 colocar "SI"
    - RUC (debe ser distinto de 20610930213)
    - Empresa (debe ser distinto a INKAHARVEST S.A.C.)

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
        "TOTAL PAGADO": "350.00"
        }
    ]
    }

    No expliques nada. Solo responde con ese bloque JSON.
    '''
    
    try:
        # Convertir PDF a imágenes
        doc = fitz.open(pdf_path)
        total_paginas = doc.page_count
        paginas = list(range(total_paginas))
        doc.close()

        pixmaps = pdf_to_images(pdf_path, paginas)
        imagenes = [Image.frombytes("RGB", (pix.width, pix.height), pix.samples) for pix in pixmaps]

        todas_las_filas = []
        
        for img in imagenes:
            texto = extract_table_from_image(img, prompt)
            json_result = response_json_to_dict(texto)

            if json_result and "detalle" in json_result:
                try:
                    df = pd.DataFrame(json_result["detalle"])
                    columnas_deseadas = [
                        "FECHA EMISION", "MONEDA", "RUC", "EMPRESA", "IGV", "TOTAL PAGADO"
                    ]
                    df = df[[col for col in columnas_deseadas if col in df.columns]]
                    numero_doc = json_result.get("numero_documento", "")
                    df["NroDocumento"] = numero_doc
                    todas_las_filas.append(df)
                except Exception as e:
                    print(f"Error procesando página: {e}")

        if todas_las_filas:
            df_ocr = pd.concat(todas_las_filas, ignore_index=True)
            
            # Calcular IGV y normalizar columnas
            df_ocr["IGV 18%"] = df_ocr.apply(
                lambda row: round((float(row["TOTAL PAGADO"]) / 1.18) * 0.18, 2) 
                if row["IGV"] == "SI" else 0.00, axis=1
            )
            df_ocr["Base Imponible"] = df_ocr.apply(
                lambda row: round(float(row["TOTAL PAGADO"]) / 1.18, 2) 
                if row["IGV"] == "SI" else float(row["TOTAL PAGADO"]), axis=1
            )
            
            # Normalizar columnas
            df_ocr['TOTAL PAGADO'] = df_ocr['TOTAL PAGADO'].astype(float)
            df_ocr['FECHA EMISION'] = pd.to_datetime(df_ocr['FECHA EMISION'], errors='coerce')
            df_ocr['Tipo Documento'] = 'Factura'
            df_ocr['Fuente'] = 'OCR'
            
            return df_ocr
        else:
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error en OCR: {str(e)}")
        return pd.DataFrame()

def extract_image_ocr_compras(image_path):
    """
    Extrae facturas de una imagen usando OCR con IA
    """
    prompt = '''
    Extrae los siguientes datos de una factura a partir de esta imagen:

    - FECHA EMISION
    - MONEDA
    - TOTAL PAGADO (puede figurar como: total a pagar, importe total, total)
    - IGV: si el valor es 0 o no aparece, colocar "NO", si es mayor a 0 colocar "SI"
    - RUC (debe ser distinto de 20610930213)
    - Empresa (debe ser distinto a INKAHARVEST S.A.C.)

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
        "TOTAL PAGADO": "350.00"
        }
    ]
    }

    No expliques nada. Solo responde con ese bloque JSON.
    '''
    
    try:
        # Cargar imagen
        img = Image.open(image_path)
        
        # Procesar con IA
        texto = extract_table_from_image(img, prompt)
        json_result = response_json_to_dict(texto)

        if json_result and "detalle" in json_result:
            try:
                df = pd.DataFrame(json_result["detalle"])
                columnas_deseadas = [
                    "FECHA EMISION", "MONEDA", "RUC", "EMPRESA", "IGV", "TOTAL PAGADO"
                ]
                df = df[[col for col in columnas_deseadas if col in df.columns]]
                numero_doc = json_result.get("numero_documento", "")
                df["NroDocumento"] = numero_doc
                
                # Calcular IGV y normalizar columnas
                df["IGV 18%"] = df.apply(
                    lambda row: round((float(row["TOTAL PAGADO"]) / 1.18) * 0.18, 2) 
                    if row["IGV"] == "SI" else 0.00, axis=1
                )
                df["Base Imponible"] = df.apply(
                    lambda row: round(float(row["TOTAL PAGADO"]) / 1.18, 2) 
                    if row["IGV"] == "SI" else float(row["TOTAL PAGADO"]), axis=1
                )
                
                # Normalizar columnas
                df['TOTAL PAGADO'] = df['TOTAL PAGADO'].astype(float)
                df['FECHA EMISION'] = pd.to_datetime(df['FECHA EMISION'], errors='coerce')
                df['Tipo Documento'] = 'Factura'
                df['Fuente'] = 'OCR'
                
                return df
                
            except Exception as e:
                print(f"Error procesando imagen: {e}")
                return pd.DataFrame()
        else:
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error en OCR de imagen: {str(e)}")
        return pd.DataFrame()

def guardar_en_excel_por_mes(df):
    """
    Guarda las facturas en Excel agrupadas por mes de emisión
    """
    try:
        # Crear directorio si no existe
        carpeta_base = r"C:\Users\Dussand\Desktop\BPA\Impuestos\inkaharavest\2025\excel_compras"
        os.makedirs(carpeta_base, exist_ok=True)
        
        facturas_guardadas = []
        
        for index, row in df.iterrows():
            # Obtener mes de la fecha de emisión
            fecha_emision = row['FECHA EMISION']
            if pd.isna(fecha_emision):
                continue
                
            mes_año = fecha_emision.strftime('%Y%m')  # Formato: 202509
            nombre_archivo = f"compras_{mes_año}.xlsx"
            ruta_archivo = os.path.join(carpeta_base, nombre_archivo)
            
            # Crear DataFrame con la fila actual
            df_nueva_fila = pd.DataFrame([row])
            
            # Verificar si el archivo existe
            if os.path.exists(ruta_archivo):
                # Leer archivo existente
                df_existente = pd.read_excel(ruta_archivo)
                
                # Verificar si la factura ya existe (evitar duplicados)
                duplicado = df_existente[
                    (df_existente['RUC'] == row['RUC']) & 
                    (df_existente['NroDocumento'] == row['NroDocumento'])
                ].any().any()
                
                if not duplicado:
                    # Agregar nueva fila
                    df_consolidado = pd.concat([df_existente, df_nueva_fila], ignore_index=True)
                    df_consolidado.to_excel(ruta_archivo, index=False)
                    facturas_guardadas.append({
                        'archivo': nombre_archivo,
                        'accion': 'agregada',
                        'factura': row['NroDocumento'],
                        'empresa': row['EMPRESA']
                    })
                else:
                    facturas_guardadas.append({
                        'archivo': nombre_archivo,
                        'accion': 'duplicada',
                        'factura': row['NroDocumento'],
                        'empresa': row['EMPRESA']
                    })
            else:
                # Crear nuevo archivo
                df_nueva_fila.to_excel(ruta_archivo, index=False)
                facturas_guardadas.append({
                    'archivo': nombre_archivo,
                    'accion': 'creada',
                    'factura': row['NroDocumento'],
                    'empresa': row['EMPRESA']
                })
        
        return facturas_guardadas
        
    except Exception as e:
        print(f"Error guardando Excel: {e}")
        return []

def crear_mensaje_detallado(df, excel_info):
    """
    Crea mensaje detallado con información de cada factura
    """
    mensaje = "✅ PDF procesado exitosamente\n\n"
    
    # Información de cada factura
    for index, row in df.iterrows():
        fecha_str = row['FECHA EMISION'].strftime('%d/%m/%Y') if not pd.isna(row['FECHA EMISION']) else 'Sin fecha'
        igv_texto = "Con IGV" if row['IGV'] == 'SI' else "Sin IGV"
        
        mensaje += f"📄 Factura {index + 1}:\n"
        mensaje += f"• Empresa: {row['EMPRESA']}\n"
        mensaje += f"• RUC: {row['RUC']}\n"
        mensaje += f"• Documento: {row['NroDocumento']}\n"
        mensaje += f"• Fecha: {fecha_str}\n"
        mensaje += f"• Total: S/ {row['TOTAL PAGADO']:,.2f}\n"
        mensaje += f"• IGV: {igv_texto} (S/ {row['IGV 18%']:,.2f})\n"
        mensaje += f"• Base Imponible: S/ {row['Base Imponible']:,.2f}\n\n"
    
    # Información del Excel
    mensaje += "💾 Estado de guardado:\n"
    
    for info in excel_info:
        if info['accion'] == 'creada':
            mensaje += f"🆕 Nuevo archivo: {info['archivo']}\n"
        elif info['accion'] == 'agregada':
            mensaje += f"➕ Agregada a: {info['archivo']}\n"
        elif info['accion'] == 'duplicada':
            mensaje += f"⚠️ Duplicada en: {info['archivo']}\n"
    
    # Totales
    total_importe = df['TOTAL PAGADO'].sum()
    total_igv = df['IGV 18%'].sum()
    
    mensaje += f"\n📊 Totales:\n"
    mensaje += f"• Total comprado: S/ {total_importe:,.2f}\n"
    mensaje += f"• Total IGV: S/ {total_igv:,.2f}\n"
    mensaje += f"• Facturas procesadas: {len(df)}\n"
    
    return mensaje

# Manejo de documentos PDF e imágenes
@bot.message_handler(content_types=['document', 'photo'])
def handle_file(message):
    try:
        if message.content_type == 'photo':
            # Manejar imágenes enviadas como foto
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            temp_file_path = f"temp_image.jpg"
            
            with open(temp_file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            
            bot.reply_to(message, "📷 Imagen recibida, procesando con IA...")
            df_resultado = extract_image_ocr_compras(temp_file_path)
            
        elif message.content_type == 'document':
            file_name = message.document.file_name
            
            # Verificar extensiones válidas
            valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            if not any(file_name.lower().endswith(ext) for ext in valid_extensions):
                bot.reply_to(message, "❌ Por favor envía archivos PDF, JPG o PNG")
                return
            
            # Descargar el archivo
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            temp_file_path = f"temp_{file_name}"
            
            with open(temp_file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            
            if file_name.lower().endswith('.pdf'):
                bot.reply_to(message, "📄 PDF recibido, procesando con IA...")
                df_resultado = extract_pdf_ocr_compras(temp_file_path)
            else:
                bot.reply_to(message, "📷 Imagen recibida, procesando con IA...")
                df_resultado = extract_image_ocr_compras(temp_file_path)
        
        # Limpiar archivo temporal
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        
        if df_resultado.empty:
            bot.reply_to(message, "❌ No se encontraron facturas válidas en el archivo")
        else:
            # Guardar en Excel por mes
            excel_guardado = guardar_en_excel_por_mes(df_resultado)
            
            # Crear mensaje detallado con datos de la factura
            mensaje_detallado = crear_mensaje_detallado(df_resultado, excel_guardado)
            
            bot.reply_to(message, mensaje_detallado)
            
    except Exception as e:
        # Limpiar archivo temporal en caso de error
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        bot.reply_to(message, f"❌ Error procesando archivo: {str(e)}")

# Comando de inicio
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """🤖 Bot Extractor de Facturas con IA

📄 Envía archivos PDF, JPG o PNG de facturas y los procesaré con inteligencia artificial.

Cómo usar:
1. Adjunta tu archivo (PDF, JPG, PNG)
2. La IA extrae automáticamente los datos
3. Recibe resumen con estadísticas
4. Se guarda automáticamente en Excel por mes

Datos que extrae:
• RUC y empresa emisora
• Fecha de emisión
• Total pagado
• IGV calculado automáticamente

¡Envía tu primera factura! 🚀"""
    
    bot.reply_to(message, welcome_text)

# Manejo de otros mensajes
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, "📄 Envía un archivo PDF para procesarlo, o usa /start para instrucciones")

if __name__ == '__main__':
    print("🤖 Bot Extractor PDF con IA iniciado...")
    print("📄 Listo para procesar facturas con inteligencia artificial")
    
    try:
        bot.polling(none_stop=True)
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido")
    except Exception as e:
        print(f"Error: {e}")