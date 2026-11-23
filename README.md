Buscador diario BOE y BOJA con filtros complejos
Creado por Javier Ariza Ayuso con Google AI Studio
Fecha versión: 27/04/2026
En sección y departamento se pueden poner palabras que pertenezcan al nombre de esa sección o departamento, separados por espacios para selección OR.
Por ejemplo, si se quiere buscar en la sección "II. Autoridades y personal. - A. Nombramientos, situaciones e incidencias" del BOE y en los ministerios de Transición Ecológica así como en el de Hacienda, se puede poner "personal" en sección (o más si se quier eponer más secciones) y "hacienda ecologica" en departamento.
En la palabra se admite AND, OR y NOT (este último para eliminar anuncios que contengan la palabra que sigue)
Insensible a mayúsculas y tildes.


## Notas de la versión v20261123

**Estructura del código**
- `app.py`: interfaz Streamlit (reglas, descargas con caché y resultados).
- `reglas.py` y `reglas.json`: reglas por defecto, validación y lectura/escritura del archivo.
- `filtros.py`: normalización, coincidencia de palabras y expresiones booleanas (sin `eval`).
- `boletines.py`: descarga del BOE (API XML) y del BOJA (PDF del sumario) y extracción de anuncios.
- `tests/`: pruebas automáticas (`pip install -r requirements-dev.txt` y luego `pytest`).

**Cambios de comportamiento**
- Las palabras de sección, organismo y título coinciden al **comienzo de una palabra** del texto: "subvencion" encuentra "subvenciones", pero "agua" ya no encuentra "paraguas".
- Si un filtro de título está mal escrito (por ejemplo `ayuda subvencion` sin AND/OR), se avisa antes de descargar nada en lugar de dejar la regla sin resultados.
- Los fallos de descarga (BOE o BOJA caídos, PDF ilegible o con formato distinto) se muestran como avisos. Un domingo o festivo sin BOE se indica como tal.
- Las descargas se guardan en caché 15 minutos (boletines) o 1 hora (PDF del BOJA).

**Si el BOJA deja de leerse bien:** los límites de maquetación del PDF están en las constantes `BOJA_*` al principio de `boletines.py`.

**Reglas de vigilancia (`reglas.json`)**
- Las reglas con las que arranca la app están en `reglas.json`. Para cambiarlas para todos los dispositivos, edita ese archivo en GitHub (también desde el móvil); Streamlit Cloud se redespliega solo.
- Dentro de la app, el panel «Guardar, cargar o restaurar reglas» permite **descargar** las reglas que ves en pantalla, **cargar** un `.json` propio (por ejemplo desde otro dispositivo) y **restaurar** las de `reglas.json`. Lo cargado solo afecta a tu sesión actual; para que sea permanente, sube el archivo al repositorio.
- Si `reglas.json` no existe se usan las reglas integradas en `reglas.py`; si está mal escrito, se usan también y la app avisa del error.
- Formato: `{"version": 1, "reglas": [{"activa": true, "boletin": "BOE", "seccion": "", "organismo": "", "titulo": "ayuda OR subvencion"}]}` (hasta 10 reglas; las que falten se rellenan como inactivas).
