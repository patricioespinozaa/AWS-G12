"""Parámetros por entorno. Los stacks no leen variables de entorno: todo lo configurable pasa por aquí.

Se elige con `cdk deploy -c entorno=demo`. La cuenta y la región salen del perfil de AWS CLI en uso
(CDK_DEFAULT_ACCOUNT y CDK_DEFAULT_REGION), salvo que se definan HLF_CUENTA o HLF_REGION.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Entorno:
    nombre: str
    cuenta: str | None = None
    region: str | None = None
    # Red: 0 NAT = tareas en subred pública con IP pública (más barato, solo datos sintéticos).
    #      1 NAT = tareas en subred privada (obligatorio con datos reales, ver F0013)
    nat_gateways: int = 0
    # Datos
    crear_rds: bool = False            # la app empieza a usar RDS en F0005
    retener_datos: bool = False        # True: buckets con RETAIN y RDS con snapshot al destruir
    prefijo_s3: str = "hlf"
    athena_limite_bytes: int = 1024 ** 3
    # Backend
    backend_cpu: int = 1024            # 1 vCPU
    backend_memoria_mib: int = 3072
    # IA generativa (F0008): solo Amazon Bedrock. Perfil de inferencia permitido en la cuenta del hackatón
    llm_proveedor: str = ""            # "bedrock" activa las explicaciones con IA
    bedrock_model_id: str = ""
    dias_logs: int = 7
    # Asistente del paciente (F0010/F0011). Los números de WhatsApp y SMS se dan de alta fuera de CDK (Meta, AWS End
    # User Messaging); mientras estén vacíos, el simulador de la app cubre la demo
    asistente_modelo_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    whatsapp_origen: str = ""          # phone-number-id-… de End User Messaging Social
    sms_origen: str = ""               # identidad de origen de End User Messaging SMS (códigos de verificación)
    estimacion_publicable: bool = False   # H5 de pendientes.md: solo True con datos sintéticos
    # Exámenes externos (F0012): escaneo de malware con GuardDuty antes de leer cada archivo
    examenes_guardduty: bool = False
    # Voz (F0011): instancia de Connect y bot de Lex. Reclamar el número tiene costo diario: se activa a propósito
    voz: bool = False
    voz_reclamar_numero: bool = False
    voz_pais: str = "US"               # números chilenos según disponibilidad de Connect (ver F0011, Riesgos)
    # Identidad (F0007): MFA opcional en la demo; obligatorio con datos reales
    mfa_obligatorio: bool = False
    # Observabilidad y costos (F0013). El correo de las alarmas sale de HLF_CORREO_ALARMAS (no va en el repo)
    correo_alarmas: str = ""
    presupuesto_usd: int = 0           # 0 = sin presupuesto; alertas al 50, 80 y 100 %
    # Seguridad (F0013). WAF y CloudTrail tienen costo fijo: solo con datos reales (decisión del plan)
    waf: bool = False
    waf_solo_chile: bool = False       # bloqueo geográfico en un piloto
    waf_limite_ip: int = 1000          # peticiones por IP cada 5 minutos
    cloudtrail: bool = False
    cmk: bool = False                  # claves KMS propias para datos (bucket, RDS, Athena) y logs
    dias_respaldo_rds: int = 1         # backups automáticos de RDS
    respaldo: bool = False             # AWS Backup diario de RDS
    respaldo_region_copia: str = ""    # copia del respaldo en otra región
    rotar_secreto_rds: bool = False    # rotación cada 30 días (requiere NAT: la Lambda llama a Secrets Manager)

    @property
    def id(self) -> str:
        return f"Hlf{self.nombre.capitalize()}"

    @property
    def parametro_cognito(self) -> str:
        """Parámetro de SSM con la configuración del login (F0007): lo escribe FrontendStack y lo lee la API."""
        return f"/hlf/{self.nombre}/cognito"

    @property
    def workgroup(self) -> str:
        return f"hlf-priorizacion-{self.nombre}"


ENTORNOS = {
    # Desarrollo: barato y desechable. cdk destroy no deja nada.
    "dev": Entorno("dev"),
    # Demo del hackatón: los datos y la base sobreviven a un destroy accidental.
    "demo": Entorno("demo", crear_rds=True, retener_datos=True, dias_logs=30, llm_proveedor="bedrock",
                    bedrock_model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", estimacion_publicable=True,
                    # GuardDuty: la SCP de la cuenta del hackatón niega CreateMalwareProtectionPlan. Sin escaneo, los
                    # exámenes quedan `sin_escaneo` y se leen igual (datos sintéticos); en piloto es obligatorio
                    # Voz: Connect rechazó el flujo (InvalidContactFlowException) al desplegar; se reactiva al corregirlo
                    voz=False, examenes_guardduty=False, presupuesto_usd=150, dias_respaldo_rds=7),
    # Piloto con datos reales del HLF: todo lo de la lista de verificación de F0013. Sin voz ni estimación publicable
    "piloto": Entorno("piloto", nat_gateways=1, crear_rds=True, retener_datos=True, dias_logs=365,
                      llm_proveedor="bedrock", bedrock_model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                      examenes_guardduty=True, mfa_obligatorio=True, presupuesto_usd=400, waf=True,
                      waf_solo_chile=True, cloudtrail=True, cmk=True, dias_respaldo_rds=35, respaldo=True,
                      respaldo_region_copia="us-west-2", rotar_secreto_rds=True),
}


def cargar(nombre: str) -> Entorno:
    if nombre not in ENTORNOS:
        raise ValueError(f"Entorno desconocido: {nombre}. Opciones: {', '.join(ENTORNOS)}")
    return replace(ENTORNOS[nombre],
                   correo_alarmas=os.environ.get("HLF_CORREO_ALARMAS", ""),
                   cuenta=os.environ.get("HLF_CUENTA") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
                   region=os.environ.get("HLF_REGION") or os.environ.get("CDK_DEFAULT_REGION"))
