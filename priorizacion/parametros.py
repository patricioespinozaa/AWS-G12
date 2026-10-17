"""Parámetros configurables de las reglas, versionados (F0014).

`reglas.py` define la fórmula y los valores de fábrica. Este módulo agrega el catálogo de lo que la Administradora
puede cambiar (con nombre, descripción, unidad y límites), valida un conjunto de valores y lo aplica reemplazando los
atributos de `reglas`. Cada conjunto guardado es una versión (`priorizacion.version_reglas`, solo inserción) y deja
`R.VERSION_REGLAS = "reglas-v0.1+c<n>"`, que viaja en cada evaluación, propuesta y corrida.

Los valores son globales del proceso. Para que una simulación no se mezcle con un cálculo en curso:
    with parametros.lectura():   ...   # cualquier cálculo (peticiones, consolidación)
    with parametros.escritura(): ...   # simular o aplicar una versión
"""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import reglas as R

BASE = R.VERSION_REGLAS                      # versión del código; la configuración agrega "+c<n>"


@dataclass(frozen=True)
class Parametro:
    clave: str
    grupo: str
    nombre: str
    descripcion: str
    atributo: str                            # constante de reglas.py
    llave: object = None                     # entrada del diccionario, si la constante es un diccionario
    indice: int | None = None                # posición dentro de una tupla (rango mínimo/máximo, categoría)
    tipo: str = "numero"                     # numero | entero | opcion
    unidad: str = ""
    minimo: float | None = None
    maximo: float | None = None
    opciones: tuple[str, ...] = ()

    def leer(self, fuente=None):
        valor = getattr(R, self.atributo) if fuente is None else fuente[self.atributo]
        if self.llave is not None:
            valor = valor[self.llave]
        if self.indice is not None:
            valor = valor[self.indice]
        return valor


def _slug(texto: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else "_" for c in t).strip("_")


def _catalogo() -> list[Parametro]:
    P = Parametro
    c: list[Parametro] = [
        P("nivel.umbral_alta", "Niveles", "Umbral de prioridad alta",
          "Puntaje de nivel desde el que la propuesta es alta.", "UMBRAL_ALTA", unidad="puntos", minimo=1, maximo=100),
        P("nivel.umbral_media", "Niveles", "Umbral de prioridad media",
          "Puntaje de nivel desde el que la propuesta es media (debe ser menor que el de alta).", "UMBRAL_MEDIA",
          unidad="puntos", minimo=0, maximo=100),
    ]
    c += [P(f"nivel.base_{n}", "Niveles", f"Base de la prioridad inicial {n}",
            f"Puntaje con que parte una solicitud ingresada como {n}, antes de las señales clínicas.",
            "BASE_PRIORIDAD", llave=n, unidad="puntos", minimo=-50, maximo=100) for n in R.NIVELES]
    c += [P(f"evento.{t}.{_slug(s)}", "Eventos clínicos", f"{R.NOMBRE_TIPO_EVENTO[t]} · {s}",
            "Puntos que suma (o resta, si es negativo) un evento de este tipo, antes de su decaimiento.",
            "PESO_EVENTO", llave=(t, s), unidad="puntos", minimo=-20, maximo=30) for t, s in R.PESO_EVENTO]
    c += [
        P("evento.vida_media_dias", "Eventos clínicos", "Vida media de un evento",
          "Días en que un evento pierde la mitad de su peso.", "VIDA_MEDIA_DIAS", tipo="entero", unidad="días",
          minimo=7, maximo=730),
        P("evento.ventana_dias", "Eventos clínicos", "Antigüedad máxima de un evento",
          "Los eventos más antiguos no aportan.", "VENTANA_EVENTOS_DIAS", tipo="entero", unidad="días",
          minimo=30, maximo=1825),
        P("evento.ventana_regla_dura_dias", "Eventos clínicos", "Ventana de la regla dura",
          "Un evento grave dentro de esta ventana deja la propuesta en alta con alerta.", "VENTANA_REGLA_DURA_DIAS",
          tipo="entero", unidad="días", minimo=1, maximo=180),
        P("evento.ventana_mejora_dias", "Eventos clínicos", "Ventana de evidencia de mejora",
          "Una señal de mejora en esta ventana permite bajar de nivel (sin ella, se mantiene la prioridad).",
          "VENTANA_MEJORA_DIAS", tipo="entero", unidad="días", minimo=7, maximo=365),
    ]
    c += [P(f"riesgo.dx.{dx}", "Riesgo basal", f"{dx} · {txt.split(':')[0]}", f"Riesgo basal del diagnóstico ({txt}).",
            "RIESGO_BASAL_DX", llave=dx, indice=0, tipo="opcion", opciones=("alto", "medio", "bajo"))
          for dx, (_, txt) in R.RIESGO_BASAL_DX.items()]
    for cat in ("alto", "medio", "bajo"):
        c += [
            P(f"riesgo.puntos.{cat}", "Riesgo basal", f"Puntos de orden por riesgo {cat}",
              "Se suman al puntaje de orden (no cambian el nivel).", "PUNTOS_RIESGO_BASAL", llave=cat,
              unidad="puntos", minimo=-10, maximo=20),
            P(f"riesgo.ajuste_senales.{cat}", "Riesgo basal", f"Ajuste de las señales con riesgo {cat}",
              "Proporción en que se amplifican (+) o atenúan (−) las señales clínicas positivas. 0,25 = ×1,25.",
              "AJUSTE_SENALES_RIESGO_BASAL", llave=cat, unidad="proporción", minimo=-0.9, maximo=2),
            P(f"riesgo.plazo_dias.{cat}", "Riesgo basal", f"Plazo de referencia con riesgo {cat}",
              "Días de espera que llevan el aporte de la espera a su máximo.", "PLAZO_REFERENCIA_DIAS", llave=cat,
              tipo="entero", unidad="días", minimo=15, maximo=1095),
        ]
    c += [
        P("edad.umbral_mayor", "Edad y espera", "Edad del tramo mayor", "Desde esta edad se suman los puntos del tramo mayor.",
          "EDAD_UMBRAL_MAYOR", tipo="entero", unidad="años", minimo=50, maximo=100),
        P("edad.puntos_mayor", "Edad y espera", "Puntos del tramo mayor", "Puntos de orden desde la edad del tramo mayor.",
          "EDAD_PUNTOS_MAYOR", unidad="puntos", minimo=0, maximo=10),
        P("edad.umbral", "Edad y espera", "Edad del tramo intermedio",
          "Desde esta edad (y antes del tramo mayor) se suman los puntos del tramo intermedio.", "EDAD_UMBRAL",
          tipo="entero", unidad="años", minimo=40, maximo=100),
        P("edad.puntos", "Edad y espera", "Puntos del tramo intermedio", "Puntos de orden del tramo intermedio.",
          "EDAD_PUNTOS", unidad="puntos", minimo=0, maximo=10),
        P("espera.max_aporte", "Edad y espera", "Aporte máximo de la espera",
          "Puntos de orden al cumplir el plazo de referencia.", "MAX_APORTE_ESPERA", unidad="puntos", minimo=0, maximo=20),
    ]
    for tipo, (lo, hi) in R.RANGOS_NORMALES.items():
        nombre, unidad = R.NOMBRE_MEDICION[tipo], R.UNIDADES[tipo]
        c += [P(f"medicion.{tipo}.minimo", "Mediciones", f"{nombre}: mínimo normal",
                "Límite inferior del rango normal.", "RANGOS_NORMALES", llave=tipo, indice=0, unidad=unidad,
                minimo=0, maximo=1000),
              P(f"medicion.{tipo}.maximo", "Mediciones", f"{nombre}: máximo normal",
                "Límite superior del rango normal (debe ser mayor que el mínimo).", "RANGOS_NORMALES", llave=tipo,
                indice=1, unidad=unidad, minimo=0, maximo=1000)]
    c += [
        P("medicion.peso_desviacion", "Mediciones", "Peso de un valor fuera de rango",
          "Puntos por cada ancho de rango fuera del rango normal.", "PESO_DESVIACION", unidad="puntos", minimo=0, maximo=20),
        P("medicion.max_desviacion", "Mediciones", "Desviación máxima considerada",
          "Anchos de rango como máximo (tope del aporte).", "MAX_DESVIACION", unidad="anchos", minimo=0.1, maximo=10),
        P("medicion.peso_tendencia", "Mediciones", "Peso de la tendencia de empeoramiento",
          "Puntos por cada ancho de rango por mes de empeoramiento.", "PESO_TENDENCIA", unidad="puntos", minimo=0, maximo=60),
        P("medicion.max_aporte_tendencia", "Mediciones", "Aporte máximo de la tendencia", "", "MAX_APORTE_TENDENCIA",
          unidad="puntos", minimo=0, maximo=20),
        P("medicion.umbral_tendencia", "Mediciones", "Pendiente mínima para considerar tendencia",
          "Pendientes menores se consideran estables (anchos de rango por mes).", "UMBRAL_TENDENCIA", minimo=0, maximo=1),
        P("medicion.aporte_tendencia_mejora", "Mediciones", "Aporte de una tendencia de mejora",
          "Con último valor normal; negativo resta.", "APORTE_TENDENCIA_MEJORA", unidad="puntos", minimo=-10, maximo=0),
        P("medicion.min_mediciones_tendencia", "Mediciones", "Mediciones mínimas para una tendencia", "",
          "MIN_MEDICIONES_TENDENCIA", tipo="entero", minimo=2, maximo=20),
        P("medicion.ventana_tendencia_dias", "Mediciones", "Ventana de la tendencia", "", "VENTANA_TENDENCIA_DIAS",
          tipo="entero", unidad="días", minimo=30, maximo=730),
        P("medicion.peso_persistencia", "Mediciones", "Peso de la persistencia fuera de rango",
          "Puntos × proporción de mediciones fuera de rango en la ventana.", "PESO_PERSISTENCIA", unidad="puntos",
          minimo=0, maximo=20),
        P("medicion.ventana_persistencia_dias", "Mediciones", "Ventana de la persistencia", "",
          "VENTANA_PERSISTENCIA_DIAS", tipo="entero", unidad="días", minimo=7, maximo=365),
        P("patron.escalada_aporte", "Patrones", "Aumento de dosis + examen alterado",
          "Puntos cuando ambos ocurren dentro de la ventana.", "PATRON_ESCALADA_APORTE", unidad="puntos", minimo=0, maximo=20),
        P("patron.escalada_ventana_dias", "Patrones", "Ventana de la escalada", "", "PATRON_ESCALADA_VENTANA_DIAS",
          tipo="entero", unidad="días", minimo=7, maximo=365),
        P("patron.medicion_aporte", "Patrones", "Medición alterada antes de un evento",
          "Puntos cuando una medición alterada precede a un evento moderado o grave.", "PATRON_MEDICION_APORTE",
          unidad="puntos", minimo=0, maximo=20),
        P("patron.medicion_previa_dias", "Patrones", "Anticipación de la medición", "Días antes del evento.",
          "PATRON_MEDICION_PREVIA_DIAS", tipo="entero", unidad="días", minimo=1, maximo=180),
        P("patron.medicion_ventana_dias", "Patrones", "Ventana del patrón de medición", "", "PATRON_MEDICION_VENTANA_DIAS",
          tipo="entero", unidad="días", minimo=7, maximo=730),
        P("box.tasa_no_show_global", "Gestión del box", "Tasa global de inasistencia",
          "Punto de partida del riesgo de inasistencia de cada paciente (no entra al puntaje clínico).",
          "TASA_NO_SHOW_GLOBAL", unidad="proporción", minimo=0, maximo=1),
        P("box.peso_prior_no_show", "Gestión del box", "Peso del punto de partida",
          "Citas equivalentes con que se suaviza la tasa propia hacia la global.", "PESO_PRIOR_NO_SHOW",
          unidad="citas", minimo=0, maximo=20),
        P("box.umbral_riesgo_no_show", "Gestión del box", "Umbral de riesgo de inasistencia",
          "Desde esta probabilidad se marca riesgo de inasistencia.", "UMBRAL_RIESGO_NO_SHOW", unidad="proporción",
          minimo=0, maximo=1),
        P("box.vigencia_examen_dias", "Gestión del box", "Vigencia de un examen requerido", "", "VIGENCIA_EXAMEN_DIAS",
          tipo="entero", unidad="días", minimo=7, maximo=365),
        P("box.ventana_confirmacion_dias", "Gestión del box", "Ventana de confirmación de la cita", "",
          "VENTANA_CONFIRMACION_DIAS", tipo="entero", unidad="días", minimo=1, maximo=120),
    ]
    return c


CATALOGO: list[Parametro] = _catalogo()
POR_CLAVE: dict[str, Parametro] = {p.clave: p for p in CATALOGO}
ATRIBUTOS = sorted({p.atributo for p in CATALOGO})
FABRICA: dict[str, object] = {a: copy.deepcopy(getattr(R, a)) for a in ATRIBUTOS}   # foto al importar

# Lo que se lista pero no se edita aquí (nombres, unidades y supuestos de la red)
SOLO_LECTURA = [
    ("Mediciones", "Unidades", "UNIDADES"),
    ("Mediciones", "Mediciones donde bajar es empeorar", "MEJOR_ALTO"),
    ("Eventos clínicos", "Subtipos que cuentan como mejora", "SUBTIPOS_MEJORA"),
    ("Gestión del box", "Examen requerido por especialidad", "REQUISITO_EXAMEN"),
    ("Canal de origen", "Canal de origen de la derivación", "CANAL_ORIGEN"),
]

numero_vigente = 0


def fabrica() -> dict[str, object]:
    return {p.clave: p.leer(FABRICA) for p in CATALOGO}


def vigentes() -> dict[str, object]:
    return {p.clave: p.leer() for p in CATALOGO}


def version_texto(numero: int) -> str:
    return BASE if numero == 0 else f"{BASE}+c{numero}"


@dataclass
class ErrorValidacion(Exception):
    errores: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return "; ".join(f"{POR_CLAVE[k].nombre if k in POR_CLAVE else k}: {m}" for k, m in self.errores.items())


def normalizar(valores: dict) -> dict[str, object]:
    """Completa con los valores de fábrica, convierte los tipos y valida. Lanza ErrorValidacion con cada problema."""
    errores: dict[str, str] = {}
    resultado = fabrica()
    for clave, valor in (valores or {}).items():
        p = POR_CLAVE.get(clave)
        if p is None:
            errores[clave] = "no es un parámetro configurable"
            continue
        if p.tipo == "opcion":
            if valor not in p.opciones:
                errores[clave] = f"debe ser {', '.join(p.opciones)}"
                continue
            resultado[clave] = valor
            continue
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            errores[clave] = "debe ser un número"
            continue
        if numero != numero or numero in (float("inf"), float("-inf")):
            errores[clave] = "debe ser un número"
            continue
        if p.tipo == "entero":
            if numero != int(numero):
                errores[clave] = "debe ser un número entero"
                continue
            numero = int(numero)
        if p.minimo is not None and numero < p.minimo or p.maximo is not None and numero > p.maximo:
            errores[clave] = f"debe estar entre {p.minimo:g} y {p.maximo:g}"
            continue
        resultado[clave] = numero
    # Reglas entre parámetros
    if resultado["nivel.umbral_media"] >= resultado["nivel.umbral_alta"]:
        errores.setdefault("nivel.umbral_media", "debe ser menor que el umbral de alta")
    if resultado["edad.umbral"] >= resultado["edad.umbral_mayor"]:
        errores.setdefault("edad.umbral", "debe ser menor que la edad del tramo mayor")
    for tipo in R.RANGOS_NORMALES:
        if resultado[f"medicion.{tipo}.minimo"] >= resultado[f"medicion.{tipo}.maximo"]:
            errores.setdefault(f"medicion.{tipo}.maximo", "debe ser mayor que el mínimo")
    if errores:
        raise ErrorValidacion(errores)
    return resultado


def diferencias(antes: dict, despues: dict) -> dict[str, dict]:
    return {k: {"anterior": antes.get(k), "nuevo": v} for k, v in despues.items() if antes.get(k) != v}


def _construir(valores: dict[str, object]) -> dict[str, object]:
    nuevos = {a: copy.deepcopy(FABRICA[a]) for a in ATRIBUTOS}
    for p in CATALOGO:
        v = valores[p.clave]
        if p.llave is None:
            nuevos[p.atributo] = v
            continue
        actual = nuevos[p.atributo][p.llave]
        if p.indice is not None:
            lista = list(actual)
            lista[p.indice] = v
            v = tuple(lista)
        nuevos[p.atributo][p.llave] = v
    return nuevos


def _aplicar_sin_candado(valores: dict[str, object], numero: int) -> None:
    global numero_vigente
    for atributo, valor in _construir(valores).items():
        setattr(R, atributo, valor)
    R.VERSION_REGLAS = version_texto(numero)
    numero_vigente = numero


def aplicar(valores: dict, numero: int) -> None:
    """Deja vigentes estos valores (ya normalizados o parciales) como la versión `numero` (0 = fábrica)."""
    completos = normalizar(valores)
    with escritura():
        _aplicar_sin_candado(completos, numero)


def aplicar_vigente(registro) -> int:
    """Aplica la última versión guardada en el registro, si es otra que la vigente. Devuelve su número."""
    ultima = registro.version_reglas_vigente()
    numero = 0 if ultima is None else int(ultima["numero"])
    if numero != numero_vigente:
        aplicar({} if ultima is None else ultima["valores"], numero)
    return numero


@contextmanager
def temporal(valores: dict):
    """Para simular: aplica `valores` y vuelve a la versión vigente al salir (con el candado de escritura)."""
    completos = normalizar(valores)
    with escritura():
        previos, numero = vigentes(), numero_vigente
        _aplicar_sin_candado(completos, -1)
        R.VERSION_REGLAS = f"{BASE}+simulacion"
        try:
            yield
        finally:
            _aplicar_sin_candado(previos, numero)


# -- candado de lectura y escritura ---------------------------------------------------------------------
class _CandadoLE:
    """Muchos lectores a la vez, o un solo escritor. Reentrante para el escritor (simular calcula leyendo)."""

    def __init__(self):
        self._cond = threading.Condition()
        self._lectores = 0
        self._escritor: int | None = None
        self._profundidad = 0

    @contextmanager
    def lectura(self):
        yo = threading.get_ident()
        with self._cond:
            if self._escritor != yo:
                self._cond.wait_for(lambda: self._escritor is None)
                self._lectores += 1
                propia = True
            else:
                propia = False
        try:
            yield
        finally:
            if propia:
                with self._cond:
                    self._lectores -= 1
                    self._cond.notify_all()

    @contextmanager
    def escritura(self):
        yo = threading.get_ident()
        with self._cond:
            if self._escritor == yo:
                self._profundidad += 1
            else:
                self._cond.wait_for(lambda: self._escritor is None and self._lectores == 0)
                self._escritor, self._profundidad = yo, 1
        try:
            yield
        finally:
            with self._cond:
                self._profundidad -= 1
                if self._profundidad == 0:
                    self._escritor = None
                    self._cond.notify_all()


_candado = _CandadoLE()
lectura = _candado.lectura
escritura = _candado.escritura


def catalogo_json() -> list[dict]:
    fab, vig = fabrica(), vigentes()
    return [{"clave": p.clave, "grupo": p.grupo, "nombre": p.nombre, "descripcion": p.descripcion, "tipo": p.tipo,
             "unidad": p.unidad, "minimo": p.minimo, "maximo": p.maximo, "opciones": list(p.opciones),
             "valor": vig[p.clave], "fabrica": fab[p.clave]} for p in CATALOGO]


def solo_lectura_json() -> list[dict]:
    filas = []
    for grupo, nombre, atributo in SOLO_LECTURA:
        valor = getattr(R, atributo)
        if isinstance(valor, dict):
            texto = "; ".join(f"{k}: {', '.join(v) if isinstance(v, tuple) else v}" for k, v in valor.items())
        else:
            texto = ", ".join(sorted(valor))
        filas.append({"grupo": grupo, "nombre": nombre, "valor": texto})
    return filas
