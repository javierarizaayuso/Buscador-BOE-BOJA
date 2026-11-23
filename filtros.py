"""Lógica de filtrado del Radar Maestro BOE/BOJA.

Módulo sin dependencias de Streamlit, para poder probarlo de forma aislada.

Reglas de coincidencia:
- Las comparaciones ignoran mayúsculas y tildes.
- Una palabra del filtro coincide si aparece al *comienzo* de una palabra del
  texto ("subvencion" encuentra "subvenciones", pero "agua" ya no encuentra
  "paraguas").
"""
import re
import unicodedata
from functools import lru_cache


class ExpresionBooleanaError(ValueError):
    """La expresión booleana de un filtro no es válida."""


# --- NORMALIZACIÓN Y COINCIDENCIA DE PALABRAS ---

def normalizar(texto):
    """Minúsculas y sin tildes."""
    if not texto:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower())
                   if unicodedata.category(c) != 'Mn')


@lru_cache(maxsize=1024)
def _patron_termino(palabra_normalizada):
    """Patrón que busca la palabra al comienzo de una palabra del texto."""
    return re.compile(r'(?<![a-z0-9])' + re.escape(palabra_normalizada))


def match_multiples_palabras_or(texto_destino, filtro_usuario):
    """True si el texto contiene alguna de las palabras del filtro (separadas por espacios)."""
    if not filtro_usuario or filtro_usuario.strip() == "":
        return True
    t_dest_norm = normalizar(texto_destino)
    for palabra in filtro_usuario.split():
        if _patron_termino(normalizar(palabra)).search(t_dest_norm):
            return True
    return False


# --- EXPRESIONES BOOLEANAS (AND / OR / NOT / paréntesis) ---
#
# Gramática (precedencia: NOT > AND > OR):
#   expr   := and ('or' and)*
#   and    := not ('and' not)*
#   not    := 'not' not | atomo
#   atomo  := PALABRA | '(' expr ')'

_PALABRA_RE = re.compile(r'[a-z0-9]+(?:[-./][a-z0-9]+)*')
_OPERADORES = ('and', 'or', 'not')


def _tokenizar(expresion_normalizada):
    tokens = []
    pos = 0
    while pos < len(expresion_normalizada):
        c = expresion_normalizada[pos]
        if c.isspace():
            pos += 1
        elif c == '(':
            tokens.append(('LP', c))
            pos += 1
        elif c == ')':
            tokens.append(('RP', c))
            pos += 1
        else:
            m = _PALABRA_RE.match(expresion_normalizada, pos)
            if not m:
                raise ExpresionBooleanaError(f"carácter no permitido: '{c}'")
            palabra = m.group()
            tokens.append(('OP' if palabra in _OPERADORES else 'WORD', palabra))
            pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self):
        tok = self._peek()
        self.i += 1
        return tok

    def parse(self):
        nodo = self._or()
        sobrante = self._peek()
        if sobrante is not None:
            raise ExpresionBooleanaError(
                f"no se esperaba '{sobrante[1]}' aquí (¿falta un AND u OR entre palabras?)")
        return nodo

    def _or(self):
        nodos = [self._and()]
        while self._peek() == ('OP', 'or'):
            self._next()
            nodos.append(self._and())
        return nodos[0] if len(nodos) == 1 else ('or', nodos)

    def _and(self):
        nodos = [self._not()]
        while self._peek() == ('OP', 'and'):
            self._next()
            nodos.append(self._not())
        return nodos[0] if len(nodos) == 1 else ('and', nodos)

    def _not(self):
        if self._peek() == ('OP', 'not'):
            self._next()
            return ('not', self._not())
        return self._atomo()

    def _atomo(self):
        tok = self._next()
        if tok is None:
            raise ExpresionBooleanaError("la expresión termina de forma inesperada")
        tipo, valor = tok
        if tipo == 'WORD':
            return ('term', valor)
        if tipo == 'LP':
            nodo = self._or()
            if self._next() != ('RP', ')'):
                raise ExpresionBooleanaError("falta cerrar un paréntesis")
            return nodo
        raise ExpresionBooleanaError(f"no se esperaba '{valor}' en esta posición")


@lru_cache(maxsize=256)
def compilar_expresion(expresion):
    """Convierte la expresión en un árbol. Devuelve None si está vacía.

    Lanza ExpresionBooleanaError si no es válida.
    """
    if not expresion or expresion.strip() == "":
        return None
    return _Parser(_tokenizar(normalizar(expresion))).parse()


def _evaluar(nodo, texto_normalizado):
    tipo = nodo[0]
    if tipo == 'term':
        return _patron_termino(nodo[1]).search(texto_normalizado) is not None
    if tipo == 'not':
        return not _evaluar(nodo[1], texto_normalizado)
    if tipo == 'and':
        return all(_evaluar(n, texto_normalizado) for n in nodo[1])
    return any(_evaluar(n, texto_normalizado) for n in nodo[1])


def evaluate_boolean(text, expression):
    """Evalúa la expresión sobre el texto. Lanza ExpresionBooleanaError si es inválida."""
    arbol = compilar_expresion(expression)
    if arbol is None:
        return True
    return _evaluar(arbol, normalizar(text))


# --- RESALTADO ---

def _terminos_positivos(nodo, negado=False):
    """Palabras de la expresión que no están bajo un NOT."""
    tipo = nodo[0]
    if tipo == 'term':
        if not negado:
            yield nodo[1]
    elif tipo == 'not':
        yield from _terminos_positivos(nodo[1], not negado)
    else:
        for hijo in nodo[1]:
            yield from _terminos_positivos(hijo, negado)


def _normalizar_con_mapa(texto):
    """Como normalizar(), pero devuelve también la posición original de cada carácter."""
    chars, mapa = [], []
    for i, c in enumerate(texto):
        for ch in unicodedata.normalize('NFD', c.lower()):
            if unicodedata.category(ch) != 'Mn':
                chars.append(ch)
                mapa.append(i)
    return ''.join(chars), mapa


def resaltar_palabras(titulo, expresion):
    """Pone en negrita (Markdown) las palabras buscadas, aunque el título lleve tildes."""
    if not expresion or expresion.strip() == "":
        return titulo
    try:
        arbol = compilar_expresion(expresion)
    except ExpresionBooleanaError:
        return titulo
    if arbol is None:
        return titulo
    palabras = sorted({p for p in _terminos_positivos(arbol) if len(p) > 2},
                      key=len, reverse=True)
    if not palabras:
        return titulo

    norm, mapa = _normalizar_con_mapa(titulo)
    patron = re.compile('|'.join(r'(?<![a-z0-9])' + re.escape(p) for p in palabras))

    partes, pos = [], 0
    for m in patron.finditer(norm):
        ini = max(mapa[m.start()], pos)
        fin = mapa[m.end() - 1] + 1
        while fin < len(titulo) and unicodedata.category(titulo[fin]) == 'Mn':
            fin += 1
        if fin <= ini:
            continue
        partes.append(titulo[pos:ini])
        partes.append(f"**{titulo[ini:fin]}**")
        pos = fin
    partes.append(titulo[pos:])
    return ''.join(partes)
