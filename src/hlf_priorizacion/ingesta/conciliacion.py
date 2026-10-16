"""Conciliación perfil ↔ tablas planas (sección 4.4).

Para cada perfil se comparan conteos y huellas por serie con los CSV. Si difieren, se usa el perfil
y se emite un hallazgo ``verificar`` (código ``conciliacion_diferencias``). ``agenda_box`` no se concilia.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from hlf_priorizacion.contrato.esquema import PerfilValido, normalizar_cie10
from hlf_priorizacion.ingesta.carga import TablasPlanas
from hlf_priorizacion.ingesta.normalizacion import id_medicion
from hlf_priorizacion.modelos import HallazgoDQ

CODIGO_CONCILIACION = "conciliacion_diferencias"

Clave = tuple[str, ...]


@dataclass(frozen=True)
class InformeConciliacion:
    hallazgos: dict[str, list[HallazgoDQ]] = field(default_factory=dict)
    pacientes_solo_en_tablas: tuple[str, ...] = ()
    tablas_no_conciliadas: tuple[str, ...] = ()

    @property
    def perfiles_con_diferencias(self) -> int:
        return len(self.hallazgos)


def _huella(claves: Iterable[Clave]) -> str:
    texto = "\n".join("|".join(c) for c in sorted(claves))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _bool(texto: str) -> str:
    return texto.strip().lower()


def _clave_medicion_csv(fila: dict[str, str]) -> Clave:
    try:
        valor = Decimal(fila["valor"])
        return (
            id_medicion(fila["id_paciente"], date.fromisoformat(fila["fecha_medicion"]), fila["tipo_medicion"], valor),
        )
    except (KeyError, ValueError, InvalidOperation):
        return ("fila_ilegible",)


def _claves_perfil(perfil: PerfilValido) -> dict[str, list[Clave]]:
    p = perfil.paciente
    return {
        "pacientes": [
            (
                perfil.id_paciente,
                str(p.edad),
                p.sexo,
                str(p.fallecido).lower(),
                p.fecha_defuncion.isoformat() if p.fecha_defuncion else "",
            )
        ],
        "lista_espera": [
            (
                s.id_solicitud,
                s.especialidad,
                normalizar_cie10(s.diagnostico_cie10),
                s.prioridad_inicial,
                s.fecha_ingreso_lista.isoformat(),
                s.estado,
            )
            for s in perfil.lista_espera
        ],
        "eventos_clinicos": [
            (e.id_evento, e.fecha_evento.isoformat(), e.tipo_evento, e.subtipo, e.severidad)
            for e in perfil.eventos_clinicos
        ],
        "mediciones": [
            (id_medicion(perfil.id_paciente, m.fecha_medicion, m.tipo_medicion, m.valor),) for m in perfil.mediciones
        ],
        "citaciones": [
            (c.id_cita, c.id_box, c.fecha_cita.isoformat(), c.especialidad, c.estado_cita) for c in perfil.citaciones
        ],
    }


_CLAVES_CSV: dict[str, Callable[[dict[str, str]], Clave]] = {
    "pacientes": lambda f: (
        f.get("id_paciente", ""),
        f.get("edad", ""),
        f.get("sexo", ""),
        _bool(f.get("fallecido", "")),
        f.get("fecha_defuncion", ""),
    ),
    "lista_espera": lambda f: (
        f.get("id_solicitud", ""),
        f.get("especialidad", ""),
        normalizar_cie10(f.get("diagnostico_cie10", "")),
        f.get("prioridad_inicial", ""),
        f.get("fecha_ingreso_lista", ""),
        f.get("estado", ""),
    ),
    "eventos_clinicos": lambda f: (
        f.get("id_evento", ""),
        f.get("fecha_evento", ""),
        f.get("tipo_evento", ""),
        f.get("subtipo", ""),
        f.get("severidad", ""),
    ),
    "mediciones": _clave_medicion_csv,
    "citaciones": lambda f: (
        f.get("id_cita", ""),
        f.get("id_box", ""),
        f.get("fecha_cita", ""),
        f.get("especialidad", ""),
        f.get("estado_cita", ""),
    ),
}


def conciliar(perfiles: list[PerfilValido], tablas: TablasPlanas) -> InformeConciliacion:
    por_tabla: dict[str, dict[str, list[Clave]]] = {}
    for nombre, filas in tablas.filas.items():
        agrupadas: dict[str, list[Clave]] = defaultdict(list)
        for fila in filas:
            agrupadas[fila.get("id_paciente", "")].append(_CLAVES_CSV[nombre](fila))
        por_tabla[nombre] = agrupadas

    hallazgos: dict[str, list[HallazgoDQ]] = {}
    ids_perfiles = set()
    for perfil in perfiles:
        ids_perfiles.add(perfil.id_paciente)
        diferencias = []
        for serie, claves in _claves_perfil(perfil).items():
            if serie not in por_tabla:
                continue
            en_tabla = por_tabla[serie].get(perfil.id_paciente, [])
            if len(claves) != len(en_tabla) or _huella(claves) != _huella(en_tabla):
                diferencias.append(f"{serie} (perfil {len(claves)}, tabla {len(en_tabla)})")
        if diferencias:
            hallazgos[perfil.id_paciente] = [
                HallazgoDQ(
                    codigo=CODIGO_CONCILIACION,
                    nivel="verificar",
                    ids_registro=[perfil.id_paciente, *(s.id_solicitud for s in perfil.lista_espera)],
                    detalle="series con diferencias perfil ↔ tabla: " + ", ".join(diferencias),
                )
            ]

    solo_tablas = sorted(
        {pid for agrupadas in por_tabla.values() for pid in agrupadas if pid and pid not in ids_perfiles}
    )
    return InformeConciliacion(
        hallazgos=hallazgos,
        pacientes_solo_en_tablas=tuple(solo_tablas),
        tablas_no_conciliadas=tablas.faltantes,
    )
