import streamlit as st
import urllib.parse
import pandas as pd
import os
from io import BytesIO
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import gspread
from google.oauth2.service_account import Credentials
import unicodedata
import requests
import re

# --- CONFIGURACIÓN DE PÁGINA Y ESTILOS ---
st.set_page_config(page_title="Cotizador YQ Seguros", page_icon="🛡️", layout="centered")

st.markdown("""
    <style>
    /* 1. Botón Principal: Cotizar */
    div.stButton > button {
        background-color: #2456A6 !important;
        color: white !important;
        border: 2px solid #2456A6 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 16px !important;
    }
    div.stButton > button:hover, div.stButton > button:active, div.stButton > button:focus {
        background-color: #1a428a !important;
        border-color: #1a428a !important;
        color: white !important;
        box-shadow: none !important;
    }

    /* 2. Botón Salvavidas HTML: WhatsApp */
    a[data-testid="stLinkButton"] {
        background-color: #25D366 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        text-decoration: none !important;
        box-shadow: 0 4px 12px rgba(37, 211, 102, 0.2) !important;
        display: flex !important;
        justify-content: center !important;
    }
    a[data-testid="stLinkButton"]:hover {
        background-color: #1ebc59 !important;
        color: white !important;
    }
    
    /* 3. Botón de Descarga PDF */
    button[kind="secondary"] {
        background-color: #2456A6 !important;
        color: white !important;
        border: 2px solid #2456A6 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        width: 100% !important;
        height: 42px !important;
    }
    button[kind="secondary"]:hover {
        background-color: #1a428a !important;
        border-color: #1a428a !important;
        color: white !important;
    }

    /* Limpieza visual extra */
    div[data-testid="stSidebarHeader"] {
        padding-bottom: 0px;
    }
    </style>
""", unsafe_allow_html=True)

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ImageRL
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
except ImportError:
    st.error("❌ Falta la librería 'reportlab'. Ejecuta REPARAR.bat")
    st.stop()

# --- DATOS DE ACCESO (ROLES) ---
CODIGO_ADMIN = "ADMIN2026"
CODIGOS_ASESORES = ["ASE01", "ASE02", "ASE03", "VENTAS2026"] 

# --- FUNCIONES DE SOPORTE Y LIMPIEZA ---
def obtener_hora_peru():
    return datetime.utcnow() - timedelta(hours=5)

def get_mes_actual():
    mes_num = obtener_hora_peru().month
    meses = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
             7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
    return meses[mes_num]

def quitar_tildes(texto):
    if pd.isna(texto): return ""
    texto = str(texto).strip()
    return "".join(c for c in unicodedata.normalize('NFKD', texto) if not unicodedata.combining(c)).upper()

# --- FUNCIONES GOOGLE SHEETS ---
def get_gspread_client():
    try:
        if "gcp_service_account" not in st.secrets:
            st.warning("⚠️ Falta configuración de Google en Secrets.")
            return None
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"❌ Error de conexión Google: {e}")
        return None

def guardar_en_sheets(datos_fila):
    try:
        client = get_gspread_client()
        if not client: return
        sheet = client.open("historial_cotizador_salud").sheet1 
        sheet.append_row(datos_fila)
    except Exception as e:
        st.error(f"❌ Error al guardar en Sheets: {e}")

def descargar_historial_sheets():
    try:
        client = get_gspread_client()
        if not client: return None
        sheet = client.open("historial_cotizador_salud").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error descargando historial: {e}")
        return None

# --- FUNCIONES DE CORREO ---
def enviar_notificacion(cliente, correo, celular, plan_interes_list, n_familia, edad, clinicas, continuidad, score_rimac, cliente_rimac):
    clinicas_txt = ", ".join(clinicas) if clinicas else "Sin preferencia específica"
    cobertura_txt = ", ".join(plan_interes_list) if isinstance(plan_interes_list, list) else str(plan_interes_list)
    
    try:
        fecha_hora_peru = obtener_hora_peru().strftime('%d/%m/%Y %H:%M')
    except:
        fecha_hora_peru = "Fecha no disponible"
        
    descripcion_crm = f"Edad Titular: {edad} | Interés: {cobertura_txt} | Condición: {continuidad} | Scoring Rímac: {score_rimac} | Cliente Rímac: {cliente_rimac} | Clínicas: {clinicas_txt} | Total Asegurados: {n_familia + 1} | Fecha: {fecha_hora_peru}"

    try:
        url_auth = "https://accounts.zoho.com/oauth/v2/token"
        datos_auth = {
            "refresh_token": st.secrets["ZOHO_REFRESH_TOKEN"],
            "client_id": st.secrets["ZOHO_CLIENT_ID"],
            "client_secret": st.secrets["ZOHO_CLIENT_SECRET"],
            "grant_type": "refresh_token"
        }
        res_auth = requests.post(url_auth, data=datos_auth)
        access_token = res_auth.json().get("access_token")
        
        if not access_token:
            raise Exception("No se pudo obtener el Access Token de Zoho")

        url_crm = "https://www.zohoapis.com/crm/v2/Leads"
        headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
        
        payload = {
            "data": [
                {
                    "Last_Name": cliente,
                    "Email": correo,
                    "Mobile": str(celular),
                    "Lead_Source": "Cotizador Salud Web",
                    "Description": descripcion_crm
                }
            ]
        }
        
        res_crm = requests.post(url_crm, headers=headers, json=payload)
        
        if res_crm.status_code in [200, 201]:
            return True, "¡Cotización generada y enviada a un asesor exitosamente!"
        else:
            raise Exception(f"Fallo en API Zoho CRM: {res_crm.text}")

    except Exception as e:
        print(f"⚠️ Error CRM (Salud): {e}. Activando envío de correo de respaldo...")
        try:
            if "EMAIL_PASSWORD" in st.secrets:
                SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
            else:
                return False, "Hubo un problema temporal en el servidor. Por favor, contáctanos por WhatsApp."
                
            SMTP_SERVER = "smtppro.zoho.com"
            SMTP_PORT = 587
            SENDER_EMAIL = "administracion@yqcorredores.com"
            RECEIVER_EMAIL = "administracion@yqcorredores.com"
            
            asunto = f"NUEVO LEAD DE COTIZADOR SALUD: {cliente} [RESPALDO]"
            cuerpo = f"Hola Chicos,\n\nUn cliente ha generado una cotización de salud:\n\nDATOS DEL CLIENTE:\nNombre: {cliente}\nCorreo: {correo}\nWhatsApp: {celular}\n\nDATOS DE LA COTIZACIÓN:\nEdad Titular: {edad} años\nInterés: {cobertura_txt}\nCondición: {continuidad}\nScoring Rímac: {score_rimac}\nCliente Rímac: {cliente_rimac}\nClínicas Preferidas: {clinicas_txt}\nTotal Asegurados: {n_familia + 1}\n\nFecha: {fecha_hora_peru}"

            msg = MIMEMultipart()
            msg['From'], msg['To'], msg['Subject'] = SENDER_EMAIL, RECEIVER_EMAIL, asunto
            msg.attach(MIMEText(cuerpo, 'plain'))
            
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
            server.quit()
            
            return True, "Hemos procesado tu cotización, un asesor te contactará en breve."
            
        except Exception as email_error:
            print(f"❌ Fallo crítico en CRM y Correo (Salud): {email_error}")
            return False, "Experimentamos intermitencias. Por favor, intenta de nuevo en unos minutos."

# --- SOPORTE ---
def obtener_nuevo_folio():
    try:
        with open('folio.txt', 'r') as f: return int(f.read().strip()) + 1
    except: return 1000

def incrementar_folio():
    fol = obtener_nuevo_folio()
    try:
        with open('folio.txt', 'w') as f: f.write(str(fol))
    except: pass
    return fol

# --- CARGA DE DATOS ---
@st.cache_data
def cargar_datos_base():
    if not os.path.exists('precios_2026.csv') or not os.path.exists('base_clinicas.xlsx'):
        return None
    try:
        try: df_precios = pd.read_csv('precios_2026.csv', sep=',')
        except: df_precios = pd.read_csv('precios_2026.csv', sep=';')

        df_precios = df_precios.loc[:, ~df_precios.columns.str.contains('^Unnamed')]
        df_precios['Aseguradora'] = df_precios['Aseguradora'].astype(str).str.strip()
        df_precios['Plan'] = df_precios['Plan'].astype(str).str.strip()

        if os.path.exists('info_adicional.csv'):
            try: df_int = pd.read_csv('info_adicional.csv')
            except: df_int = pd.read_csv('info_adicional.csv', sep=';')
            df_int['Aseguradora'] = df_int['Aseguradora'].astype(str).str.strip()
            df_int['Plan'] = df_int['Plan'].astype(str).str.strip()
            cols_drop = [c for c in df_int.columns if c in df_precios.columns and c not in ['Aseguradora','Plan']]
            df_precios = df_precios.drop(columns=cols_drop, errors='ignore')
            df_precios = pd.merge(df_precios, df_int, on=['Aseguradora','Plan'], how='left')

        xls = pd.ExcelFile('base_clinicas.xlsx', engine='openpyxl')
        df_redes = pd.read_excel(xls, sheet_name='REDES')
        df_redes['Clinicas_Busqueda'] = df_redes['Clinicas_Incluidas'].fillna('').astype(str)
        df_redes['Aseguradora'] = df_redes['Aseguradora'].astype(str).str.strip()
        df_redes['Plan'] = df_redes['Plan'].astype(str).str.strip()
        
        todas = []
        for l in df_redes['Clinicas_Incluidas'].dropna():
            todas.extend([c.strip() for c in l.split(',')])
        clinicas_unicas = sorted(list(set(todas)))

        return df_precios, df_redes, clinicas_unicas, df_precios
    except Exception as e:
        st.error(f"Error cargando datos base: {e}")
        return None

def cargar_campanas():
    lista_campanas = [] 
    if os.path.exists('campana_descuentos.csv'):
        try:
            try: df_camp = pd.read_csv('campana_descuentos.csv', sep=',')
            except: df_camp = pd.read_csv('campana_descuentos.csv', sep=';')
            
            if len(df_camp.columns) <= 1:
                df_camp = pd.read_csv('campana_descuentos.csv', sep=';')

            df_camp.columns = df_camp.columns.str.strip()

            def safe_int(val, default):
                try: return int(float(val))
                except: return default

            for _, row in df_camp.iterrows():
                lista_campanas.append({
                    'Aseguradora': quitar_tildes(row.get('Aseguradora', '')),
                    'Plan': quitar_tildes(row.get('Plan', '')),
                    'Continuidad': quitar_tildes(row.get('Continuidad', '')),
                    'Edad_Min': safe_int(row.get('Edad_Min', 0), 0),
                    'Edad_Max': safe_int(row.get('Edad_Max', 999), 999),
                    'Asegurados_Min': safe_int(row.get('Asegurados_Min', 1), 1),
                    'Forma_Pago': quitar_tildes(row.get('Forma_Pago', '')),
                    'Score_Rimac': quitar_tildes(row.get('Score_Rimac', '')),
                    'Cliente_Rimac': quitar_tildes(row.get('Cliente_Rimac', '')),
                    'Salud': quitar_tildes(row.get('Salud', '')),
                    'Mes': quitar_tildes(row.get('Mes', '')),
                    'Porcentaje_Descuento': safe_int(row.get('Porcentaje_Descuento', 0), 0)
                })
        except Exception as e: 
            st.error(f"Error procesando campañas: {e}")
    return lista_campanas

# --- MOTOR DE REGLAS DINÁMICO ---
def obtener_descuento_matriz(campanas, cia, plan, continuidad, edad, n_asegurados, forma_pago, score_rimac, cliente_rimac, salud, mes):
    cia_norm = quitar_tildes(cia)
    plan_norm = quitar_tildes(plan)
    mes_norm = quitar_tildes(mes)
    cont_norm = "CONTINUIDAD" if "continuidad" in continuidad.lower() else "NUEVO"
    pago_norm = quitar_tildes(forma_pago)
    score_norm = quitar_tildes(score_rimac)
    cliente_norm = "SI" if quitar_tildes(cliente_rimac) in ["SI", "S", "YES"] else "NO"
    salud_norm = quitar_tildes(salud)
    
    for c in campanas:
        if not (cia_norm in c['Aseguradora'] or c['Aseguradora'] in cia_norm): continue
        if c['Plan'] != plan_norm: continue
        if c['Mes'] != 'TODOS' and c['Mes'] != mes_norm: continue
        if c['Continuidad'] != 'TODOS' and c['Continuidad'] != cont_norm: continue
        if not (c['Edad_Min'] <= edad <= c['Edad_Max']): continue
        if n_asegurados < c['Asegurados_Min']: continue
        if c['Forma_Pago'] != 'TODOS' and c['Forma_Pago'] != pago_norm: continue
        if c['Score_Rimac'] != 'TODOS' and c['Score_Rimac'] != score_norm: continue
        if c['Cliente_Rimac'] != 'TODOS' and c['Cliente_Rimac'] != cliente_norm: continue
        if c['Salud'] != 'TODOS' and c['Salud'] != salud_norm: continue
        
        return c['Porcentaje_Descuento']
    return 0

# --- BÚSQUEDA ---
def calcular_precio(df, cia, plan, familia):
    total = 0
    for p in familia:
        edad = min(p['edad'], 81)
        row = df[(df['Aseguradora']==cia) & (df['Plan']==plan) & (df['Edad']==edad)]
        if row.empty: return None
        col_p = 'Precio_Sano' if p['salud']=='Sano' else 'Precio_Cronico'
        try: precio = float(row.iloc[0][col_p])
        except: precio = 0.0
        if precio <= 0: return None
        total += precio
    return total

def buscar(df_precios, df_redes, familia, clinicas_user, continuidad, coberturas_list, desc_men_dict, desc_anu_dict):
    candidatos = []
    set_user = set(quitar_tildes(c) for c in clinicas_user)
    
    PLANES_BASICA = ['Esencial', 'Esencial Plus', 'Multisalud Base', 'Medisalud Lite', 'Medisalud Base','Plan Vital','Salud Total']
    PLANES_INTEGRAL = ['Red Preferente', 'Red Médica', 'Multisalud', 'Medisalud', 'Medisalud Plus', 'Viva Salud', 'Trébol Salud', 'Medisalud Senior +', 'Oro - Plan preferente', 'Oro - Plan Red', 'Oro - Plan Completo']
    PLANES_REEMBOLSO = ['Full Salud', 'Medicvida Nacional', 'Medisalud Premium']
    PLANES_INTERNACIONAL = ['Salud Preferencial', 'Medicvida Internacional']

    planes_permitidos = set()
    if "Básica" in coberturas_list: planes_permitidos.update(PLANES_BASICA)
    if "Integral" in coberturas_list: planes_permitidos.update(PLANES_INTEGRAL)
    if "Integral + Reembolso" in coberturas_list: planes_permitidos.update(PLANES_REEMBOLSO)
    if "Integral + Cobertura Internacional" in coberturas_list: planes_permitidos.update(PLANES_INTERNACIONAL)

    for (cia, plan), grupo in df_redes.groupby(['Aseguradora', 'Plan']):
        cia_clean = quitar_tildes(cia)
        plan_clean = quitar_tildes(plan)
        
        if continuidad == "Vengo con continuidad" and "RIMAC" in cia_clean and plan_clean == "PLAN VITAL": 
            continue
        if "Vengo con continuidad" == continuidad and "MAPFRE" in cia_clean: continue
        if continuidad == "Sí (Continuidad)" and "mapfre" in str(cia).lower(): continue
        if plan_clean not in [quitar_tildes(p) for p in planes_permitidos]: continue

        clinicas_plan = set()
        for _, row in grupo.iterrows():
            clinicas_plan.update([quitar_tildes(c) for c in str(row['Clinicas_Busqueda']).split(',')])
        if clinicas_user and not set_user.issubset(clinicas_plan): continue
        
        list_clin_red, list_cob_amb, list_cob_hosp = [], [], []
        
        if not clinicas_user:
            row = grupo.iloc[0]
            list_clin_red.append(f"• <b>Red:</b> {row['Nombre_Red']}")
            list_cob_amb.append(f"• <b>Amb:</b> {row['Cobertura_Amb']}")
            list_cob_hosp.append(f"• <b>Hosp:</b> {row['Cobertura_Hosp']}")
        else:
            for cli in clinicas_user:
                for _, row in grupo.iterrows():
                    if quitar_tildes(cli) in [quitar_tildes(c.strip()) for c in str(row['Clinicas_Busqueda']).split(',')]:
                        list_clin_red.append(f"• <b>{cli}</b>: {row['Nombre_Red']}")
                        list_cob_amb.append(f"• <b>{cli}</b>: {row['Cobertura_Amb']}")
                        list_cob_hosp.append(f"• <b>{cli}</b>: {row['Cobertura_Hosp']}")
                        break

        base = calcular_precio(df_precios, cia, plan, familia)
        if base is None: continue
        
        dsc_men = 0
        dsc_anu = 0
        for (d_cia, d_plan), v in desc_men_dict.items():
            if quitar_tildes(d_cia) == cia_clean and quitar_tildes(d_plan) == plan_clean:
                dsc_men = v
                break
        for (d_cia, d_plan), v in desc_anu_dict.items():
            if quitar_tildes(d_cia) == cia_clean and quitar_tildes(d_plan) == plan_clean:
                dsc_anu = v
                break
        
        precio_anual_final = base * (1 - dsc_anu/100)
        precio_mensual_final = (base / 12) * (1 - dsc_men/100)

        match = df_precios[(df_precios['Aseguradora']==cia) & (df_precios['Plan']==plan)]
        data = match.iloc[0] if not match.empty else {}

        candidatos.append({
            'Aseguradora': cia, 'Plan': plan, 'Txt_Clin_Red': "<br/>".join(list_clin_red),
            'Txt_Cob_Amb': "<br/>".join(list_cob_amb), 'Txt_Cob_Hosp': "<br/>".join(list_cob_hosp),
            'Int_Amb_Full': f"<b>Ded:</b> {data.get('Int_Ded_Amb_Pre','-')}<br/><b>Reemb:</b> {data.get('Int_Reem_Amb_Sin','-')}",
            'Int_Hosp_Full': f"<b>Ded:</b> {data.get('Int_Ded_Hosp_Pre','-')}<br/><b>Reemb:</b> {data.get('Int_Reem_Hosp_Sin','-')}",
            'Precio_Mensual_Base': base/12, 'Pct_Dscto_Mensual': f"{dsc_men}%", 'Precio_Mensual_Final': precio_mensual_final,
            'Precio_Anual_Base': base, 'Pct_Dscto_Anual': f"{dsc_anu}%", 'Precio_Anual_Final': precio_anual_final,
            'Dsc_Num_Mensual': dsc_men, 'Dsc_Num_Anual': dsc_anu,
            'Precio_Final': precio_anual_final,
            'Link_Cartilla': data.get('Link_Cartilla', ''), 'Link_Carencia': data.get('Link_Carencia', ''), 'ID': f"{cia}-{plan}"
        })

    return pd.DataFrame(candidatos).sort_values('Precio_Final') if candidatos else pd.DataFrame()
    
# --- PDF ---
def generar_pdf(perfil, df, id_sel, razon, folio, es_vista_cliente=False):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
        estilos = getSampleStyleSheet()
        
        # 1. PALETA MINIMALISTA Y CORPORATIVA (CRO)
        AZUL_CORP = colors.HexColor("#2456A6")
        AZUL_CLARO = colors.HexColor("#F0F6FF")  # Fondo suave para el recomendado
        VERDE_EXITO = colors.HexColor("#28A745") # Exclusivo para ahorros y botones
        GRIS_TEXTO = colors.HexColor("#444444")  # Gris oscuro elegante para lectura
        GRIS_FONDO = colors.HexColor("#F8F9FA")  # Fondo limpio para cajas de info
        BORDE_SUAVE = colors.HexColor("#DEE2E6") # Líneas divisorias minimalistas
        
        st_tit = ParagraphStyle('T', parent=estilos['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=AZUL_CORP, leading=16)
        st_sub = ParagraphStyle('S', parent=estilos['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=AZUL_CORP)
        st_norm = ParagraphStyle('N', parent=estilos['Normal'], fontSize=8.5, textColor=GRIS_TEXTO, leading=11)
        st_bold = ParagraphStyle('B', parent=st_norm, fontName='Helvetica-Bold', textColor=AZUL_CORP)
        st_th = ParagraphStyle('TH', parent=estilos['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
        # Ajustamos el interlineado de la tabla para que respire mejor
        st_td = ParagraphStyle('TD', parent=estilos['Normal'], fontSize=7.5, textColor=GRIS_TEXTO, leading=9.5)
        st_td_b = ParagraphStyle('TDB', parent=st_td, fontName='Helvetica-Bold', textColor=AZUL_CORP)

        elements = []
        # Cabecera
        img = ImageRL("logo.png", width=4.0*cm, height=2.2*cm, kind='proportional') if os.path.exists("logo.png") else Paragraph("", st_norm)
        p_header = Paragraph("<b>YQ CORREDORES DE SEGUROS</b><br/>Propuesta de Seguro de Salud", st_tit)
        fecha_peru = obtener_hora_peru().strftime('%d/%m/%Y')
        p_folio = Paragraph(f"<font color='#666666'><b>Folio:</b> {folio}<br/><b>Fecha:</b> {fecha_peru}</font>", ParagraphStyle('F', parent=st_norm, alignment=2))
        
        t_head = Table([[img, p_header, p_folio]], colWidths=[4.0*cm, 8.5*cm, 3.5*cm])
        t_head.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        elements.append(t_head)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("En YQ Corredores de Seguros, entendemos la importancia de proteger tu salud. Te presentamos esta cotización personalizada con precios exclusivos.", st_norm))
        elements.append(Spacer(1, 10))

        # Perfil del Cliente
        elements.append(Paragraph("TU PERFIL", st_sub))
        elements.append(Spacer(1, 5))
        data_perfil = [
            [Paragraph("<b>Titular:</b>", st_bold), Paragraph(perfil['Titular'], st_norm),
             Paragraph("<b>Cobertura:</b>", st_bold), Paragraph(perfil['Cobertura'], st_norm)],
            [Paragraph("<b>Dependientes:</b>", st_bold), Paragraph(perfil['Dependientes'], st_norm),
             Paragraph("<b>Condición:</b>", st_bold), Paragraph(perfil['Continuidad'], st_norm)]
        ]
        t_perf = Table(data_perfil, colWidths=[2.5*cm, 8.0*cm, 2.5*cm, 5.0*cm])
        t_perf.setStyle(TableStyle([('LINEBELOW', (0,0), (-1,-1), 0.5, BORDE_SUAVE), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('PADDING', (0,0), (-1,-1), 5)]))
        elements.append(t_perf)
        elements.append(Spacer(1, 15))

        # Tabla Principal
       # AJUSTE UX 1: Redistribución de columnas (Le damos más espacio a los precios)
        es_int = "Internacional" in perfil['Cobertura']
        if es_int:
            headers = ['Plan', 'Clínicas: Redes', 'Atención Amb', 'Atención Hosp', 'Pago Mensual', 'Pago Anual']
            anchos = [3.0*cm, 3.3*cm, 3.4*cm, 3.5*cm, 2.3*cm, 2.5*cm] # Total 18cm
        else:
            headers = ['Plan', 'Clínicas: Redes', 'Atención Amb', 'Atención Hosp', 'Pago Mensual', 'Pago Anual']
            anchos = [3.0*cm, 3.3*cm, 3.4*cm, 3.5*cm, 2.3*cm, 2.5*cm] # Total 18cm

        texto_guia_pdf = """<b>¿CÓMO LEER ESTE DOCUMENTO?</b><br/>
        • <b>Coberturas (Atención Amb/Hosp):</b> Muestra tu deducible o copago al atenderte por consulta (Amb) o por hospitalización (Hosp).<br/>
        • <b>Precios y Ahorro:</b> El precio <strike color='#999999'>Antes</strike> es la tarifa pública regular. Tu costo exclusivo es el <b>Final</b>, y en <font color='#28A745'><b>verde</b></font> verás el dinero que ahorras.<br/>
        • <b>Enlaces Activos:</b> Haz clic en <font color='#2456A6'><u>Cartilla</u></font> o <font color='#2456A6'><u>Carencia</u></font> para ver los detalles del plan, y en <font color='#28A745'><b>► CONTRATAR</b></font> para iniciar tu solicitud por WhatsApp."""
        
        t_guia = Table([[Paragraph(texto_guia_pdf, st_norm)]], colWidths=[18*cm])
        t_guia.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F0F4F8")), 
            ('BOX', (0,0), (-1,-1), 0.5, AZUL_CORP), 
            ('PADDING', (0,0), (-1,-1), 8)
        ]))
        elements.append(t_guia)
        elements.append(Spacer(1, 10))

        data = [[Paragraph(h, st_th) for h in headers]]
        
        for _, row in df.iterrows():
            rec = (row['ID'] == id_sel)
            # 1. Nombre del plan y etiqueta
            txt_p = f"<b>{row['Aseguradora']}</b><br/>{row['Plan']}"
            if rec: txt_p = "<font color='#2456A6'><b>► RECOMENDADO</b></font><br/>" + txt_p
            
            # 2. Enlaces de Cartilla y Carencia
            links = []
            cartilla = str(row.get('Link_Cartilla', '')).strip()
            if cartilla and cartilla != '-' and cartilla.lower() != 'nan':
                href = cartilla if cartilla.startswith('http') else 'https://' + cartilla
                links.append(f"<a href='{href}' color='#2456A6'><u>Cartilla</u></a>")
                
            carencia = str(row.get('Link_Carencia', '')).strip()
            if carencia and carencia != '-' and carencia.lower() != 'nan':
                href_c = carencia if carencia.startswith('http') else 'https://' + carencia
                links.append(f"<a href='{href_c}' color='#2456A6'><u>Carencia</u></a>")
            
            if links: txt_p += "<br/>" + " | ".join(links)

            # 3. Botón directo de WhatsApp por plan
            nombre_titular = perfil['Titular'].split('(')[0].strip()
            msg_plan = f"Hola, soy {nombre_titular}. Revisé mi cotización (Folio {folio}) y deseo contratar el plan {row['Aseguradora']} {row['Plan']}."
            enlace_plan_wa = f"https://wa.me/51906462225?text={urllib.parse.quote(msg_plan)}"
            txt_p += f"<br/><br/><a href='{enlace_plan_wa}' color='#28A745'><font size='7.5'><b>► CONTRATAR</b></font></a>"

            # 4. Formateo de Precios Simétricos
            dsc_men = row['Dsc_Num_Mensual']
            dsc_anu = row['Dsc_Num_Anual']
            
            if dsc_anu > 0:
                ahorro_anual = row['Precio_Anual_Base'] - row['Precio_Anual_Final']
                precio_anual_str = (
                    f"<font color='#666666' size='7.5'>Antes: S/ <strike>{row['Precio_Anual_Base']:,.0f}</strike></font><br/>"
                    f"<font color='#28A745' size='7.5'><b>Ahorro: S/ {ahorro_anual:,.0f}</b></font><br/>"
                    f"<font color='#2456A6' size='8.5'><b>Final: S/ {row['Precio_Anual_Final']:,.0f}</b></font>"
                )
            else:
                precio_anual_str = f"<font color='#2456A6' size='8.5'><b>Final: S/ {row['Precio_Anual_Final']:,.0f}</b></font>"
            
            if dsc_men > 0:
                ahorro_mensual = row['Precio_Mensual_Base'] - row['Precio_Mensual_Final']
                precio_mensual_str = (
                    f"<font color='#666666' size='7.5'>Antes: S/ <strike>{row['Precio_Mensual_Base']:,.0f}</strike></font><br/>"
                    f"<font color='#28A745' size='7.5'><b>Ahorro: S/ {ahorro_mensual:,.0f}</b></font><br/>"
                    f"<font color='#2456A6' size='8.5'><b>Final: S/ {row['Precio_Mensual_Final']:,.0f}</b></font>"
                )
            else:
                precio_mensual_str = f"<font color='#2456A6' size='8.5'><b>Final: S/ {row['Precio_Mensual_Final']:,.0f}</b></font>"
                
            # 5. Cierre de fila
            if es_int:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Int_Amb_Full'], st_td), Paragraph(row['Int_Hosp_Full'], st_td), Paragraph(precio_mensual_str, st_td_b), Paragraph(precio_anual_str, st_td_b)]
            else:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Txt_Cob_Amb'], st_td), Paragraph(row['Txt_Cob_Hosp'], st_td), Paragraph(precio_mensual_str, st_td_b), Paragraph(precio_anual_str, st_td_b)]
            data.append(fila)
            # 👇 ESTA ES LA LÍNEA QUE DEBES AGREGAR 👇
        t = Table(data, colWidths=anchos, repeatRows=1)
        estilos_t = [('BACKGROUND', (0,0), (-1,0), AZUL_CORP), ('GRID', (0,0), (-1,-1), 0.5, BORDE_SUAVE), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 4)]
        
        for i, row in enumerate(df.iterrows()):
            if row[1]['ID'] == id_sel:
                # Estilo premium para el recomendado: Fondo celeste suave y bordes azules
                estilos_t.append(('BACKGROUND', (0, i+1), (-1, i+1), AZUL_CLARO))
                estilos_t.append(('BOX', (0, i+1), (-1, i+1), 1.5, AZUL_CORP))
        t.setStyle(TableStyle(estilos_t))
        elements.append(t)
        elements.append(Spacer(1, 10))

        # --- SISTEMA UNIFICADO DE ALERTAS (Diseño Limpio) ---
        def crear_caja_aviso(texto):
            tabla = Table([[Paragraph(texto, st_norm)]], colWidths=[18*cm])
            tabla.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), GRIS_FONDO), ('BOX', (0,0), (-1,-1), 0.5, BORDE_SUAVE), ('PADDING', (0,0), (-1,-1), 8)]))
            return tabla

        if perfil['Continuidad'] == "Nuevo":
            elements.append(crear_caja_aviso("<b>🚨 IMPORTANTE:</b> Al ser un seguro nuevo, aplican periodos de carencia (30 días) y espera. Revisa el enlace de 'Carencia'."))
            elements.append(Spacer(1, 5))
        elif perfil['Continuidad'] == "Vengo con continuidad":
            elements.append(crear_caja_aviso("<b>✅ BENEFICIO DE CONTINUIDAD:</b> Para mantenerlo, debes haber estado asegurado en los últimos 90 días con una póliza EPS o Individual."))
            elements.append(Spacer(1, 5))

        tiene_rimac = any("RIMAC" in str(cia).upper() or "RÍMAC" in str(cia).upper() for cia in df['Aseguradora'].values)
        if es_vista_cliente and tiene_rimac:
            elements.append(crear_caja_aviso("<b>🎁 DESCUENTO EN RÍMAC:</b> Esta aseguradora otorga descuentos exclusivos por perfil crediticio que no podemos mostrar aquí. Escríbenos al WhatsApp para revelar tu tarifa final."))
            elements.append(Spacer(1, 5))
            
        tiene_salud_total = any("SALUD TOTAL" in str(p).upper() for p in df['Plan'].values)
        if tiene_salud_total:
            elements.append(crear_caja_aviso("<b>🏥 PLAN SALUD TOTAL:</b> La atención y hospitalización en la clínica Ricardo Palma está sujeta a previa evaluación de Mapfre."))
            elements.append(Spacer(1, 5))
            
        elements.append(Spacer(1, 15))

        # Análisis del Experto (Estilo "Cita" Minimalista)
        if razon:
            elements.append(Paragraph(f"¿POR QUÉ RECOMENDAMOS EL PLAN {str(df[df['ID']==id_sel]['Plan'].values[0]).upper()}?", st_sub))
            elements.append(Spacer(1, 8)) 
            t_box = Table([[Paragraph(f"<b>ANÁLISIS DEL EXPERTO:</b><br/><br/>{razon}", st_norm)]], colWidths=[18*cm])
            t_box.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), GRIS_FONDO), 
                ('LINELEFT', (0,0), (-1,-1), 2, AZUL_CORP), # Fina línea azul a la izquierda
                ('BOX', (0,0), (-1,-1), 0.5, BORDE_SUAVE), 
                ('PADDING', (0,0), (-1,-1), 12)
            ]))
            elements.append(t_box)
            elements.append(Spacer(1, 25))

        # Footer y Botones
        # --- CIERRE PREMIUM (Manejo de Objeciones y Autoridad) ---
        elements.append(Paragraph("¿Aún tienes dudas sobre cuál elegir?", st_sub))
        elements.append(Spacer(1, 5))
        
        # 1. Obtenemos el nombre del cliente y construimos los mensajes dinámicos
        nombre_titular = perfil['Titular'].split('(')[0].strip()
        
        msg_dudas = f"Hola, soy {nombre_titular}. Estaba revisando mi cotización de salud (Folio {folio}) y tengo algunas consultas rápidas antes de elegir mi plan."
        link_dudas = f"https://wa.me/51906462225?text={urllib.parse.quote(msg_dudas)}"
        
        msg_llamada = f"Hola, soy {nombre_titular}. Me gustaría agendar una breve llamada para que me ayuden a elegir el mejor plan de mi cotización (Folio {folio})."
        link_llamada = f"https://wa.me/51906462225?text={urllib.parse.quote(msg_llamada)}"
        
        # 2. Botones usando caracteres universales ">>" y enlaces dinámicos
        st_btn = ParagraphStyle('Btn', parent=st_norm, textColor=colors.white, alignment=1, fontName='Helvetica-Bold', fontSize=9)
        t_btns = Table([
            [Paragraph(f'<a href="{link_dudas}">>> RESOLVER DUDAS POR WHATSAPP</a>', st_btn), 
             "", 
             Paragraph(f'<a href="{link_llamada}">>> AGENDAR LLAMADA CON UN EXPERTO</a>', st_btn)]
        ], colWidths=[7.5*cm, 0.5*cm, 7.5*cm], rowHeights=[1.1*cm])
        
        t_btns.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,0), AZUL_CORP), 
            ('BACKGROUND', (2,0), (2,0), colors.HexColor("#333333")), 
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), 
            ('ROUNDED', (0,0), (-1,-1), 6)
        ]))
        elements.append(t_btns)
        elements.append(Spacer(1, 20))

        # Textos de autoridad y legales limpios
        legal_text = (
            "<b>Condiciones de la Propuesta:</b> Los precios son referenciales, incluyen IGV y están sujetos a evaluación médica de la aseguradora. "
            "Tarifas válidas por 7 días hábiles desde la fecha de emisión."
        )
        elements.append(Paragraph(legal_text, ParagraphStyle('D', parent=st_norm, fontSize=7.5, textColor=colors.grey)))
        elements.append(Spacer(1, 5))
        
        # Gatillo de Confianza Institucional 
        autoridad_text = "<b>RESPALDO:</b> <i>YQ Corredores de Seguros opera bajo los más altos estándares y regulaciones del mercado asegurador peruano.</i>"
        elements.append(Paragraph(autoridad_text, ParagraphStyle('D2', parent=st_norm, fontSize=7.5, textColor=AZUL_CORP)))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer
    except Exception as e:
        return f"ERROR PDF: {str(e)}"

# --- INTERFAZ ---
base_data = cargar_datos_base()
if base_data is None:
    st.error("Error en base_data. Verifica precios_2026.csv y base_clinicas.xlsx")
else:
    df_precios, df_redes, clinicas_unicas, df_full = base_data
    campanas_maestras = cargar_campanas() 
    mes_actual = get_mes_actual()

    if 'resultados' not in st.session_state: st.session_state['resultados'] = None
    
    # 1. EVALUACIÓN DE SEGURIDAD INVISIBLE
    codigo_actual = st.session_state.get('codigo_secreto', '')
    es_admin = (codigo_actual == CODIGO_ADMIN)
    es_asesor = (codigo_actual in CODIGOS_ASESORES)
    es_cliente = (not es_admin and not es_asesor)

    # LOGO EN PANTALLA PRINCIPAL
    if os.path.exists("logo_web.png"):
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image("logo_web.png", use_container_width=True)

    # --- 2. EL SALUDO Y GUÍA DE CONVERSIÓN ---
    nombre_url = st.query_params.get("nombre", "")

    if nombre_url:
        st.title(f"¡Hola {nombre_url}! 👋")
        st.subheader("Hemos guardado tus respuestas del chat. 🚀")
        st.info("Ya tienes la mitad del camino hecho. Solo elige tus **clínicas favoritas**, ingresa tus **datos de contacto** y haz clic en Cotizar.")
    else:
        st.title("¡Hola! 👋")
        st.subheader("Descubre el seguro de salud ideal para ti en 3 simples pasos.")
        
        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            st.info("**1. Tu Perfil**\n\nDatos básicos y familiares.")
        with col_g2:
            st.info("**2. Preferencias**\n\nCobertura y clínicas.")
        with col_g3:
            st.info("**3. Cotización**\n\nComparativo y PDF.")

    st.divider()

    # LA CAJA SECRETA: Menú lateral (Sidebar)
    with st.sidebar.expander("🔒 Acceso Interno YQ"):
        st.text_input("Código", type="password", key="codigo_secreto", label_visibility="collapsed", placeholder="")

    # --- CAPTURA INTELIGENTE DE VARIABLES DESDE ZOHO ---
    nombre_url = st.query_params.get("nombre", "")
    edad_url = st.query_params.get("edad", "")
    cont_url = st.query_params.get("continuidad", "")
    salud_url = st.query_params.get("salud", "")
    dep_url = st.query_params.get("dependientes", "0") 
    clinicas_url = st.query_params.get("clinicas", "")

    try: edad_default = int(edad_url) if edad_url else None
    except: edad_default = None

    try: num_dep = int(''.join(filter(str.isdigit, dep_url))) if any(c.isdigit() for c in dep_url) else 0
    except: num_dep = 0

    salud_lower = salud_url.lower()
    index_salud = 1 if "cronic" in salud_lower or "crónic" in salud_lower else 0

    nom = st.text_input("Nombres completos", value=nombre_url)
    
    col_edad, col_salud = st.columns(2)
    with col_edad:
        edad = st.number_input("Edad", min_value=0, max_value=99, value=edad_default, placeholder="Edad del asegurado")
        edad_calculo = edad if edad is not None else 0 
    with col_salud:
        salud = st.radio("Estado de salud", ["Sano", "Crónico"], index=index_salud, horizontal=True)
        
    st.write("### 👨‍👩‍👧‍‍👦 2. Familia")
    st.caption("💡 *Si deseas asegurar a tu cónyuge o hijos, indica cuántos son aquí abajo. Luego ingresa la edad de cada uno para calcular el descuento familiar.*")
    
    n_dep = st.number_input("Número de dependientes adicionales", 0, 10, value=num_dep)
    
    familia = [{'edad': edad_calculo, 'salud': salud, 'rol': 'Titular'}]
    txt_fam = []
    if n_dep > 0:
        for i in range(n_dep):
            col_edep, col_sdep = st.columns(2)
            with col_edep:
                e = st.number_input(f"Edad Dep {i+1}", 0, 99, 10, key=f"edad_dep_{i}")
            with col_sdep:
                s = st.radio(f"Salud Dep {i+1}", ["Sano", "Crónico"], horizontal=True, key=f"salud_dep_{i}")
            familia.append({'edad': e, 'salud': s, 'rol': 'Dependiente'})
            txt_fam.append(f"Dep ({e}a)")
    
    txt_dependientes = ", ".join(txt_fam) if txt_fam else "Ninguno"

    st.write("### ⚙️ 3. Filtros y Preferencias")
    
    index_continuidad = 1 if "continuidad" in cont_url.lower() else 0
    cont = st.selectbox("Tipo de asegurado", ["Nuevo", "Vengo con continuidad"], index=index_continuidad)

    cob = st.multiselect("Cobertura", ["Básica", "Integral", "Integral + Reembolso", "Integral + Cobertura Internacional"], default=["Integral", "Básica"])
    
    clinicas_default = []
    if clinicas_url:
        for clinica in clinicas_unicas:
            if clinica.lower() in clinicas_url.lower():
                clinicas_default.append(clinica)

    clinicas = st.multiselect(
        "Clínicas de preferencia", 
        clinicas_unicas, 
        default=clinicas_default, 
        placeholder="Ej: Escribe el nombre de tu clínica (Puedes elegir varias)"
    )
    
    if es_cliente:
        score_rimac = "ROJO"
        cliente_rimac = "No"
    else:
        col_sc, col_cr = st.columns(2)
        with col_sc:
            score_rimac = st.selectbox("Scoring Rímac", ["BUENO", "AMBAR", "ROJO", "GRIS"], index=2)
        with col_cr:
            cliente_rimac = st.radio("¿Es cliente Rímac?", ["Sí", "No"], index=1, horizontal=True)
    
    correo, celular = "", ""
    if es_cliente:
        st.info("Para generar tu cotización, por favor ingresa tus datos de contacto:")
        col_cel, col_mail = st.columns(2)
        with col_cel:
            celular = st.text_input("Celular / Whatsapp", max_chars=9, placeholder="Ej: 999123456")
        with col_mail:
            correo = st.text_input("Correo Electrónico", placeholder="cliente@correo.com")

    # --- GENERACIÓN DE DICCIONARIOS EN MEMORIA ---
    descuentos_mensual = {}
    descuentos_anual = {}
    for c in df_full['Aseguradora'].unique():
        for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
            val_men = obtener_descuento_matriz(campanas_maestras, c, p, cont, edad_calculo, len(familia), "Mensual", score_rimac, cliente_rimac, salud, mes_actual)
            val_anu = obtener_descuento_matriz(campanas_maestras, c, p, cont, edad_calculo, len(familia), "Contado", score_rimac, cliente_rimac, salud, mes_actual)
            descuentos_mensual[(c,p)] = int(val_men)
            descuentos_anual[(c,p)] = int(val_anu)

    if es_admin:
        with st.expander(f"Campañas {mes_actual} (Modo Admin)"):
            st.write("Verifica o modifica los descuentos a mano:")
            for c in df_full['Aseguradora'].unique():
                for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
                    st.markdown(f"**{c} - {p}**")
                    col_da1, col_da2 = st.columns(2)
                    llave_dinamica = f"{c}_{p}_{edad}_{cont}_{score_rimac}_{cliente_rimac}"
                    with col_da1:
                        descuentos_mensual[(c,p)] = st.number_input(f"Mensual %", 0, 100, descuentos_mensual[(c,p)], key=f"dm_{llave_dinamica}")
                    with col_da2:
                        descuentos_anual[(c,p)] = st.number_input(f"Anual %", 0, 100, descuentos_anual[(c,p)], key=f"da_{llave_dinamica}")
                    st.write("---")
        
        st.divider()
        st.write("### Base de Datos (Nube)")
        col_admin_1, col_admin_2 = st.columns(2)
        with col_admin_1:
            if st.button("🔄 Probar Conexión Sheets"):
                client = get_gspread_client()
                if client: st.success("✅ Conectado a Sheets")
                else: st.error("❌ No hay cliente configurado.")
        with col_admin_2:
            if st.button("📥 Descargar Historial Completo"):
                df_historial = descargar_historial_sheets()
                if df_historial is not None and not df_historial.empty:
                    csv = df_historial.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(label="💾 Guardar CSV", data=csv, file_name=f"historial_{obtener_hora_peru().strftime('%d%m%Y')}.csv", mime="text/csv")
                    st.success(f"Registros encontrados: {len(df_historial)}")

    es_solo_internacional = (len(cob) == 1 and "Integral + Cobertura Internacional" in cob)
    requiere_clinica = not es_solo_internacional and es_cliente

    st.divider()
    if st.button("Cotizar", type="primary", use_container_width=True):   # --- RESULTADOS ---
    if st.session_state['resultados'] is not None:
        res = st.session_state['resultados']
        if res.empty:
            st.error(f"⚠️ No se encontraron planes. Intenta cambiar los filtros.")
        else:
            op = {f"{r['Aseguradora']} {r['Plan']}": r['ID'] for _,r in res.iterrows()}
            
            if es_cliente:
                mejores_planes = res.drop_duplicates(subset=['Aseguradora'], keep='first')
                st.success(f"¡Hemos analizado todas las opciones y seleccionamos los {len(mejores_planes)} mejores planes para ti!")
                
                df_resumen = mejores_planes[['Aseguradora', 'Plan', 'Precio_Mensual_Final', 'Precio_Anual_Final']].copy()
                df_resumen.columns = ['Aseguradora', 'Mejor Plan Sugerido', 'Mensual', 'Anual']
                df_resumen['Mensual'] = df_resumen['Mensual'].apply(lambda x: f"S/ {x:,.0f}")
                df_resumen['Anual'] = df_resumen['Anual'].apply(lambda x: f"S/ {x:,.0f}")
                st.dataframe(df_resumen, hide_index=True, use_container_width=True)
                
                st.info("👇 Descarga tu cotización detallada para ver coberturas, o contáctanos para contratar.")
                
                numero_whatsapp = "51906462225"
                mensaje_wa = f"Hola, mi nombre es {nom}. Acabo de usar el cotizador web de salud y quiero contratar el plan que me sugirieron."
                enlace_wa = f"https://wa.me/{numero_whatsapp}?text={urllib.parse.quote(mensaje_wa)}"
                            
                col_btn_pdf, col_btn_wa = st.columns(2)
                
                planes_seleccionados = mejores_planes.apply(lambda r: f"{r['Aseguradora']} {r['Plan']}", axis=1).tolist()
                sel = planes_seleccionados[0]
                clin_txt = ", ".join(st.session_state.get('clinicas_sel', [])) or "su red de afiliados"
                razon = f"Este plan es el que tiene mejor precio considerando las clínicas que prefiere ({clin_txt}) y sus beneficios."
                if cont == "Nuevo": razon += " Recuerde revisar los periodos de carencia."

                with col_btn_pdf:
                    pdf_res = generar_pdf(st.session_state['perfil'], mejores_planes, op[sel], razon, incrementar_folio(), es_vista_cliente=True)
                    if isinstance(pdf_res, str): 
                        st.error(pdf_res)
                    else:
                        nom_clean = st.session_state.get('nombre_cliente', 'Cliente').strip().split()[0]
                        fecha_str = obtener_hora_peru().strftime("%d%m%y")
                        
                        datos_para_sheet = [obtener_hora_peru().strftime('%Y-%m-%d %H:%M'), nom, correo, celular, edad, str(cob), cont, str(clinicas), len(familia)-1, "Cliente"]
                        
                        st.download_button(
                            label="📄 Descargar Cotización Detallada", 
                            data=pdf_res, 
                            file_name=f"COTISALUD_{nom_clean}_{fecha_str}.pdf", 
                            mime="application/pdf", 
                            use_container_width=True,
                            on_click=guardar_en_sheets,
                            args=(datos_para_sheet,),
                            key="btn_descarga_pdf_cliente"
                        )
                
                with col_btn_wa:
                    st.markdown(f"""
                        <a href='{enlace_wa}' target='_blank' style='display: flex; align-items: center; justify-content: center; width: 100%; height: 42px; background-color: #25D366; color: white; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px;'>
                            📲 Contratar vía WhatsApp
                        </a>
                    """, unsafe_allow_html=True)
            
            else:
                st.success(f"Vista Asesor: {len(res)} opciones compatibles.")
                cols = ['Aseguradora','Plan']
                if "Integral + Cobertura Internacional" in cob: cols += ['Int_Amb_Full', 'Int_Hosp_Full']
                if any(c != "Integral + Cobertura Internacional" for c in cob): cols += ['Txt_Cob_Amb', 'Txt_Cob_Hosp']

                df_view = res.copy()
                for c in df_view.columns:
                    if df_view[c].dtype == object:
                        df_view[c] = df_view[c].str.replace('<b>','').str.replace('</b>','').str.replace('<br/>','\n').str.replace('• ','')
                
                cols_final = [c for c in cols if c in df_view.columns]
                columnas_precios = ['Precio_Mensual_Base', 'Pct_Dscto_Mensual', 'Precio_Mensual_Final', 'Precio_Anual_Base', 'Pct_Dscto_Anual', 'Precio_Anual_Final']
                st.dataframe(df_view[cols_final + columnas_precios], hide_index=True)

                st.divider()
                st.subheader("Configuración del PDF (Asesor)")
                op_keys = list(op.keys())
                planes_seleccionados = []
                for i, opcion in enumerate(op_keys):
                    if st.checkbox(opcion, value=True, key=f"pdf_chk_{i}"):
                        planes_seleccionados.append(opcion)
                
                if not planes_seleccionados:
                    st.warning("⚠️ Debes dejar marcado al menos un plan.")
                else:
                    res_filtrado = res[res.apply(lambda r: f"{r['Aseguradora']} {r['Plan']}" in planes_seleccionados, axis=1)]
                    clin_txt = ", ".join(st.session_state.get('clinicas_sel', [])) or "su red de afiliados"
                    txt_motivo = f"Este plan es el que tiene mejor precio considerando las clínicas que prefiere ({clin_txt})."
                    sel = st.radio("Resaltar con la estrella (⭐):", planes_seleccionados)
                    razon = st.text_area("Motivo (Análisis del Experto):", value=txt_motivo)
                    
                    if st.button("Generar PDF", type="secondary"):
                        pdf_res = generar_pdf(st.session_state['perfil'], res_filtrado, op[sel], razon, incrementar_folio(), es_vista_cliente=False)
                        if isinstance(pdf_res, str): 
                            st.error(pdf_res)
                        else:
                            datos_para_sheet = [obtener_hora_peru().strftime('%Y-%m-%d %H:%M'), nom, correo, celular, edad, str(cob), cont, str(clinicas), len(familia)-1, "Admin/Asesor"]
                            guardar_en_sheets(datos_para_sheet)
                            
                            nom_clean = st.session_state.get('nombre_cliente', 'Cliente').strip().split()[0]
                            st.download_button("📥 Descargar PDF", pdf_res, f"COTISALUD_{nom_clean}.pdf", "application/pdf")

    # --- CIERRE HUMANO (Salvavidas UX Dinámico) ---
    if st.session_state.get('resultados') is None:
        st.divider()
        st.write("💡 **¿Tienes dudas sobre qué cobertura elegir o cómo funciona un seguro de salud/Continuidad?**")
        st.write("Recuerda que somos tu aliado, no un vendedor. No tienes que tomar esta decisión a solas.\n\n¡Escríbenos y nosotros te asesoramos completamente gratis!")
        numero_whatsapp = "51906462225"
        mensaje_ayuda = "Hola. Acabo de ingresar al cotizador web de salud y necesito ayuda para completarlo."
        if "nombre" in st.query_params: mensaje_ayuda += f" Mi nombre es {st.query_params['nombre']}."
        enlace_ayuda = f"https://wa.me/{numero_whatsapp}?text={urllib.parse.quote(mensaje_ayuda)}"

        st.markdown(f"""
            <a href='{enlace_ayuda}' target='_blank' style='display: flex; align-items: center; justify-content: center; width: 100%; height: 48px; background-color: #25D366; color: white; border-radius: 8px; text-decoration: none; font-weight: bold; font-family: sans-serif; box-shadow: 0 4px 12px rgba(37, 211, 102, 0.2);'>
                💬 Chatear con un experto
            </a>
        """, unsafe_allow_html=True)
