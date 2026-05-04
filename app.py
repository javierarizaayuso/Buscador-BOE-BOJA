import streamlit as st
import requests
from lxml import html, etree
import datetime
import re
import io
import pdfplumber
from urllib.parse import urljoin
import unicodedata

st.set_page_config(page_title="Radar Maestro BOE/BOJA - v20260504", layout="wide")

# --- FUNCIONES DE UTILIDAD ---

def normalizar(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower())
                  if unicodedata.category(c) != 'Mn')

def match_multiples_palabras_or(texto_destino, filtro_usuario):
    if not filtro_usuario or filtro_usuario.strip() == "":
        return True
    t_dest_norm = normalizar(texto_destino)
    palabras_filtro = filtro_usuario.split() 
    for palabra in palabras_filtro:
        if normalizar(palabra) in t_dest_norm:
            return True
    return False

def evaluate_boolean(text, expression):
    if not expression or expression.strip() == "": return True
    t_norm = normalizar(text)
    expr = normalizar(expression)
    expr = expr.replace(" and ", " and ").replace(" or ", " or ").replace(" not ", " not ")
    keywords = re.findall(r'\b(?!(?:and|or|not)\b)[a-z0-9]+\b', expr)
    for word in set(keywords):
        exists = str(word in t_norm)
        expr = re.sub(rf'\b{word}\b', exists, expr)
    try:
        return eval(expr, {"__builtins__": None}, {})
    except:
        return False

def resaltar_palabras(titulo, expresion):
    if not expresion or expresion.strip() == "":
        return titulo
    expr_limpia = normalizar(expresion).replace(" and ", " ").replace(" or ", " ").replace(" not ", " ").replace("(", " ").replace(")", " ")
    palabras_clave = set(p for p in expr_limpia.split() if len(p) > 2)
    titulo_resaltado = titulo
    for word in palabras_clave:
        try:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            titulo_resaltado = pattern.sub(lambda m: f"**{m.group(0)}**", titulo_resaltado)
        except: continue
    return titulo_resaltado

def corregir_url(path):
    if not path: return ""
    if path.startswith("http"): return path
    if path.startswith("//"): return "https:" + path
    return "https://www.boe.es" + path

# --- MOTOR BOE (API XML) ---

def get_boe_data(date_obj):
    date_str = date_obj.strftime("%Y%m%d")
    url = f"https://www.boe.es/datosabiertos/api/boe/sumario/{date_str}"
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/xml'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return []
        root = etree.fromstring(response.content)
        results = []
        for seccion in root.xpath("//seccion"):
            nombre_sec = seccion.get("nombre") or ""
            for depto in seccion.xpath(".//departamento"):
                nombre_dep = depto.get("nombre") or ""
                for item in depto.xpath(".//item"):
                    results.append({
                        "fuente": "BOE",
                        "seccion": nombre_sec,
                        "organismo": nombre_dep,
                        "titulo": item.findtext("titulo") or "",
                        "url": corregir_url(item.findtext("url_pdf")),
                        "url_html": corregir_url(item.findtext("url_html"))
                    })
        return results
    except: return []

# --- MOTOR BOJA (LOCALIZACIÓN Y EXTRACCIÓN PDF) ---

def get_boletines_del_dia(fecha_obj):
    """Localización híbrida: Hub del día o Calendario Anual."""
    f_str = fecha_obj.strftime("%Y%m%d")
    anio = str(fecha_obj.year)
    dia_num = str(fecha_obj.day)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    mes_nombre = meses[fecha_obj.month - 1]
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    boletines = set()

    # 1. Intentar Hub del día
    try:
        r = requests.get(f"https://www.juntadeandalucia.es/eboja/{f_str}.html", headers=headers, timeout=5)
        if r.status_code == 200:
            links = html.fromstring(r.content).xpath('//a/@href')
            for l in links:
                full = urljoin(f"https://www.juntadeandalucia.es/eboja/{f_str}.html", l)
                if re.search(rf'/eboja/{anio}/\d+/(?:c\d+/)?', full):
                    boletines.add(re.search(rf'.*/eboja/{anio}/\d+/(?:c\d+/)?', full).group(0))
    except: pass

    # 2. Intentar Calendario Anual
    if not boletines:
        try:
            r = requests.get(f"https://www.juntadeandalucia.es/eboja/{anio}", headers=headers, timeout=5)
            if r.status_code == 200:
                tree = html.fromstring(r.content)
                xpath_cal = f'//table[contains(@summary, "{mes_nombre}")]//a[text()="{dia_num}"]/@href'
                links_cal = tree.xpath(xpath_cal)
                for l in links_cal:
                    full = urljoin("https://www.juntadeandalucia.es", l)
                    base = re.search(rf'.*/eboja/{anio}/\d+/', full)
                    if base: boletines.add(base.group(0))
        except: pass

    return sorted(list(boletines))

def extraer_anuncios_boja_pdf(pdf_content, boletin_fuente):
    anuncios = []
    es_comp = "/c" in boletin_fuente
    LIMITE_SUPERIOR = 20 if es_comp else 95 
    LIMITE_INFERIOR = 780
    
    KEYWORDS_NUEVO_ORG = ["CONSEJERÍA", "AGENCIA", "DELEGACIÓN", "PRESIDENCIA", "SECRETARÍA", 
                          "CONSEJO", "INSTITUTO", "PARLAMENTO", "TRIBUNAL", "UNIVERSIDAD", "COMISIÓN"]
    
    regex_ruido = re.compile(r'bboojjaa|boletin oficial de la junta de andalucia|numero \d+|sumario\s*-\s*página\s*\d+|[a-z]+,\s*\d+\s*de\s*[a-z]+\s*de\s*202\d', re.IGNORECASE)

    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        sec_actual = "Sin Sección"
        dep_actual = ""
        buffer_titulo = []

        for page in pdf.pages:
            words = page.extract_words()
            links = page.hyperlinks
            if not words: continue
            
            lineas_dict = {}
            for w in words:
                if w['top'] < LIMITE_SUPERIOR or w['top'] > LIMITE_INFERIOR: continue
                t = round(w['top'], 1)
                if t not in lineas_dict: lineas_dict[t] = []
                lineas_dict[t].append(w)
            
            for t in sorted(lineas_dict.keys()):
                linea_words = sorted(lineas_dict[t], key=lambda x: x['x0'])
                line_text = " ".join([w['text'] for w in linea_words]).strip()
                if regex_ruido.search(line_text): continue

                match_sec = re.match(r'^(\d+(\.\d+)*\.\s+[A-ZÁÉÍÓÚÑa-z]+(?:\s+[a-z]+)*)(.*)', line_text)
                if match_sec:
                    sec_actual = match_sec.group(1).strip()
                    dep_actual = ""
                    buffer_titulo = []
                    resto = match_sec.group(3).strip()
                    if resto and resto.isupper() and len(resto) > 5:
                        dep_actual = resto
                    continue
                
                if line_text.isupper() and len(line_text) > 8 and "BOJA" not in line_text:
                    es_inicio = any(line_text.startswith(kw) for kw in KEYWORDS_NUEVO_ORG)
                    if es_inicio:
                        dep_actual = line_text
                    else:
                        if not buffer_titulo:
                            dep_actual = (dep_actual + " " + line_text).strip()
                        else:
                            dep_actual = line_text
                    buffer_titulo = []
                    continue

                if "texto núm." in line_text.lower():
                    titulo_final = regex_ruido.sub("", " ".join(buffer_titulo)).strip()
                    link_uri = ""
                    if links:
                        for hl in links:
                            if abs(hl['top'] - t) < 15:
                                link_uri = hl['uri']
                                break
                    if titulo_final and dep_actual:
                        fuente_txt = "BOJA Princ." if not es_comp else f"BOJA Comp. ({boletin_fuente.strip('/').split('/')[-1]})"
                        anuncios.append({
                            "fuente": fuente_txt,
                            "seccion": sec_actual,
                            "organismo": dep_actual,
                            "titulo": titulo_final,
                            "url": link_uri,
                            "url_html": "",
                            "filtro_aplicado": ""
                        })
                    buffer_titulo = []
                else:
                    if dep_actual and len(line_text) > 3 and not line_text.isdigit():
                        buffer_titulo.append(line_text)
    return anuncios

# --- INTERFAZ ---

st.title("📑 Radar Maestro BOE/BOJA by JAA")

with st.form("radar_form"):
    fecha = st.date_input("Fecha de consulta", datetime.date.today())
    st.markdown("### ⚙️ Reglas de Vigilancia")
    
    default_rules = [
        {"act": True, "bol": "BOE", "sec": "", "dep": "", "words": "ayuda OR subvencion OR incentivos"},
        {"act": True, "bol": "BOE", "sec": "", "dep": "jefatura competencia", "words": ""},
        {"act": True, "bol": "BOE", "sec": "", "dep": "ecologica", "words": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador"},
        {"act": True, "bol": "BOE", "sec": "", "dep": "movilidad", "words": "DGT OR comunicaciones OR ADIF AND NOT formalización"},
        {"act": False, "bol": "BOE", "sec": "", "dep": "", "words": ""},
        {"act": True, "bol": "BOJA", "sec": "", "dep": "", "words": "ayuda OR subvencion OR incentivos"},
        {"act": True, "bol": "BOJA", "sec": "generales", "dep": "presidencia", "words": ""},
        {"act": True, "bol": "BOJA", "sec": "otras anuncios generales", "dep": "hacienda agua sostenibilidad energía fomento", "words": "NOT riego AND NOT subterranea AND NOT vertido AND NOT extincion AND NOT sancionador"},
        {"act": False, "bol": "BOJA", "sec": "", "dep": "", "words": ""}
    ]

    rules_input = []
    c_h = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
    c_h[0].write("**Act.**"); c_h[1].write("**Bol.**"); c_h[2].write("**Sección (OR)**"); c_h[3].write("**Organismo (OR)**"); c_h[4].write("**Filtro Título (Bool)**")

    for i, r in enumerate(default_rules):
        c = st.columns([0.4, 0.7, 1.2, 1.3, 3.4])
        with c[0]: act = st.checkbox("", value=r["act"], key=f"a{i}")
        with c[1]: bol = st.selectbox("", ["BOE", "BOJA"], index=0 if r["bol"]=="BOE" else 1, key=f"bol{i}")
        with c[2]: sec = st.text_input("", value=r["sec"], key=f"s{i}")
        with c[3]: dep = st.text_input("", value=r["dep"], key=f"d{i}")
        with c[4]: words = st.text_input("", value=r["words"], key=f"w{i}")
        rules_input.append({"active": act, "boletin": bol, "seccion": sec, "depto": dep, "palabras": words})

    submit = st.form_submit_button("🚀 EJECUTAR VIGILANCIA")
    
if submit:
    active_rules = [r for r in rules_input if r["active"]]
    data_pool = []
    with st.spinner("Analizando boletines..."):
        # Descarga BOE
        if any(r["boletin"] == "BOE" for r in active_rules):
            res_boe = get_boe_data(fecha)
            data_pool.extend(res_boe)
            st.write(f"✅ BOE: {len(res_boe)} anuncios leídos.")
        
        # Descarga BOJA
        if any(r["boletin"] == "BOJA" for r in active_rules):
            urls_boja = get_boletines_del_dia(fecha)
            total_boja_ads = []
            for b_url in urls_boja:
                try:
                    num_bol_txt = b_url.strip('/').split('/')[-1]
                    st.write(f"📥 Accediendo a BOJA: `{b_url}`")
                    r_bol = requests.get(b_url, timeout=10)
                    pdf_rel = html.fromstring(r_bol.content).xpath('//a[contains(@title, "sumario") and contains(@href, ".pdf")]/@href')
                    if pdf_rel:
                        pdf_url = urljoin(b_url, pdf_rel[0])
 # LOG                  st.write(f"   📄 Leyendo PDF: `{pdf_url}`")
                        r_pdf = requests.get(pdf_url, timeout=25)
                        ads = extraer_anuncios_boja_pdf(r_pdf.content, b_url)
                        total_boja_ads.extend(ads)
                        st.write(f"   👍 {len(ads)} anuncios extraídos.")
                except: continue
            data_pool.extend(total_boja_ads)
            st.write(f"✅ BOJA: {len(total_boja_ads)} anuncios leídos en total.")

    if data_pool:
        encontrados = []
        for anuncio in data_pool:
            for rule in active_rules:
                if rule["boletin"] not in anuncio["fuente"]: continue
                # Filtros por capas
                if not match_multiples_palabras_or(anuncio["seccion"], rule["seccion"]): continue
                if not match_multiples_palabras_or(anuncio["organismo"], rule["depto"]): continue
                if not evaluate_boolean(anuncio["titulo"], rule["palabras"]): continue
                item = anuncio.copy(); item["filtro_aplicado"] = rule["palabras"]
                encontrados.append(item); break 

        if encontrados:
            encontrados.sort(key=lambda x: (0 if "BOE" in x["fuente"] else 1, normalizar(x["organismo"])))
            st.success(f"🔥 Detectados {len(encontrados)} anuncios de interés.")
            last_bol_group, last_org = None, None
            for e in encontrados:
                curr_bol_group = "BOE" if "BOE" in e["fuente"] else "BOJA"
                if curr_bol_group != last_bol_group:
                    st.header(f"🏛 {curr_bol_group}")
                    last_bol_group, last_org = curr_bol_group, None
                if e["organismo"] != last_org:
                    st.markdown(f"### <u>**{e['organismo']}**</u>", unsafe_allow_html=True)
                    last_org = e["organismo"]
                t_final = resaltar_palabras(e["titulo"], e["filtro_aplicado"])
                with st.expander(t_final):
                    st.write(f"**📂 Sección:** {e['seccion']} | **📍 Fuente:** {e['fuente']}")
                    st.markdown(f"[📄 Ver PDF]({e['url']})" + (f" | [🔗 Ver HTML]({e['url_html']})" if e['url_html'] else ""))
        else:
            st.warning("No hay coincidencias con los filtros aplicados.")
    else:
        st.error("No se han podido recuperar datos. Verifica la fecha seleccionada.")

# Creado por Javier Ariza Ayuso con Google AI Studio

