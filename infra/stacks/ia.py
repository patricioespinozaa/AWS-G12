"""IA generativa (F0008): Guardrail de Amazon Bedrock y política IAM de invocación, reutilizables por F0009 y F0010.

Solo IA del ecosistema AWS: el modelo se invoca por Bedrock con la política de este stack (mínimo privilegio: solo el
perfil de inferencia elegido, los modelos base a los que enruta y el guardrail).

El guardrail usa el nivel Standard (evalúa español; el nivel clásico solo inglés), que requiere el perfil de
guardrail entre regiones `us.guardrail.v1:0`. Los temas denegados se aplican solo a la SALIDA: la entrada son los
factores de la propuesta, que contienen legítimamente diagnósticos y cambios de tratamiento.
"""
from __future__ import annotations

import hashlib
import json

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from constructs import Construct

from config.entornos import Entorno

PERFIL_GUARDRAIL = "us.guardrail.v1:0"
MENSAJE_BLOQUEO = "Texto bloqueado por el guardrail: se usa la explicación de plantilla."
# Regiones a las que enruta un perfil "us." (el modelo base debe poder invocarse en cada una)
REGIONES_PERFIL_US = ("us-east-1", "us-east-2", "us-west-2")
FILTROS = ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT")
NIVEL_FILTRO = "MEDIUM"

TEMAS = [
    ("Indicar tratamiento",
     "Recomendar, indicar o sugerir que la persona reciba un tratamiento, fármaco, dosis, examen o procedimiento "
     "médico. Describir un cambio de tratamiento que ya ocurrió y está registrado no es indicar un tratamiento.",
     ["Se recomienda iniciar un betabloqueador.", "Debería aumentar la dosis de sertralina.",
      "Sugiero solicitar una coronariografía."]),
    # Mencionar el diagnóstico ya registrado (p. ej. "angina de pecho, riesgo de infarto") es legítimo: viene en los
    # factores. Lo que se deniega es especular sobre otra enfermedad o sobre la evolución
    ("Especular diagnostico o pronostico",      # el nombre no admite tildes
     "Especular que la persona podría tener una enfermedad distinta de la registrada, o anticipar cómo evolucionará "
     "su salud. Nombrar el diagnóstico registrado en la interconsulta y su riesgo asociado no es especular.",
     ["Es probable que esté cursando un infarto en evolución.", "Podría tratarse de una insuficiencia cardiaca.",
      "Lo más probable es que empeore en las próximas semanas."]),
]


class IaStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: IA generativa en Bedrock (guardrail y permisos)",
                         **kwargs)
        perfil_guardrail = f"arn:aws:bedrock:{self.region}:{self.account}:guardrail-profile/{PERFIL_GUARDRAIL}"
        self.guardrail = bedrock.CfnGuardrail(
            self, "Guardrail",
            name=f"hlf-explicaciones-{entorno.nombre}",
            description="Explicaciones de la priorización: el LLM solo redacta; no diagnostica ni indica tratamientos",
            blocked_input_messaging=MENSAJE_BLOQUEO,
            blocked_outputs_messaging=MENSAJE_BLOQUEO,
            cross_region_config=bedrock.CfnGuardrail.GuardrailCrossRegionConfigProperty(
                guardrail_profile_arn=perfil_guardrail),
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                content_filters_tier_config=bedrock.CfnGuardrail.ContentFiltersTierConfigProperty(tier_name="STANDARD"),
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type=t, input_strength="NONE", output_strength=NIVEL_FILTRO, input_enabled=False,
                        output_enabled=True)
                    for t in FILTROS
                ]),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_tier_config=bedrock.CfnGuardrail.TopicsTierConfigProperty(tier_name="STANDARD"),
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(name=n, definition=d, examples=e, type="DENY",
                                                             input_enabled=False, output_enabled=True)
                    for n, d, e in TEMAS
                ]),
        )
        # Una versión por configuración: si cambian los temas o filtros, cambia la huella, CloudFormation reemplaza el
        # recurso y Bedrock publica una versión nueva (la API usa siempre una versión fija, nunca DRAFT)
        huella = hashlib.sha256(json.dumps([TEMAS, FILTROS, NIVEL_FILTRO], ensure_ascii=False).encode()).hexdigest()[:12]
        self.version = bedrock.CfnGuardrailVersion(
            self, "GuardrailVersion", guardrail_identifier=self.guardrail.attr_guardrail_id,
            description=f"Configuración {huella}")

        # Política de invocación: el perfil de inferencia elegido, sus modelos base y el guardrail
        # El modelo de la app (explicaciones, consulta) y el del asistente del paciente (F0010, más rápido)
        recursos = []
        for modelo in dict.fromkeys(m for m in (entorno.bedrock_model_id, entorno.asistente_modelo_id) if m):
            if not entorno.bedrock_model_id:
                break
            recursos.append(self.format_arn(service="bedrock", resource="inference-profile", resource_name=modelo))
            base = modelo.split(".", 1)[1] if modelo.split(".")[0] in ("us", "eu", "apac", "global") else modelo
            recursos += [f"arn:aws:bedrock:{r}::foundation-model/{base}" for r in REGIONES_PERFIL_US]
        self.politica = iam.ManagedPolicy(
            self, "PoliticaInvocacion",
            description="Invocar el modelo de las explicaciones (F0008) y aplicar su guardrail",
            statements=[s for s in (
                iam.PolicyStatement(sid="InvocarModelo", actions=["bedrock:InvokeModel"], resources=recursos)
                if recursos else None,
                iam.PolicyStatement(sid="AplicarGuardrail", actions=["bedrock:ApplyGuardrail"],
                                    resources=[self.guardrail.attr_guardrail_arn,
                                               f"arn:aws:bedrock:*:{self.account}:guardrail-profile/{PERFIL_GUARDRAIL}"]),
            ) if s is not None],
        )

        CfnOutput(self, "SalidaGuardrail", value=self.guardrail.attr_guardrail_id)
        CfnOutput(self, "SalidaGuardrailVersion", value=self.version.attr_version)
