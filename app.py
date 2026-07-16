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

# --- CONFIGURACIÓN DE PÁGINA Y ESTILOS ---
st.set_page_config(page_title="Cotizador YQ Seguros", page_icon="🛡️", layout="wide")

# --- 1. EL SALUDO PERSONALIZADO ---
if "nombre" in st.query_params:
    nombre_cliente = st.query_params["nombre"]
    st.title(f"¡Hola {nombre_cliente}! 👋")
    st.subheader("Vamos a evaluar qué seguro de salud es el adecuado para ti.")
else:
    st.title("¡Hola! 👋")
    st.subheader("Vamos a evaluar qué seguro de salud es el adecuado para ti.")

st.divider()

st.markdown("""
    <style>
    .stButton>button {
        background-color: #2456A6;
        color: white;
        border-radius: 8px;
    }
    .stButton>button:hover {
        background-color: #1a428a;
        color: white;
    }
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
    """Guarda la cotización en Google Sheets."""
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
    SMTP_SERVER = "smtppro.zoho.com"
    SMTP_PORT = 587
    SENDER_EMAIL = "administracion@yqcorredores.com"
    if "EMAIL_PASSWORD" in st.secrets:
        SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    else:
        SENDER_PASSWORD = "TU_CONTRASEÑA_AQUI" 
        
    RECEIVER_EMAIL = "administracion@yqcorredores.com"

    clinicas_txt = ", ".join(clinicas) if clinicas else "Sin preferencia específica"
    cobertura_txt = ", ".join(plan_interes_list) if isinstance(plan_interes_list, list) else str(plan_interes_list)
    fecha_hora_peru = obtener_hora_peru().strftime('%d/%m/%Y %H:%M')

    asunto = f"NUEVO LEAD DE COTIZADOR SALUD: {cliente}"
    cuerpo = f"""Hola Chicos,\n\nUn cliente ha generado una cotización de salud:\n\nDATOS DEL CLIENTE:\nNombre: {cliente}\nCorreo: {correo}\nWhatsApp: {celular}\n\nDATOS DE LA COTIZACIÓN:\nEdad Titular: {edad} años\nInterés: {cobertura_txt}\nCondición: {continuidad}\nScoring Rímac: {score_rimac}\nCliente Rímac: {cliente_rimac}\nClínicas Preferidas: {clinicas_txt}\nTotal Asegurados: {n_familia + 1}\n\nFecha: {fecha_hora_peru}"""

    try:
        if SENDER_PASSWORD == "TU_CONTRASEÑA_AQUI": return True
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = SENDER_EMAIL, RECEIVER_EMAIL, asunto
        msg.attach(MIMEText(cuerpo, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return True
    except:
        return False

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

        # Cargar info_adicional.csv si existe para los links
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
    
    PLANES_BASICA = ['Esencial', 'Esencial Plus', 'Multisalud Base', 'Medisalud Lite', 'Medisalud Base']
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
        
        if "Vengo con continuidad" == continuidad and "MAPFRE" in cia_clean: continue
        if "RIMAC" in cia_clean and familia[0]['edad'] >= 65 and "ORO" not in plan_clean: continue
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
        
        # OBTENCIÓN DE DESCUENTOS USANDO LOS DICCIONARIOS (Permite la edición manual)
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
def generar_pdf(perfil, df, id_sel, razon, folio):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
        estilos = getSampleStyleSheet()
        
        AZUL = colors.HexColor("#2456A6"); DORADO_FONDO = colors.HexColor("#FFF2CC"); DORADO_BORDE = colors.HexColor("#D6B656")
        VERDE = colors.HexColor("#28A745"); ROJO = colors.HexColor("#D32F2F"); GRIS = colors.HexColor("#6E7A8A"); AZUL_CLARO = colors.HexColor("#E6F3FF")
        
        st_tit = ParagraphStyle('T', parent=estilos['Heading1'], fontName='Helvetica-Bold', fontSize=14, textColor=AZUL, leading=16)
        st_sub = ParagraphStyle('S', parent=estilos['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=AZUL)
        st_norm = ParagraphStyle('N', parent=estilos['Normal'], fontSize=9, textColor=GRIS, leading=11)
        st_bold = ParagraphStyle('B', parent=st_norm, fontName='Helvetica-Bold', textColor=AZUL)
        st_analysis = ParagraphStyle('Analysis', parent=st_norm, leading=14, fontSize=9)
        st_th = ParagraphStyle('TH', parent=estilos['Normal'], fontSize=8, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
        st_td = ParagraphStyle('TD', parent=estilos['Normal'], fontSize=7.5, textColor=colors.black, leading=9)
        st_td_b = ParagraphStyle('TDB', parent=st_td, fontName='Helvetica-Bold', textColor=AZUL)

        elements = []
        # LOGO MÁS GRANDE (Se aumentó el width a 6.0cm y height a 2.2cm proporcionalmente)
        img = ImageRL("logo.png", width=4.0*cm, height=2.2*cm, kind='proportional') if os.path.exists("logo.png") else Paragraph("", st_norm)
        txt_header = """<b>YQ CORREDORES DE SEGUROS</b><br/>Propuesta de seguro de salud"""
        p_header = Paragraph(txt_header, st_tit)
        
        fecha_peru = obtener_hora_peru().strftime('%d/%m/%Y')
        txt_folio = f"<b>Folio:</b> {folio}<br/><b>Fecha:</b> {fecha_peru}"
        
        p_folio = Paragraph(txt_folio, ParagraphStyle('F', parent=st_norm, alignment=2))
        t_head = Table([[img, p_header, p_folio]], colWidths=[4.0*cm, 8.5*cm, 3.5*cm])
        t_head.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        elements.append(t_head)
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("En YQ Corredores de Seguros, entendemos la importancia de proteger tu salud. Te presentamos esta cotización personalizada con precios exclusivos.", st_norm))
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("TU PERFIL", st_sub))
        elements.append(Spacer(1, 5))
        data_perfil = [
            [Paragraph("<b>Titular:</b>", st_bold), Paragraph(perfil['Titular'], st_norm),
             Paragraph("<b>Cobertura:</b>", st_bold), Paragraph(perfil['Cobertura'], st_norm)],
            [Paragraph("<b>Dependientes:</b>", st_bold), Paragraph(perfil['Dependientes'], st_norm),
             Paragraph("<b>Condición:</b>", st_bold), Paragraph(perfil['Continuidad'], st_norm)]
        ]
        t_perf = Table(data_perfil, colWidths=[3.0*cm, 7.5*cm, 2.5*cm, 5.0*cm])
        t_perf.setStyle(TableStyle([('LINEBELOW', (0,0), (-1,-1), 0.5, colors.lightgrey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('PADDING', (0,0), (-1,-1), 5)]))
        elements.append(t_perf)
        elements.append(Spacer(1, 20))

        es_int = "Internacional" in perfil['Cobertura']
        if es_int:
            headers = ['Plan', 'Clínicas: Redes', 'Int. Amb', 'Int. Hosp', 'Pago Mensual', 'Pago Anual']
            anchos = [3.1*cm, 3.2*cm, 3.6*cm, 3.8*cm, 2.1*cm, 2.2*cm]
        else:
            headers = ['Plan', 'Clínicas: Redes', 'Int. Amb', 'Int. Hosp', 'Pago Mensual', 'Pago Anual']
            anchos = [3.1*cm, 3.2*cm, 3.6*cm, 3.8*cm, 2.1*cm, 2.2*cm]

        data = [[Paragraph(h, st_th) for h in headers]]
        
        for _, row in df.iterrows():
            rec = (row['ID'] == id_sel)
            txt_p = f"<b>{row['Aseguradora']}</b><br/>{row['Plan']}"
            if rec: txt_p = "⭐ RECOMENDADO ⭐<br/>" + txt_p
            
            links = []
            # LOGICA DE ENLACES A PRUEBA DE FALLOS
            cartilla = str(row.get('Link_Cartilla', '')).strip()
            if cartilla and cartilla != '-' and cartilla.lower() != 'nan':
                href = cartilla if cartilla.startswith('http') else 'https://' + cartilla
                links.append(f"<a href='{href}' color='blue'><u>Cartilla</u></a>")
                
            carencia = str(row.get('Link_Carencia', '')).strip()
            if carencia and carencia != '-' and carencia.lower() != 'nan':
                href_c = carencia if carencia.startswith('http') else 'https://' + carencia
                links.append(f"<a href='{href_c}' color='green'><u>Carencia</u></a>")
            
            if links: txt_p += "<br/>" + " | ".join(links)

            dsc_men = row['Dsc_Num_Mensual']
            dsc_anu = row['Dsc_Num_Anual']
            
            precio_anual_str = f"S/ {row['Precio_Anual_Final']:,.2f}"
            precio_mensual_str = f"S/ {row['Precio_Mensual_Final']:,.0f}"

            if dsc_anu > 0:
                ahorro_anual = row['Precio_Anual_Base'] - row['Precio_Anual_Final']
                precio_anual_str = f"<strike color='grey'>S/ {row['Precio_Anual_Base']:,.0f}</strike><br/><b>{precio_anual_str}</b><br/><font color='red' size='7'>Ahorras S/ {ahorro_anual:,.0f}</font>"
            
            if dsc_men > 0:
                ahorro_mensual = row['Precio_Mensual_Base'] - row['Precio_Mensual_Final']
                precio_mensual_str = f"<strike color='grey'>S/ {row['Precio_Mensual_Base']:,.0f}</strike><br/><b>{precio_mensual_str}</b><br/><font color='red' size='7'>Ahorras S/ {ahorro_mensual:,.0f}</font>"

            if es_int:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Int_Amb_Full'], st_td), Paragraph(row['Int_Hosp_Full'], st_td), Paragraph(precio_mensual_str, st_td_b), Paragraph(precio_anual_str, st_td_b)]
            else:
                fila = [Paragraph(txt_p, st_td), Paragraph(row['Txt_Clin_Red'], st_td), Paragraph(row['Txt_Cob_Amb'], st_td), Paragraph(row['Txt_Cob_Hosp'], st_td), Paragraph(precio_mensual_str, st_td_b), Paragraph(precio_anual_str, st_td_b)]
            data.append(fila)

        t = Table(data, colWidths=anchos, repeatRows=1)
        estilos_t = [('BACKGROUND', (0,0), (-1,0), AZUL), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('PADDING', (0,0), (-1,-1), 4)]
        for i, row in enumerate(df.iterrows()):
            if row[1]['ID'] == id_sel:
                estilos_t.append(('BACKGROUND', (0, i+1), (-1, i+1), DORADO_FONDO))
                estilos_t.append(('BOX', (0, i+1), (-1, i+1), 1.5, DORADO_BORDE))
        t.setStyle(TableStyle(estilos_t))
        elements.append(t)
        
        elements.append(Spacer(1, 10))
        if perfil['Continuidad'] == "Nuevo":
            aviso = "<b>IMPORTANTE:</b> Al ser un seguro nuevo, aplican periodos de carencia (30 días) y espera (para preexistencias). Por favor revise el enlace de 'carencia' en la tabla superior."
            t_warn = Table([[Paragraph(aviso, ParagraphStyle('W', parent=st_norm, textColor=AZUL))]], colWidths=[18*cm])
            t_warn.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), AZUL_CLARO), ('BOX', (0,0), (-1,-1), 0.5, AZUL), ('PADDING', (0,0), (-1,-1), 8)]))
            elements.append(t_warn)
        elif perfil['Continuidad'] == "Vengo con continuidad":
            aviso_cont = "<b>BENEFICIO DE CONTINUIDAD:</b> Para gozar del beneficio de continuidad debe haber estado asegurado dentro de los últimos 90 días con una póliza de salud EPS o Individual."
            t_cont = Table([[Paragraph(aviso_cont, ParagraphStyle('W', parent=st_norm, textColor=VERDE))]], colWidths=[18*cm])
            t_cont.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#E8F5E9")), ('BOX', (0,0), (-1,-1), 0.5, VERDE), ('PADDING', (0,0), (-1,-1), 8)]))
            elements.append(t_cont)

        elements.append(Spacer(1, 20))
        if razon:
            elements.append(Paragraph(f"¿POR QUÉ RECOMENDAMOS EL PLAN {str(df[df['ID']==id_sel]['Plan'].values[0]).upper()}?", st_sub))
            elements.append(Spacer(1, 15)) 
            t_box = Table([[Paragraph(f"<b>ANÁLISIS DEL EXPERTO:</b><br/><br/>{razon}", st_analysis)]], colWidths=[18*cm])
            t_box.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), DORADO_FONDO), ('BOX', (0,0), (-1,-1), 1, DORADO_BORDE), ('PADDING', (0,0), (-1,-1), 12)]))
            elements.append(t_box)
            elements.append(Spacer(1, 25))

        elements.append(Paragraph("¿Listo para estar protegido?", st_sub))
        elements.append(Spacer(1, 5))
        st_btn = ParagraphStyle('Btn', parent=st_norm, textColor=colors.white, alignment=1, fontName='Helvetica-Bold', fontSize=10)
        t_btns = Table([[Paragraph('<a href="https://wa.link/czc7jg">TENGO DUDAS: QUIERO MI ASESORÍA GRATUITA</a>', st_btn), "", Paragraph('<a href="https://wa.link/zwdc6r">¡QUIERO CONTRATAR AHORA!</a>', st_btn)]], colWidths=[7*cm, 1*cm, 7*cm], rowHeights=[1.2*cm])
        t_btns.setStyle(TableStyle([('BACKGROUND', (0,0), (0,0), AZUL), ('BACKGROUND', (2,0), (2,0), VERDE), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ROUNDED', (0,0), (-1,-1), 8)]))
        elements.append(t_btns)
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("Nota: Precios referenciales sujetos a evaluación médica. Incluyen IGV. Esta cotización dura sólo por 7 días.", ParagraphStyle('D', parent=st_norm, fontSize=9)))

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
    
    with st.sidebar:
        if os.path.exists("logo.png"):
            st.sidebar.image("logo.png", use_container_width=True)
            
        st.header("Datos del Cliente")
        nom = st.text_input("Nombres completos")
        edad = st.number_input("Edad", 0, 99, 30)
        salud = st.radio("Estado de salud", ["Sano", "Crónico"], horizontal=True)
        
        st.header("Familia")
        n_dep = st.number_input("Número de dependientes", 0, 10, 0)
        familia = [{'edad': edad, 'salud': salud, 'rol': 'Titular'}]
        txt_fam = []
        if n_dep > 0:
            for i in range(n_dep):
                e = st.number_input(f"Edad Dep {i+1}", 0, 99, 10, key=f"edad_dep_{i}")
                s = st.radio(f"Salud Dep {i+1}", ["Sano", "Crónico"], horizontal=True, key=f"salud_dep_{i}")
                familia.append({'edad': e, 'salud': s, 'rol': 'Dependiente'})
                txt_fam.append(f"Dep ({e}a)")
        
        txt_dependientes = ", ".join(txt_fam) if txt_fam else "Ninguno"

        st.header("Filtros Comerciales")
        cont = st.selectbox("Tipo de asegurado", ["Nuevo", "Vengo con continuidad"])
        score_rimac = st.selectbox("Scoring Rímac", ["BUENO", "AMBAR", "ROJO", "GRIS"])
        cliente_rimac = st.radio("¿Es cliente Rímac?", ["Sí", "No"], horizontal=True)
        
        st.header("Filtros Técnicos")
        cob = st.multiselect("Cobertura", ["Básica", "Integral", "Integral + Reembolso", "Integral + Cobertura Internacional"], default=["Integral"])
        clinicas = st.multiselect("Clínicas de preferencia", clinicas_unicas, placeholder="Puedes elegir más de una")
        
        st.header("Seguridad")
        codigo_acceso = st.text_input("Código opcional de descuento", type="password")
        
        es_admin = (codigo_acceso == CODIGO_ADMIN)
        es_asesor = (codigo_acceso in CODIGOS_ASESORES)
        es_cliente = (not es_admin and not es_asesor)

        correo, celular = "", ""
        if es_cliente:
            st.info("Para generar tu cotización, por favor ingresa tus datos de contacto:")
            correo = st.text_input("Correo Electrónico", placeholder="cliente@correo.com")
            celular = st.text_input("Celular / Whatsapp", max_chars=9, placeholder="Ej: 999123456")

        # GENERACIÓN DE DICCIONARIOS EN MEMORIA
        descuentos_mensual = {}
        descuentos_anual = {}
        for c in df_full['Aseguradora'].unique():
            for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
                val_men = obtener_descuento_matriz(campanas_maestras, c, p, cont, edad, len(familia), "Mensual", score_rimac, cliente_rimac, salud, mes_actual)
                val_anu = obtener_descuento_matriz(campanas_maestras, c, p, cont, edad, len(familia), "Contado", score_rimac, cliente_rimac, salud, mes_actual)
                descuentos_mensual[(c,p)] = int(val_men)
                descuentos_anual[(c,p)] = int(val_anu)

        if es_admin:
            with st.expander(f"Campañas {mes_actual} (Modo Admin)"):
                st.write("Verifica o modifica los descuentos a mano:")
                for c in df_full['Aseguradora'].unique():
                    for p in df_full[df_full['Aseguradora']==c]['Plan'].unique():
                        st.markdown(f"**{c} - {p}**")
                        col1, col2 = st.columns(2)
                        with col1:
                            # ESTA ES LA CLAVE: El diccionario ahora lee y guarda el input manual
                            descuentos_mensual[(c,p)] = st.number_input(f"Mensual %", 0, 100, descuentos_mensual[(c,p)], key=f"dm_{c}_{p}")
                        with col2:
                            descuentos_anual[(c,p)] = st.number_input(f"Anual %", 0, 100, descuentos_anual[(c,p)], key=f"da_{c}_{p}")
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

        if st.button("Cotizar"):
            if not cob:
                st.error("⚠️ Por favor selecciona al menos un tipo de Cobertura.")
            elif requiere_clinica and not clinicas:
                st.error("⚠️ Por favor selecciona al menos una Clínica de preferencia.")
            elif es_cliente and (not correo or not celular or len(celular) != 9):
                st.error("⚠️ Datos de contacto inválidos.")
            else:
                rol_actual = "Cliente" if es_cliente else "Admin/Asesor"
                guardar_en_sheets([obtener_hora_peru().strftime('%Y-%m-%d %H:%M'), nom, correo, celular, edad, str(cob), cont, str(clinicas), len(familia)-1, rol_actual])
                if es_cliente: enviar_notificacion(nom, correo, celular, cob, len(familia)-1, edad, clinicas, cont, score_rimac, cliente_rimac)
                
                # ENVIAMOS LOS DICCIONARIOS YA VALIDADOS
                st.session_state['resultados'] = buscar(df_full, df_redes, familia, clinicas, cont, cob, descuentos_mensual, descuentos_anual)
                st.session_state['perfil'] = {'Titular': f"{nom} ({edad} años)", 'Dependientes': txt_dependientes, 'Continuidad': cont, 'Cobertura': ", ".join(cob)}
                st.session_state['nombre_cliente'] = nom
                st.session_state['clinicas_sel'] = clinicas

    if st.session_state['resultados'] is not None:
        res = st.session_state['resultados']
        if res.empty:
            st.error(f"⚠️ No se encontraron planes. Intenta cambiar los filtros.")
        else:
            st.success(f"¡Hemos encontrado {len(res)} opciones compatibles!")
            
            if not es_cliente:
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
            else:
                st.info("👇 Descarga el PDF para ver el comparativo detallado.")

            st.divider()
            
            # --- NUEVA FUNCIONALIDAD: SELECCIÓN DE PLANES ---
            st.subheader("Configuración del PDF")
            st.write("Desmarca los planes que **NO** deseas incluir en el documento final:")
            
            op = {f"{r['Aseguradora']} {r['Plan']}": r['ID'] for _,r in res.iterrows()}
            op_keys = list(op.keys())
            
            planes_seleccionados = []
            
            # Usamos checkboxes en lista vertical para que JAMÁS se corte el texto
            for i, opcion in enumerate(op_keys):
                # value=True hace que vengan marcados por defecto
                if st.checkbox(opcion, value=True, key=f"pdf_chk_{i}"):
                    planes_seleccionados.append(opcion)
            
            if not planes_seleccionados:
                st.warning("⚠️ Debes dejar marcado al menos un plan para generar el PDF.")
            else:
                # Filtramos los resultados según lo que el usuario dejó marcado
                res_filtrado = res[res.apply(lambda r: f"{r['Aseguradora']} {r['Plan']}" in planes_seleccionados, axis=1)]
                
                clin_txt = ", ".join(st.session_state.get('clinicas_sel', [])) or "su red de afiliados"
                txt_motivo = f"Este plan es el que tiene mejor precio considerando las clínicas que prefiere ({clin_txt}) y sus beneficios."
                if cont == "Nuevo": txt_motivo += " Recuerde revisar los periodos de carencia."

                st.divider()
                st.write("### Recomendación Principal")
                # La recomendación ahora solo muestra las opciones que dejaste marcadas
                sel = planes_seleccionados[0] if es_cliente else st.radio("¿Qué plan deseas recomendar y resaltar con la estrella (⭐) en el PDF?", planes_seleccionados)
                razon = txt_motivo if es_cliente else st.text_area("Motivo (Análisis del Experto):", value=txt_motivo)
                
                if st.button("Generar PDF"):
                    # Generamos el PDF con res_filtrado en lugar de res
                    pdf_res = generar_pdf(st.session_state['perfil'], res_filtrado, op[sel], razon, incrementar_folio())
                    if isinstance(pdf_res, str): st.error(pdf_res)
                    else:
                        nom_clean = st.session_state.get('nombre_cliente', 'Cliente').strip().split()[0]
                        cls_clean = "_".join([c.strip().split()[0] for c in st.session_state.get('clinicas_sel', [])])
                        fecha_str = obtener_hora_peru().strftime("%d%m%y_%H%M")
                        st.download_button("Descargar PDF", pdf_res, f"COTISALUD_{nom_clean}_{cls_clean}_{fecha_str}.pdf", "application/pdf")

            # --- CIERRE HUMANO ---
            st.divider()
            st.subheader("¿Tienes dudas o quieres evaluar estas opciones?")
            st.write("Recuerda que somos tu aliado, no un vendedor. No tienes que tomar esta decisión a solas.")
            numero_whatsapp = "51948289614"
            mensaje_base = "Hola. Acabo de usar el cotizador de salud y me gustaría que me acompañen a evaluar mis opciones."
            if "nombre" in st.query_params: mensaje_base += f" Mi nombre es {st.query_params['nombre']}."
            st.link_button("💬 Escribir por WhatsApp a un asesor humano", f"https://wa.me/{numero_whatsapp}?text={urllib.parse.quote(mensaje_base)}")