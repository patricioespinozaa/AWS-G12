"""Asistente del paciente (F0010): cifrado de teléfonos, secretos, entrada de WhatsApp y Lambda.

- **KMS**: clave propia para los teléfonos (canal.contacto_paciente.valor_cifrado), con rotación anual.
- **Secrets Manager**: el *pepper* del HMAC de los teléfonos y el secreto de servicio con que la Lambda de WhatsApp se
  autentica ante la API (cabecera X-HLF-Servicio). Ambos generados por AWS, nunca en el repositorio.
- **SNS**: tema donde AWS End User Messaging Social publica los mensajes entrantes de WhatsApp.
- **Lambda** (sin VPC, sin dependencias): SNS → API (`/api/interno/asistente/whatsapp`) → SendWhatsAppMessage. El núcleo
  del asistente corre en la API, que tiene la conexión a RDS; así la Lambda no necesita estar en la VPC ni endpoints
  privados. La URL de la API la lee de SSM (la escribe FrontendStack).
El número de WhatsApp se vincula fuera de CDK (cuenta de Meta en la consola de End User Messaging Social) y se
configura en `whatsapp_origen` (infra/config/entornos.py). Mientras tanto, el simulador de la app cubre la demo.

Exámenes externos (F0012): clave KMS propia para los archivos (`canal/evidencias/`) y, con `examenes_guardduty`,
GuardDuty Malware Protection for S3 sobre ese prefijo. El resultado del escaneo llega por EventBridge a una Lambda
que avisa a la API: solo un archivo limpio se lee con Textract y Claude.
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_guardduty as guardduty
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as eventos
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from constructs import Construct

from config.entornos import Entorno

from .datos import DatosStack

RAIZ = Path(__file__).resolve().parents[2]


class AsistenteStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, datos: DatosStack, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: asistente del paciente (WhatsApp, cifrado, secretos)",
                         **kwargs)
        retencion = RemovalPolicy.RETAIN if entorno.retener_datos else RemovalPolicy.DESTROY
        self.clave = kms.Key(self, "ClaveTelefonos", alias=f"alias/hlf-{entorno.nombre}-telefonos",
                             description="Cifrado de los teléfonos de los pacientes (canal.contacto_paciente)",
                             enable_key_rotation=True, removal_policy=retencion)
        self.pepper = secretsmanager.Secret(
            self, "PepperHmac", description="Pepper del HMAC de los teléfonos de los pacientes (F0010)",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=48),
            removal_policy=retencion)
        self.secreto_servicio = secretsmanager.Secret(
            self, "SecretoServicio", description="Autenticación de la Lambda de WhatsApp ante la API (X-HLF-Servicio)",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=48))
        self.parametro_api = f"/hlf/{entorno.nombre}/api_url"

        self.tema = sns.Topic(self, "WhatsAppEntrante", display_name="HLF WhatsApp entrante",
                              enforce_ssl=True)
        self.tema.add_to_resource_policy(iam.PolicyStatement(
            actions=["sns:Publish"], resources=[self.tema.topic_arn],
            principals=[iam.ServicePrincipal("social-messaging.amazonaws.com")],
            conditions={"StringEquals": {"aws:SourceAccount": self.account}}))

        self.funcion = lambda_.Function(
            self, "LambdaWhatsApp",
            description="WhatsApp → API del asistente → SendWhatsAppMessage (F0010)",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_whatsapp.handler",
            code=lambda_.Code.from_asset(str(RAIZ / "servicios" / "asistente"),
                                         exclude=["*", "!lambda_whatsapp.py"]),
            timeout=Duration.seconds(60),
            memory_size=256,
            log_retention=logs.RetentionDays.ONE_MONTH if entorno.dias_logs >= 30 else logs.RetentionDays.ONE_WEEK,
            environment={"HLF_SERVICIO_SECRET_ID": self.secreto_servicio.secret_arn,
                         "HLF_API_PARAMETRO": self.parametro_api,
                         "HLF_WHATSAPP_ORIGEN": entorno.whatsapp_origen},
        )
        self.funcion.add_event_source(eventos.SnsEventSource(self.tema))
        self.secreto_servicio.grant_read(self.funcion)
        self.funcion.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name=self.parametro_api.lstrip("/"))]))
        self.funcion.add_to_role_policy(iam.PolicyStatement(
            actions=["social-messaging:SendWhatsAppMessage"],
            resources=[self.format_arn(service="social-messaging", resource="phone-number-id", resource_name="*")]))

        # -- Exámenes externos (F0012) -------------------------------------------------------------------------
        self.prefijo_evidencias = f"{entorno.prefijo_s3}/canal/evidencias/"
        self.clave_examenes = kms.Key(self, "ClaveExamenes", alias=f"alias/hlf-{entorno.nombre}-examenes",
                                      description="Cifrado de los exámenes externos (canal/evidencias)",
                                      enable_key_rotation=True, removal_policy=retencion)
        self.con_escaneo = entorno.examenes_guardduty
        if self.con_escaneo:
            rol = iam.Role(self, "RolMalware", description="GuardDuty Malware Protection for S3 (exámenes externos)",
                           assumed_by=iam.ServicePrincipal("malware-protection-plan.guardduty.amazonaws.com"))
            bucket_arn = datos.bucket.bucket_arn
            rol.add_to_policy(iam.PolicyStatement(
                actions=["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets",
                         "events:DescribeRule", "events:ListTargetsByRule"],
                resources=[self.format_arn(service="events", resource="rule",
                                           resource_name="DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*")],
                conditions={"StringLike": {"events:ManagedBy": "malware-protection-plan.guardduty.amazonaws.com"}}))
            rol.add_to_policy(iam.PolicyStatement(
                actions=["s3:PutObjectTagging", "s3:GetObjectTagging", "s3:PutObjectVersionTagging",
                         "s3:GetObjectVersionTagging", "s3:GetObject", "s3:GetObjectVersion"],
                resources=[f"{bucket_arn}/{self.prefijo_evidencias}*"]))
            rol.add_to_policy(iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[f"{bucket_arn}/malware-protection-resource-validation-object"]))
            rol.add_to_policy(iam.PolicyStatement(
                actions=["s3:ListBucket", "s3:GetBucketNotification", "s3:PutBucketNotification"],
                resources=[bucket_arn]))
            self.clave_examenes.grant_decrypt(rol)
            plan = guardduty.CfnMalwareProtectionPlan(
                self, "EscaneoExamenes", role=rol.role_arn,
                protected_resource=guardduty.CfnMalwareProtectionPlan.CFNProtectedResourceProperty(
                    s3_bucket=guardduty.CfnMalwareProtectionPlan.S3BucketProperty(
                        bucket_name=datos.bucket.bucket_name, object_prefixes=[self.prefijo_evidencias])),
                actions=guardduty.CfnMalwareProtectionPlan.CFNActionsProperty(
                    tagging=guardduty.CfnMalwareProtectionPlan.CFNTaggingProperty(status="ENABLED")))
            plan.node.add_dependency(rol)
            escaneo = lambda_.Function(
                self, "LambdaEscaneo", description="Resultado del escaneo de exámenes → API (F0012)",
                runtime=lambda_.Runtime.PYTHON_3_12, handler="lambda_escaneo.handler",
                code=lambda_.Code.from_asset(str(RAIZ / "servicios" / "ocr_examenes"), exclude=["*", "!lambda_escaneo.py"]),
                timeout=Duration.seconds(30), memory_size=128,
                log_retention=logs.RetentionDays.ONE_MONTH if entorno.dias_logs >= 30 else logs.RetentionDays.ONE_WEEK,
                environment={"HLF_SERVICIO_SECRET_ID": self.secreto_servicio.secret_arn,
                             "HLF_API_PARAMETRO": self.parametro_api})
            self.secreto_servicio.grant_read(escaneo)
            escaneo.add_to_role_policy(iam.PolicyStatement(
                actions=["ssm:GetParameter"], resources=[self.format_arn(
                    service="ssm", resource="parameter", resource_name=self.parametro_api.lstrip("/"))]))
            events.Rule(self, "ResultadoEscaneo", description="GuardDuty: resultado del escaneo de un examen (F0012)",
                        event_pattern=events.EventPattern(
                            source=["aws.guardduty"], detail_type=["GuardDuty Malware Protection Object Scan Result"],
                            detail={"s3ObjectDetails": {"bucketName": [datos.bucket.bucket_name],
                                                        "objectKey": [{"prefix": self.prefijo_evidencias}]}}),
                        targets=[targets.LambdaFunction(escaneo)])

        CfnOutput(self, "SalidaTemaWhatsApp", value=self.tema.topic_arn,
                  description="Destino de eventos al vincular el número en End User Messaging Social")
        CfnOutput(self, "SalidaClaveTelefonos", value=self.clave.key_arn)

    def otorgar_a(self, rol: iam.IRole, enviar_whatsapp: bool = False, enviar_sms: bool = False) -> None:
        """Permisos de la API y de la tarea nocturna: cifrar y descifrar teléfonos, leer los secretos y, si se pide,
        enviar mensajes (recordatorios) y SMS (códigos de verificación)."""
        self.clave.grant_encrypt_decrypt(rol)
        self.clave_examenes.grant_encrypt_decrypt(rol)              # subida firmada y lectura de exámenes (F0012)
        rol.add_to_principal_policy(iam.PolicyStatement(
            actions=["textract:AnalyzeDocument", "textract:StartDocumentAnalysis", "textract:GetDocumentAnalysis"],
            resources=["*"]))                                        # Textract no admite permisos por recurso
        rol.add_to_principal_policy(iam.PolicyStatement(
            actions=["social-messaging:GetWhatsAppMessageMedia"],
            resources=[self.format_arn(service="social-messaging", resource="phone-number-id", resource_name="*")]))
        self.pepper.grant_read(rol)
        self.secreto_servicio.grant_read(rol)
        if enviar_whatsapp:
            rol.add_to_principal_policy(iam.PolicyStatement(
                actions=["social-messaging:SendWhatsAppMessage"],
                resources=[self.format_arn(service="social-messaging", resource="phone-number-id", resource_name="*")]))
        if enviar_sms:
            rol.add_to_principal_policy(iam.PolicyStatement(
                actions=["sms-voice:SendTextMessage"], resources=["*"]))
