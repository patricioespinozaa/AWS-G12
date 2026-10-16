"""Consolidación nocturna (F0006): EventBridge Scheduler lanza cada noche una tarea ECS con la misma imagen del
backend y el comando `python -m servicios.nocturno`.

La tarea revisa el buzón (s3://<bucket>/<prefijo>/entrada/<carpeta>/), suma las exportaciones nuevas a raw y
consolida el histórico (serie nocturna, propuestas, estimación). Al terminar publica en S3 el Parquet de raw y
las noches tocadas del historial, que Athena lee sin DDL (partition projection).

Es un construct dentro de BackendStack (no un stack aparte): comparte cluster, imagen y red sin referencias
entre stacks. Solo existe con RDS: sin base no hay versiones ni histórico que consolidar.
"""
from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

# 02:00 en Chile: después del cierre del día y antes de que la Administradora abra la bandeja
HORARIO = "cron(0 2 * * ? *)"
ZONA_HORARIA = "America/Santiago"
COMANDO = ["python", "-m", "servicios.nocturno"]
# Donde escribe la tarea, además de leer todo el prefijo: la copia de consulta y el historial para Athena
PREFIJOS_ESCRITURA = ("parquet", "historial")


class ConsolidacionNocturna(Construct):
    def __init__(self, scope: Construct, id: str, *, cluster: ecs.ICluster, imagen: ecs.ContainerImage,
                 variables: dict[str, str], bucket: s3.IBucket, prefijo_s3: str, secreto_db, grupo_logs: logs.ILogGroup,
                 subredes: list[str], security_group: ec2.ISecurityGroup, ip_publica: bool,
                 cpu: int, memoria_mib: int) -> None:
        super().__init__(scope, id)

        self.tarea = ecs.FargateTaskDefinition(
            self, "Tarea", cpu=cpu, memory_limit_mib=memoria_mib,
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.X86_64,
                                                 operating_system_family=ecs.OperatingSystemFamily.LINUX),
        )
        self.tarea.add_container(
            "nocturno",
            image=imagen,
            command=COMANDO,
            environment={**variables, "HLF_AUTOCONFIRMAR": "1", "HLF_ATHENA_PUBLICAR": "1"},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="nocturno", log_group=grupo_logs),
        )
        secreto_db.grant_read(self.tarea.task_role)
        bucket.grant_read(self.tarea.task_role, f"{prefijo_s3}/*")
        for prefijo in PREFIJOS_ESCRITURA:
            bucket.grant_put(self.tarea.task_role, f"{prefijo_s3}/{prefijo}/*")

        # Rol con el que EventBridge Scheduler lanza la tarea: RunTask de esta definición y PassRole de sus roles
        rol = iam.Role(self, "RolScheduler", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"))
        rol.add_to_policy(iam.PolicyStatement(
            actions=["ecs:RunTask"], resources=[self.tarea.task_definition_arn],
            conditions={"ArnLike": {"ecs:cluster": cluster.cluster_arn}}))
        rol.add_to_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[self.tarea.task_role.role_arn, self.tarea.obtain_execution_role().role_arn]))

        self.programacion = scheduler.CfnSchedule(
            self, "Programacion",
            description="HLF: consolidación nocturna (buzón → raw → histórico → Athena)",
            schedule_expression=HORARIO,
            schedule_expression_timezone=ZONA_HORARIA,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=cluster.cluster_arn,
                role_arn=rol.role_arn,
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=2,
                                                                        maximum_event_age_in_seconds=3600),
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=self.tarea.task_definition_arn,
                    launch_type="FARGATE",
                    task_count=1,
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=subredes, security_groups=[security_group.security_group_id],
                            assign_public_ip="ENABLED" if ip_publica else "DISABLED")),
                ),
            ),
        )
