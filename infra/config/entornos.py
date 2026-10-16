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
    # Voz (F0011): instancia de Connect y bot de Lex. Reclamar el número tiene costo diario: se activa a propósito
    voz: bool = False
    voz_reclamar_numero: bool = False
    voz_pais: str = "US"               # números chilenos según disponibilidad de Connect (ver F0011, Riesgos)
    # Identidad (F0007): MFA opcional en la demo; obligatorio con datos reales
    mfa_obligatorio: bool = False

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
                    voz=True),
}


def cargar(nombre: str) -> Entorno:
    if nombre not in ENTORNOS:
        raise ValueError(f"Entorno desconocido: {nombre}. Opciones: {', '.join(ENTORNOS)}")
    return replace(ENTORNOS[nombre],
                   cuenta=os.environ.get("HLF_CUENTA") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
                   region=os.environ.get("HLF_REGION") or os.environ.get("CDK_DEFAULT_REGION"))
