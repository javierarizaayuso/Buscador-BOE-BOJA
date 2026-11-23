"""Descarga y extracción de anuncios del BOE (API XML) y del BOJA (PDF del sumario).

Este módulo no depende de Streamlit. Las funciones de red LANZAN excepciones
(requests.RequestException, lxml.etree.LxmlError, ValueError) en lugar de
devolver listas vacías, para que la interfaz pueda avisar al usuario y no
confundir "ha fallado la descarga" con "no hay anuncios".
"""
import io
import logging
import re
from urllib.parse import urljoin

import pdfplumber
import requests
from lxml import etree, html

logger = logging.getLogger(__name__)

# --- AJUSTES DE MAQUETACIÓN DEL PDF DEL BOJA ---
# Si la Junta cambia el diseño del sumario, es lo primero que habrá que revisar.
BOJA_LIMITE_SUPERIOR_PRINCIPAL = 95   # puntos desde el borde superior (ignora la cabecera)
BOJA_LIMITE_SUPERIOR_COMPLEMENTARIO = 20
BOJA_LIMITE_INFERIOR = 780            # ignora el pie de página
BOJA_DISTANCIA_ENLACE = 15            # distancia vertical máxima entre "texto núm." y su enlace

BOJA_KEYWORDS_NUEVO_ORG = [
    "CONSEJERÍA", "AGENCIA", "DELEGACIÓN", "PRESIDENCIA", "SECRETARÍA",
    "CONSEJO", "INSTITUTO", "PARLAMENTO", "TRIBUNAL", "UNIVERSIDAD", "COMISIÓN",
]

REGEX_RUIDO = re.compile(
    r'bboojjaa|boletin oficial de la junta de andalucia|numero \d+|'
    r'sumario\s*-\s*página\s*\d+|[a-z]+,\s*\d+\s*de\s*[a-z]+\s*de\s*202\d',
    re.IGNORECASE)

_SESION = requests.Session()
_SESION.headers.update({'User-Agent': 'Mozilla/5.0'})


def corregir_url(path):
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if path.startswith("//"):
        return "https:" + path
    return "https://www.boe.es" + path


# --- BOE (API XML) ---

def descargar_sumario_boe(fecha):
    """Devuelve la lista de anuncios del BOE de esa fecha.

    Devuelve None si el BOE no publicó sumario ese día (404: domingo, festivo
    o fecha futura). Lanza excepción si la descarga o el XML fallan.
    """
    url = f"https://www.boe.es/datosabiertos/api/boe/sumario/{fecha.strftime('%Y%m%d')}"
    response = _SESION.get(url, headers={'Accept': 'application/xml'}, timeout=15)
    if response.status_code == 404:
        return None
    response.raise_for_status()

    root = etree.fromstring(response.content)
    resultados = []
    for seccion in root.xpath("//seccion"):
        nombre_sec = seccion.get("nombre") or ""
        for depto in seccion.xpath(".//departamento"):
            nombre_dep = depto.get("nombre") or ""
            for item in depto.xpath(".//item"):
                resultados.append({
                    "fuente": "BOE",
                    "seccion": nombre_sec,
                    "organismo": nombre_dep,
                    "titulo": item.findtext("titulo") or "",
                    "url": corregir_url(item.findtext("url_pdf")),
                    "url_html": corregir_url(item.findtext("url_html")),
                })
    return resultados


# --- BOJA: localización de boletines ---

def localizar_boletines_boja(fecha_obj):
    """URLs de los boletines (principal y complementarios) del BOJA de esa fecha.

    Prueba primero la página del día y, si no hay resultado, el calendario anual.
    Lanza excepción solo si no se encuentra nada Y alguna petición falló.
    """
    f_str = fecha_obj.strftime("%Y%m%d")
    anio = str(fecha_obj.year)
    dia_num = str(fecha_obj.day)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    mes_nombre = meses[fecha_obj.month - 1]

    boletines = set()
    errores = []

    # 1. Página del día
    url_dia = f"https://www.juntadeandalucia.es/eboja/{f_str}.html"
    try:
        r = _SESION.get(url_dia, timeout=8)
        if r.status_code == 200:
            for link in html.fromstring(r.content).xpath('//a/@href'):
                full = urljoin(url_dia, link)
                m = re.search(rf'.*/eboja/{anio}/\d+/(?:c\d+/)?', full)
                if m:
                    boletines.add(m.group(0))
    except (requests.RequestException, etree.LxmlError) as e:
        logger.warning("BOJA: fallo leyendo %s: %s", url_dia, e)
        errores.append(e)

    # 2. Calendario anual
    if not boletines:
        url_cal = f"https://www.juntadeandalucia.es/eboja/{anio}"
        try:
            r = _SESION.get(url_cal, timeout=8)
            if r.status_code == 200:
                tree = html.fromstring(r.content)
                xpath_cal = f'//table[contains(@summary, "{mes_nombre}")]//a[text()="{dia_num}"]/@href'
                for link in tree.xpath(xpath_cal):
                    full = urljoin("https://www.juntadeandalucia.es", link)
                    m = re.search(rf'.*/eboja/{anio}/\d+/', full)
                    if m:
                        boletines.add(m.group(0))
        except (requests.RequestException, etree.LxmlError) as e:
            logger.warning("BOJA: fallo leyendo %s: %s", url_cal, e)
            errores.append(e)

    if not boletines and errores:
        raise errores[-1]
    return sorted(boletines)


# --- BOJA: descarga y extracción del PDF ---

def obtener_anuncios_boletin_boja(b_url):
    """Descarga el sumario PDF de un boletín del BOJA y extrae sus anuncios."""
    r_bol = _SESION.get(b_url, timeout=10)
    r_bol.raise_for_status()
    pdf_rel = html.fromstring(r_bol.content).xpath(
        '//a[contains(@title, "sumario") and contains(@href, ".pdf")]/@href')
    if not pdf_rel:
        raise ValueError(f"No se encontró el enlace al sumario PDF en {b_url}")
    pdf_url = urljoin(b_url, pdf_rel[0])
    logger.debug("Leyendo PDF %s", pdf_url)
    r_pdf = _SESION.get(pdf_url, timeout=25)
    r_pdf.raise_for_status()
    return extraer_anuncios_boja_pdf(r_pdf.content, b_url)


def extraer_anuncios_boja_pdf(pdf_content, boletin_fuente):
    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        return extraer_anuncios_de_paginas(pdf.pages, boletin_fuente)


def extraer_anuncios_de_paginas(paginas, boletin_fuente):
    """Extrae anuncios de páginas con la interfaz de pdfplumber.

    Cada página debe ofrecer extract_words() (dicts con 'text', 'top', 'x0') y
    hyperlinks (dicts con 'top', 'uri'). Separada del PDF para poder probarla.
    """
    anuncios = []
    es_comp = "/c" in boletin_fuente
    limite_superior = (BOJA_LIMITE_SUPERIOR_COMPLEMENTARIO if es_comp
                       else BOJA_LIMITE_SUPERIOR_PRINCIPAL)

    sec_actual = "Sin Sección"
    dep_actual = ""
    buffer_titulo = []

    for page in paginas:
        words = page.extract_words()
        links = page.hyperlinks
        if not words:
            continue

        lineas_dict = {}
        for w in words:
            if w['top'] < limite_superior or w['top'] > BOJA_LIMITE_INFERIOR:
                continue
            lineas_dict.setdefault(round(w['top'], 1), []).append(w)

        for t in sorted(lineas_dict.keys()):
            linea_words = sorted(lineas_dict[t], key=lambda x: x['x0'])
            line_text = " ".join(w['text'] for w in linea_words).strip()
            if REGEX_RUIDO.search(line_text):
                continue

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
                es_inicio = any(line_text.startswith(kw) for kw in BOJA_KEYWORDS_NUEVO_ORG)
                if es_inicio:
                    dep_actual = line_text
                elif not buffer_titulo:
                    dep_actual = (dep_actual + " " + line_text).strip()
                else:
                    dep_actual = line_text
                buffer_titulo = []
                continue

            if "texto núm." in line_text.lower():
                titulo_final = REGEX_RUIDO.sub("", " ".join(buffer_titulo)).strip()
                link_uri = ""
                for hl in links or []:
                    if abs(hl['top'] - t) < BOJA_DISTANCIA_ENLACE:
                        link_uri = hl['uri']
                        break
                if titulo_final and dep_actual:
                    fuente_txt = ("BOJA Princ." if not es_comp
                                  else f"BOJA Comp. ({boletin_fuente.strip('/').split('/')[-1]})")
                    anuncios.append({
                        "fuente": fuente_txt,
                        "seccion": sec_actual,
                        "organismo": dep_actual,
                        "titulo": titulo_final,
                        "url": link_uri,
                        "url_html": "",
                        "filtro_aplicado": "",
                    })
                buffer_titulo = []
            elif dep_actual and len(line_text) > 3 and not line_text.isdigit():
                buffer_titulo.append(line_text)
    return anuncios
