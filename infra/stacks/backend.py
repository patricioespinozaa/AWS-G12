"""Backend: la API FastAPI en ECS Fargate detrás de un ALB interno (solo CloudFront llega a él).

La imagen se construye desde docker/backend/Dockerfile al desplegar (requiere Docker en la máquina o en CI).
- Con RDS (entorno demo, F0005): el estado vive en la base, así que corren 2 tareas y el despliegue no tiene
  corte (las nuevas arrancan antes de que se detengan las anteriores). Las tareas se sincronizan por la versión
  que guarda la base.
- Sin RDS (dev): la API guarda estado en SQLite dentro del contenedor; corre una sola tarea y el despliegue la
  reemplaza con corte, para que nunca haya dos copias escribiendo.
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, IgnoreMode, RemovalPolicy, Stack
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from constructs import Construct

from config.entornos import Entorno

from .datos import DatosStack
from .asistente import AsistenteStack
from .consulta import ConsultaStack
from .ia import IaStack
from .nocturno import ConsolidacionNocturna
from .comun import retencion
from .red import RedStack

RAIZ = Path(__file__).resolve().parents[2]
# Además de .dockerignore: lo que nunca debe copiarse al asset (cdk.out) aunque alguien edite ese archivo
EXCLUIR_DEL_ASSET = ["data", "**/*.csv", "**/*.sqlite", ".git", "web", "infra", "notebooks", "docs", "**/node_modules"]
# El primer arranque recalcula la serie nocturna completa (ver infra/README.md, "Primer arranque")
GRACIA_ARRANQUE = Duration.minutes(6)


class BackendStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, red: RedStack, datos: DatosStack,
                 ia: IaStack | None = None, consulta: ConsultaStack | None = None,
                 asistente: AsistenteStack | None = None, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: backend (ECS Fargate + ALB interno)", **kwargs)

        cluster = ecs.Cluster(self, "Cluster", vpc=red.vpc, container_insights_v2=ecs.ContainerInsights.ENABLED)
        clave_logs = None
        if entorno.cmk:                    # F0013: logs con clave propia en el entorno con datos reales
            clave_logs = kms.Key(self, "ClaveLogs", alias=f"alias/hlf-{entorno.nombre}-logs", enable_key_rotation=True,
                                 description="Logs del backend (F0013)")
            clave_logs.add_to_resource_policy(iam.PolicyStatement(
                principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
                actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
                resources=["*"],
                conditions={"ArnLike": {"kms:EncryptionContext:aws:logs:arn":
                                        f"arn:aws:logs:{self.region}:{self.account}:log-group:*"}}))
        grupo_logs = logs.LogGroup(self, "Logs", retention=retencion(entorno.dias_logs), encryption_key=clave_logs,
                                   removal_policy=RemovalPolicy.RETAIN if entorno.retener_datos else RemovalPolicy.DESTROY)
        self.cluster, self.grupo_logs = cluster, grupo_logs

        tarea = ecs.FargateTaskDefinition(
            self, "Tarea",
            cpu=entorno.backend_cpu,
            memory_limit_mib=entorno.backend_memoria_mib,
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.X86_64,
                                                 operating_system_family=ecs.OperatingSystemFamily.LINUX),
        )
        imagen = ecs.ContainerImage.from_asset(
            str(RAIZ),
            file="docker/backend/Dockerfile",
            platform=ecr_assets.Platform.LINUX_AMD64,
            ignore_mode=IgnoreMode.DOCKER,
            exclude=EXCLUIR_DEL_ASSET,
        )

        variables = {
            "HLF_S3_BUCKET": datos.bucket.bucket_name,
            "HLF_S3_PREFIJO": entorno.prefijo_s3,
            "HLF_ATHENA_WORKGROUP": datos.workgroup.name,
            "AWS_REGION": self.region,
            "LLM_PROVEEDOR": entorno.llm_proveedor,
            # Login de la Administradora (F0007): la API lee el User Pool y el app client de este parámetro
            "HLF_COGNITO_PARAMETRO": entorno.parametro_cognito,
        }
        if entorno.bedrock_model_id:
            variables["BEDROCK_MODEL_ID"] = entorno.bedrock_model_id
        if entorno.llm_proveedor == "bedrock" and ia is not None:
            # Explicaciones con IA (F0008): solo Bedrock, con el guardrail en una versión fija
            variables.update(BEDROCK_GUARDRAIL_ID=ia.guardrail.attr_guardrail_id,
                             BEDROCK_GUARDRAIL_VERSION=ia.version.attr_version)
        # Consulta en lenguaje natural (F0009): la KB del equipo clínico (la API la consulta; la noche la sincroniza)
        con_consulta = entorno.llm_proveedor == "bedrock" and consulta is not None and datos.rds is not None
        if con_consulta:
            variables.update(HLF_KB_ID=consulta.kb.attr_knowledge_base_id,
                             HLF_KB_DATA_SOURCE_ID=consulta.fuente.attr_data_source_id,
                             HLF_KB_PACIENTE_ID=consulta.kb_paciente.attr_knowledge_base_id,
                             HLF_KB_PACIENTE_DATA_SOURCE_ID=consulta.fuente_paciente.attr_data_source_id)
        # Asistente del paciente (F0010): teléfonos cifrados con KMS, HMAC con pepper y entrada de WhatsApp
        con_asistente = con_consulta and asistente is not None
        if con_asistente:
            variables.update(HLF_KMS_KEY_ID=asistente.clave.key_arn, HLF_HMAC_SECRET_ID=asistente.pepper.secret_arn,
                             HLF_SERVICIO_SECRET_ID=asistente.secreto_servicio.secret_arn,
                             HLF_ASISTENTE_MODELO_ID=entorno.asistente_modelo_id,
                             HLF_ESTIMACION_PUBLICABLE="1" if entorno.estimacion_publicable else "0",
                             HLF_EXAMENES_KMS_KEY_ID=asistente.clave_examenes.key_arn,
                             HLF_EXAMENES_ESCANEO="1" if asistente.con_escaneo else "0")
            if entorno.whatsapp_origen:
                variables["HLF_WHATSAPP_ORIGEN"] = entorno.whatsapp_origen
            if entorno.sms_origen:
                variables["HLF_SMS_ORIGEN"] = entorno.sms_origen
        if datos.rds is not None:
            # db/conexion.py arma la conexión con el secreto de Secrets Manager; la clave nunca va en variables
            variables.update(HLF_DB_HOST=datos.rds.db_instance_endpoint_address,
                             HLF_DB_SECRET_ID=datos.rds.secret.secret_arn,
                             HLF_DB_NAME="hlf")
            datos.rds.secret.grant_read(tarea.task_role)

        tarea.add_container(
            "api",
            image=imagen,
            environment=variables,
            port_mappings=[ecs.PortMapping(container_port=8000)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="api", log_group=grupo_logs),
        )
        # Lectura del prefijo del proyecto (CSV publicados, manifiesto, originales de las cargas) y escritura solo
        # donde la app guarda archivos: exámenes del canal y CSV de las cargas por periodo (F0005)
        datos.bucket.grant_read(tarea.task_role, f"{entorno.prefijo_s3}/*")
        if entorno.llm_proveedor == "bedrock" and ia is not None:
            tarea.task_role.add_managed_policy(ia.politica)
        if con_asistente:
            asistente.otorgar_a(tarea.task_role, enviar_sms=bool(entorno.sms_origen))
        if con_consulta:
            tarea.task_role.add_managed_policy(consulta.politica_consulta)
            tarea.task_role.add_managed_policy(consulta.politica_preparacion)   # botón "Sincronizar" de la vista
        tarea.task_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter",
                                       resource_name=entorno.parametro_cognito.lstrip("/"))]))
        for prefijo in ("canal/evidencias", "cargas"):
            datos.bucket.grant_put(tarea.task_role, f"{entorno.prefijo_s3}/{prefijo}/*")
        con_estado_en_base = datos.rds is not None
        self.tareas_deseadas = 2 if con_estado_en_base else 1

        servicio = ecs.FargateService(
            self, "Servicio",
            cluster=cluster,
            task_definition=tarea,
            desired_count=self.tareas_deseadas,
            min_healthy_percent=100 if con_estado_en_base else 0,
            max_healthy_percent=200 if con_estado_en_base else 100,
            assign_public_ip=red.ip_publica_backend,
            vpc_subnets=red.subredes_backend,
            security_groups=[red.sg_backend],
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            health_check_grace_period=GRACIA_ARRANQUE,
        )

        self.alb = elbv2.ApplicationLoadBalancer(
            self, "Alb",
            vpc=red.vpc,
            internet_facing=False,
            vpc_subnets=red.subredes_alb,
            security_group=red.sg_alb,
            idle_timeout=Duration.seconds(120),
            drop_invalid_header_fields=True,
        )
        escucha = self.alb.add_listener("Http", port=80, open=False)
        self.servicio = servicio
        self.objetivo = escucha.add_targets(
            "Api",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[servicio],
            deregistration_delay=Duration.seconds(30),
            # /api/salud: la única ruta sin sesión, y no devuelve datos (F0007)
            health_check=elbv2.HealthCheck(path="/api/salud", healthy_http_codes="200",
                                           interval=Duration.seconds(30), timeout=Duration.seconds(10),
                                           healthy_threshold_count=2, unhealthy_threshold_count=5),
        )

        # Lo que necesita `aws ecs run-task` para correr comandos puntuales (p. ej. python -m db restaurar)
        subredes = red.vpc.select_subnets(subnet_type=red.tipo_subred_backend).subnet_ids

        # Consolidación nocturna (F0006): solo con RDS, que es donde viven las versiones y el histórico
        self.nocturno: ConsolidacionNocturna | None = None
        if datos.rds is not None:
            self.nocturno = ConsolidacionNocturna(
                self, "Nocturno", cluster=cluster, imagen=imagen, variables=variables, bucket=datos.bucket,
                prefijo_s3=entorno.prefijo_s3, secreto_db=datos.rds.secret, grupo_logs=grupo_logs,
                subredes=subredes, security_group=red.sg_backend, ip_publica=red.ip_publica_backend,
                cpu=entorno.backend_cpu, memoria_mib=entorno.backend_memoria_mib)
            CfnOutput(self, "SalidaTareaNocturna", value=self.nocturno.tarea.task_definition_arn)
            if con_consulta:                               # la noche regenera la KB cuando entran datos nuevos
                self.nocturno.tarea.task_role.add_managed_policy(consulta.politica_preparacion)
            if con_asistente:                              # y envía los recordatorios de cita (F0010)
                asistente.otorgar_a(self.nocturno.tarea.task_role, enviar_whatsapp=bool(entorno.whatsapp_origen))
        CfnOutput(self, "SalidaCluster", value=cluster.cluster_name)
        CfnOutput(self, "SalidaServicio", value=servicio.service_name)
        CfnOutput(self, "SalidaDefinicionTarea", value=tarea.task_definition_arn)
        CfnOutput(self, "SalidaSubredes", value=",".join(subredes))
        CfnOutput(self, "SalidaSecurityGroup", value=red.sg_backend.security_group_id)
        CfnOutput(self, "SalidaIpPublica", value="ENABLED" if red.ip_publica_backend else "DISABLED")
        CfnOutput(self, "SalidaGrupoLogs", value=grupo_logs.log_group_name)

