import json

from calidad import auditar
from copiloto import analizar_alerta
from datos import Repositorio
from ingesta_json import cargar_perfiles, tablas_desde_perfiles
from reglas import evaluar_paciente

PID, CORTE = "PAC-HLF-00002", "2026-07-08"     # caso §10.6: debe alertar antes de la urgencia

# 1. Carga y validación del contrato oficial
perfiles, cuarentena = cargar_perfiles("perfiles.json")
print(f"Válidos: {len(perfiles)} | En cuarentena: {len(cuarentena)}")
repo = Repositorio(tablas=tablas_desde_perfiles(perfiles, "agenda_box.csv"))

# 2. Calidad de datos
dq = auditar(repo)
print(dq.groupby(["codigo", "nivel"]).size())

# 3. La alerta la genera el MOTOR DE REGLAS, no la IA
r = evaluar_paciente(repo, PID, corte=CORTE)
print(f'{r["prioridad_inicial"]} → {r["prioridad_calculada"]} (score {r["score"]})')
for m in r["motivos"]:
    print(f'  +{m["puntos"]:>5}  {m["motivo"]}  {m["registro_ids"]}')

if r.get("tipo") in ("sin_alerta", "exclusion"):
    raise SystemExit(f"Sin análisis IA: tipo={r.get('tipo')}")


def a_alerta(r: dict) -> dict:
    """Adapta la salida del motor al contrato que exige copiloto.py."""
    alerta = dict(r)
    alerta.setdefault("id_paciente", PID)
    alerta.setdefault("fecha_corte", CORTE)
    alerta.setdefault("alerta_id", f"ALR-{alerta['id_paciente']}-{CORTE.replace('-', '')}")
    faltan = [k for k in ("cie10", "especialidad", "prioridad_calculada") if k not in alerta]
    if faltan:
        raise KeyError(f"evaluar_paciente no entrega {faltan}; ajustar reglas.py o este adaptador")
    return alerta


# 4. Análisis del copiloto: queda en 'pendiente_revision_medica'
analisis = analizar_alerta(repo, a_alerta(r))
print(json.dumps(analisis, ensure_ascii=False, indent=2))

# 5. La decisión médica NO se registra aquí: la toma un médico desde la bandeja.
#    Para probar el flujo, descomentar y usar un ID de profesional real o de prueba:
# import auditoria
# auditoria.registrar_decision_medica(
#     alerta_id=analisis_alerta_id, medico_id="PROF-017", decision="aceptada",
#     prioridad_final="alta", comentario="Cita en 7 días + ECG previo.")