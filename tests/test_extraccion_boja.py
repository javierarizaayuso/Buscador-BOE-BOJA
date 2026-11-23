"""Prueba la extracción con páginas simuladas (la interfaz de pdfplumber)."""
from boletines import extraer_anuncios_de_paginas

URL_PRINCIPAL = "https://www.juntadeandalucia.es/eboja/2026/215/"
URL_COMPL = "https://www.juntadeandalucia.es/eboja/2026/215/c1/"


class PaginaFalsa:
    def __init__(self, lineas, hyperlinks=None):
        self._words = []
        for top, texto in lineas:
            x = 50
            for palabra in texto.split():
                self._words.append({'text': palabra, 'top': top, 'x0': x})
                x += 60
        self.hyperlinks = hyperlinks or []

    def extract_words(self):
        return self._words


LINEAS = [
    (30, "BOJA número 215 - Sumario"),             # cabecera, fuera de límites
    (100, "1. Disposiciones generales"),
    (120, "CONSEJERÍA DE AGRICULTURA, PESCA Y DESARROLLO RURAL"),
    (140, "Resolución de la Dirección General de Ayudas,"),
    (155, "por la que se convocan ayudas."),
    (170, "Texto núm. 12345"),
    (200, "Sumario - Página 2"),                    # ruido
    (220, "CONSEJERÍA DE HACIENDA Y FINANCIACIÓN EUROPEA"),
    (240, "Orden por la que se aprueba el plan."),
    (255, "Texto núm. 12346"),
]
ENLACES = [{'top': 170, 'uri': 'https://x/12345.pdf'}, {'top': 255, 'uri': 'https://x/12346.pdf'}]


def test_extrae_anuncios_con_seccion_organismo_y_enlace():
    anuncios = extraer_anuncios_de_paginas([PaginaFalsa(LINEAS, ENLACES)], URL_PRINCIPAL)
    assert len(anuncios) == 2
    a = anuncios[0]
    assert a["fuente"] == "BOJA Princ."
    assert a["seccion"] == "1. Disposiciones generales"
    assert a["organismo"] == "CONSEJERÍA DE AGRICULTURA, PESCA Y DESARROLLO RURAL"
    assert a["titulo"] == "Resolución de la Dirección General de Ayudas, por la que se convocan ayudas."
    assert a["url"] == "https://x/12345.pdf"
    assert anuncios[1]["organismo"] == "CONSEJERÍA DE HACIENDA Y FINANCIACIÓN EUROPEA"
    assert anuncios[1]["url"] == "https://x/12346.pdf"


def test_boletin_complementario_etiqueta_y_limite_superior():
    # A top=50 el principal ignora la línea (límite 95) y el complementario la lee (límite 20)
    lineas = [(50, "1. Disposiciones generales")] + LINEAS[2:6]
    principal = extraer_anuncios_de_paginas([PaginaFalsa(lineas, ENLACES)], URL_PRINCIPAL)
    compl = extraer_anuncios_de_paginas([PaginaFalsa(lineas, ENLACES)], URL_COMPL)
    assert principal[0]["seccion"] == "Sin Sección"
    assert compl[0]["seccion"] == "1. Disposiciones generales"
    assert compl[0]["fuente"] == "BOJA Comp. (c1)"


def test_pagina_vacia_no_rompe():
    assert extraer_anuncios_de_paginas([PaginaFalsa([])], URL_PRINCIPAL) == []
