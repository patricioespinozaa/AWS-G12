import json
from config import SALT_PSEUDONIMO
from datos import Repositorio
from copiloto import analizar_alerta
import auditoria

repo = Repositorio(salt=SALT_PSEUDONIMO)

# Esta alerta la genera el MOTOR DE REGLAS del software, no la IA
alerta = {
    "alerta_id": "ALR-000123",
    "regla": "R-CARD-01: urgencia por dolor torácico durante espera de cardiología",
    "sic_id": "SIC-2024-08812",
    "pid": repo.t["sic"].iloc[0]["pid"],     # en producción viene del evento
    "especialidad_destino": "Cardiología",
    "prioridad_actual": "media",
    "dias_en_espera": 187,
    "evento_disparador": {"registro_id": "urgencias:45", "fuente": "urgencias"},
}

analisis = analizar_alerta(repo, alerta)
print(json.dumps(analisis, ensure_ascii=False, indent=2))

# Luego, desde la bandeja de revisión:
auditoria.registrar_decision_medica(
    alerta_id="ALR-000123", medico_id="MED-017",
    decision="aceptada", prioridad_final="alta",
    comentario="Se agenda cita en 7 días y ECG previo.",
)