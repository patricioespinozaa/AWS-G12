"""Asistente del paciente por teléfono (F0011): Amazon Connect + Lex V2 (es_US, voz neural de Polly) + Lambda.

- **Lex V2**: reconoce la voz y los dígitos; todas las intenciones (y la de respaldo) van a la Lambda, que llama al
  núcleo del asistente en la API. Lex resuelve la voz y los turnos; Claude (Haiku) solo redacta.
- **Lambda** (sin VPC): Lex → `/api/interno/asistente/voz` → respuesta para Lex. Si la API falla, transfiere.
- **Connect**: instancia, horario, cola humana, flujo entrante (infra/connect/flujo_entrante.json) y grabaciones en el
  bucket de datos SOLO si el paciente lo autoriza en la llamada. El número se reclama con `voz_reclamar_numero`
  (tiene costo diario); los agentes se crean en la consola de Connect.
Región: la misma de la API, Bedrock y la base (us-east-1), sin cruces.
"""
from __future__ import annotations

import json
from pathlib import Path

from aws_cdk import Aws, CfnOutput, Duration, Fn, Stack
from aws_cdk import aws_connect as connect
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lex as lex
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

from config.entornos import Entorno

from .asistente import AsistenteStack
from .datos import DatosStack

RAIZ = Path(__file__).resolve().parents[2]
FLUJO = RAIZ / "infra" / "connect" / "flujo_entrante.json"
LOCALE = "es_US"
VOZ = "Lupe"                       # Polly neural en español
INTENCIONES = {
    "ConsultarEstado": ["en qué lugar voy", "cuál es mi posición en la lista", "cuánto me falta para la atención",
                        "cuánto tengo que esperar", "en qué lugar de la lista estoy"],
    "ConsultarCitas": ["tengo citas", "cuándo es mi próxima cita", "a qué hora es mi hora", "mis citas"],
    "ConfirmarAsistencia": ["confirmo mi asistencia", "sí voy a ir", "confirmo mi hora", "voy a asistir"],
    "NoPuedoAsistir": ["no puedo ir", "no voy a poder asistir", "quiero cancelar mi hora", "no puedo asistir"],
    "ConsultarRegistros": ["qué registros tienen de mí", "qué exámenes tienen", "qué información tiene el hospital"],
    "ReportarSintoma": ["me siento peor", "tengo un síntoma nuevo", "quiero informar un síntoma"],
    "HablarConPersona": ["quiero hablar con una persona", "con un humano", "con alguien del hospital", "operadora"],
    "Saludo": ["hola", "buenos días", "buenas tardes", "aló"],
}


class VozStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, asistente: AsistenteStack, datos: DatosStack,
                 **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: asistente por voz (Connect + Lex)", **kwargs)

        self.funcion = lambda_.Function(
            self, "LambdaVoz", description="Lex V2 → API del asistente → respuesta hablada (F0011)",
            runtime=lambda_.Runtime.PYTHON_3_12, handler="lambda_voz.handler",
            code=lambda_.Code.from_asset(str(RAIZ / "servicios" / "asistente"), exclude=["*", "!lambda_voz.py"]),
            timeout=Duration.seconds(28), memory_size=256,
            log_retention=logs.RetentionDays.ONE_MONTH if entorno.dias_logs >= 30 else logs.RetentionDays.ONE_WEEK,
            environment={"HLF_SERVICIO_SECRET_ID": asistente.secreto_servicio.secret_arn,
                         "HLF_API_PARAMETRO": asistente.parametro_api})
        asistente.secreto_servicio.grant_read(self.funcion)
        self.funcion.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter",
                                       resource_name=asistente.parametro_api.lstrip("/"))]))

        rol_lex = iam.Role(self, "RolLex", assumed_by=iam.ServicePrincipal("lexv2.amazonaws.com"),
                           description="Rol del bot de Lex del asistente (voz de Polly)")
        rol_lex.add_to_policy(iam.PolicyStatement(actions=["polly:SynthesizeSpeech"], resources=["*"]))
        gancho = lex.CfnBot.FulfillmentCodeHookSettingProperty(enabled=True)
        intenciones = [lex.CfnBot.IntentProperty(
            name=n, sample_utterances=[lex.CfnBot.SampleUtteranceProperty(utterance=u) for u in frases],
            fulfillment_code_hook=gancho) for n, frases in INTENCIONES.items()]
        intenciones.append(lex.CfnBot.IntentProperty(name="FallbackIntent", parent_intent_signature="AMAZON.FallbackIntent",
                                                     fulfillment_code_hook=gancho))
        self.bot = lex.CfnBot(
            self, "Bot", name=f"hlf-asistente-{entorno.nombre}", role_arn=rol_lex.role_arn,
            data_privacy={"ChildDirected": False}, idle_session_ttl_in_seconds=300, auto_build_bot_locales=True,
            description="Asistente del paciente en lista de espera (F0011). El texto lo redacta el núcleo del asistente",
            bot_locales=[lex.CfnBot.BotLocaleProperty(
                locale_id=LOCALE, nlu_confidence_threshold=0.40, intents=intenciones,
                voice_settings=lex.CfnBot.VoiceSettingsProperty(voice_id=VOZ, engine="neural"))])
        version = lex.CfnBotVersion(
            self, "BotVersion", bot_id=self.bot.attr_id,
            bot_version_locale_specification=[lex.CfnBotVersion.BotVersionLocaleSpecificationProperty(
                locale_id=LOCALE, bot_version_locale_details=lex.CfnBotVersion.BotVersionLocaleDetailsProperty(
                    source_bot_version="DRAFT"))])
        self.alias = lex.CfnBotAlias(
            self, "BotAlias", bot_id=self.bot.attr_id, bot_alias_name="connect", bot_version=version.attr_bot_version,
            bot_alias_locale_settings=[lex.CfnBotAlias.BotAliasLocaleSettingsItemProperty(
                locale_id=LOCALE, bot_alias_locale_setting=lex.CfnBotAlias.BotAliasLocaleSettingsProperty(
                    enabled=True, code_hook_specification=lex.CfnBotAlias.CodeHookSpecificationProperty(
                        lambda_code_hook=lex.CfnBotAlias.LambdaCodeHookProperty(
                            code_hook_interface_version="1.0", lambda_arn=self.funcion.function_arn))))])
        self.funcion.add_permission("InvocadaPorLex", principal=iam.ServicePrincipal("lexv2.amazonaws.com"),
                                    source_arn=self.alias.attr_arn)

        # Connect: instancia, horario, cola humana, grabaciones (solo con consentimiento) y flujo entrante
        self.instancia = connect.CfnInstance(
            self, "Connect", identity_management_type="CONNECT_MANAGED",
            instance_alias=f"hlf-{entorno.nombre}-{Aws.ACCOUNT_ID}",
            attributes=connect.CfnInstance.AttributesProperty(inbound_calls=True, outbound_calls=False,
                                                              contactflow_logs=True, contact_lens=False))
        connect.CfnInstanceStorageConfig(
            self, "Grabaciones", instance_arn=self.instancia.attr_arn, resource_type="CALL_RECORDINGS",
            storage_type="S3", s3_config=connect.CfnInstanceStorageConfig.S3ConfigProperty(
                bucket_name=datos.bucket.bucket_name, bucket_prefix=f"{entorno.prefijo_s3}/connect/grabaciones"))
        connect.CfnIntegrationAssociation(self, "LexEnConnect", instance_id=self.instancia.attr_arn,
                                          integration_type="LEX_BOT", integration_arn=self.alias.attr_arn)
        horario = connect.CfnHoursOfOperation(
            self, "Horario", instance_arn=self.instancia.attr_arn, name="Policlínico de especialidades",
            time_zone="America/Santiago",
            config=[connect.CfnHoursOfOperation.HoursOfOperationConfigProperty(
                day=d, start_time={"hours": 8, "minutes": 0}, end_time={"hours": 17, "minutes": 0})
                for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")])
        self.cola = connect.CfnQueue(self, "ColaHumana", instance_arn=self.instancia.attr_arn,
                                     hours_of_operation_arn=horario.attr_hours_of_operation_arn,
                                     name="Atención a pacientes", description="Derivaciones del asistente (F0011)")
        contenido = Fn.sub(json.dumps(json.loads(FLUJO.read_text(encoding="utf-8")), ensure_ascii=False),
                           {"LexAliasArn": self.alias.attr_arn, "ColaArn": self.cola.attr_queue_arn})
        self.flujo = connect.CfnContactFlow(self, "FlujoEntrante", instance_arn=self.instancia.attr_arn,
                                            name="HLF entrante", type="CONTACT_FLOW", content=contenido,
                                            description="Consentimiento de grabación → asistente → persona (F0011)")

        if entorno.voz_reclamar_numero:
            numero = connect.CfnPhoneNumber(self, "Numero", target_arn=self.instancia.attr_arn,
                                            country_code=entorno.voz_pais, type="DID",
                                            description="Número del asistente del paciente (F0011)")
            llamada = cr.AwsSdkCall(
                service="Connect", action="associatePhoneNumberContactFlow",
                parameters={"PhoneNumberId": numero.attr_phone_number_arn, "InstanceId": self.instancia.attr_id,
                            "ContactFlowId": self.flujo.attr_contact_flow_arn},
                physical_resource_id=cr.PhysicalResourceId.of("numero-flujo"))
            cr.AwsCustomResource(self, "NumeroAlFlujo", on_create=llamada, on_update=llamada,
                                 policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                                     resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE),
                                 install_latest_aws_sdk=False)
            CfnOutput(self, "SalidaNumero", value=numero.attr_address)

        CfnOutput(self, "SalidaInstanciaConnect", value=self.instancia.attr_arn)
        CfnOutput(self, "SalidaBotLex", value=self.alias.attr_arn)
