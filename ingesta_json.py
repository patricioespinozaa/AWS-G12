import hashlib
import json
from pathlib import Path
import pandas as pd
from pydantic import ValidationError
from modelos import Perfil


def id_medicion(pid: str, fecha, tipo: str, valor) -> str:
    """ID basado en contenido: es el mismo venga del JSON o del CSV y no depende del orden de filas."""
    clave = f"{pid}|{pd.Timestamp(fecha).date()}|{tipo}|{float(valor)}"
    return "MED-" + hashlib.sha1(clave.encode()).hexdigest()[:10].upper()


def cargar_perfiles(path="data/perfiles.json"):
    crudo = json.loads(Path(path).read_text(encoding="utf-8"))
    perfiles, cuarentena = [], []
    for i, obj in enumerate(crudo):
        try:
            perfiles.append(Perfil.model_validate(obj))
        except ValidationError as e:
            # Un perfil malo no detiene el sistema: queda en cuarentena para revisión
            cuarentena.append({"posicion": i, "id_paciente": obj.get("id_paciente"),
                               "errores": e.errors(include_url=False)})
    return perfiles, cuarentena


def tablas_desde_perfiles(perfiles: list[Perfil], agenda_csv="data/agenda_box.csv") -> dict:
    pac, lista, ev, med, cit = [], [], [], [], []
    for p in perfiles:
        pid = p.id_paciente
        pac.append({"id_paciente": pid, **p.paciente.model_dump()})
        lista.append({"id_paciente": pid, **p.lista_espera.model_dump()})
        ev += [{"id_paciente": pid, **e.model_dump()} for e in p.eventos_clinicos]
        med += [{"id_paciente": pid,
                 "id_medicion": id_medicion(pid, m.fecha_medicion, m.tipo_medicion, m.valor),
                 **m.model_dump()} for m in p.mediciones]
        cit += [{"id_paciente": pid, "orden_origen": k, **c.model_dump()}
                for k, c in enumerate(p.citaciones)]

    def df(rows, fechas):
        d = pd.DataFrame(rows)
        for c in fechas:
            if c in d:
                d[c] = pd.to_datetime(d[c])
        return d

    return {
        "pacientes":  df(pac, ["fecha_defuncion"]),
        "lista":      df(lista, ["fecha_ingreso_lista"]),
        "eventos":    df(ev, ["fecha_evento"]),
        "mediciones": df(med, ["fecha_medicion"]),
        "citaciones": df(cit, ["fecha_cita"]),
        "agenda":     pd.read_csv(agenda_csv, parse_dates=["fecha"]),  # recurso del hospital, no del paciente
    }


def conciliar_con_csv(tablas_json: dict, tablas_csv: dict) -> list[dict]:
    """Verifica que JSON y CSV cuenten la misma historia antes de confiar en cualquiera."""
    llaves = {"pacientes": "id_paciente", "lista": "id_solicitud", "eventos": "id_evento",
              "mediciones": "id_medicion", "citaciones": "id_cita"}
    difs = []
    for t, k in llaves.items():
        a, b = set(tablas_json[t][k]), set(tablas_csv[t][k])
        if a != b:
            difs.append({"tabla": t, "solo_json": sorted(a - b)[:20], "solo_csv": sorted(b - a)[:20]})
    return difs