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
from aws_cdk import aws_logs as logs
from constructs import Construct

from config.entornos import Entorno

from .datos import DatosStack
from .red import RedStack

RAIZ = Path(__file__).resolve().parents[2]
# Además de .dockerignore: lo que nunca debe copiarse al asset (cdk.out) aunque alguien edite ese archivo
EXCLUIR_DEL_ASSET = ["data", "**/*.csv", "**/*.sqlite", ".git", "web", "infra", "notebooks", "docs", "**/node_modules"]
# El primer arranque recalcula la serie nocturna completa (ver infra/README.md, "Primer arranque")
GRACIA_ARRANQUE = Duration.minutes(6)


class BackendStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, red: RedStack, datos: DatosStack,
                 **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: backend (ECS Fargate + ALB interno)", **kwargs)

        cluster = ecs.Cluster(self, "Cluster", vpc=red.vpc, container_insights_v2=ecs.ContainerInsights.ENABLED)
        grupo_logs = logs.LogGroup(self, "Logs", retention=_retencion(entorno.dias_logs),
                                   removal_policy=RemovalPolicy.DESTROY)

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
        }
        if entorno.bedrock_model_id:
            variables["BEDROCK_MODEL_ID"] = entorno.bedrock_model_id
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
        for prefijo in ("canal/evidencias", "cargas"):
            datos.bucket.grant_put(tarea.task_role, f"{entorno.prefijo_s3}/{prefijo}/*")
        con_estado_en_base = datos.rds is not None

        servicio = ecs.FargateService(
            self, "Servicio",
            cluster=cluster,
            task_definition=tarea,
            desired_count=2 if con_estado_en_base else 1,
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
        escucha.add_targets(
            "Api",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[servicio],
            deregistration_delay=Duration.seconds(30),
            health_check=elbv2.HealthCheck(path="/api/meta", healthy_http_codes="200",
                                           interval=Duration.seconds(30), timeout=Duration.seconds(10),
                                           healthy_threshold_count=2, unhealthy_threshold_count=5),
        )

        # Lo que necesita `aws ecs run-task` para correr comandos puntuales (p. ej. python -m db restaurar)
        subredes = red.vpc.select_subnets(subnet_type=red.tipo_subred_backend).subnet_ids
        CfnOutput(self, "SalidaCluster", value=cluster.cluster_name)
        CfnOutput(self, "SalidaServicio", value=servicio.service_name)
        CfnOutput(self, "SalidaDefinicionTarea", value=tarea.task_definition_arn)
        CfnOutput(self, "SalidaSubredes", value=",".join(subredes))
        CfnOutput(self, "SalidaSecurityGroup", value=red.sg_backend.security_group_id)
        CfnOutput(self, "SalidaIpPublica", value="ENABLED" if red.ip_publica_backend else "DISABLED")
        CfnOutput(self, "SalidaGrupoLogs", value=grupo_logs.log_group_name)


def _retencion(dias: int) -> logs.RetentionDays:
    return {7: logs.RetentionDays.ONE_WEEK, 30: logs.RetentionDays.ONE_MONTH,
            365: logs.RetentionDays.ONE_YEAR}.get(dias, logs.RetentionDays.ONE_MONTH)
