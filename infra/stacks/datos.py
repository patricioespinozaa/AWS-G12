"""Datos: bucket S3 (CSV, Parquet, historial, KB), workgroup de Athena y RDS PostgreSQL opcional.

Equivale a db/infra/crear_s3_athena.sh y crear_rds.sh, pero como código y con RDS privada (subred aislada):
la carga de RDS se hace con una tarea ECS dentro de la VPC (ver infra/README.md), no desde internet.
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

from config.entornos import Entorno

from .red import RedStack


class DatosStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, red: RedStack, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: datos (S3, Athena, RDS)", **kwargs)
        retener = entorno.retener_datos

        self.bucket = s3.Bucket(
            self, "Datos",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            bucket_key_enabled=True,
            enforce_ssl=True,
            versioned=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            lifecycle_rules=[
                s3.LifecycleRule(id="resultados-athena-7-dias", prefix="athena-resultados/",
                                 expiration=Duration.days(7)),
                s3.LifecycleRule(id="versiones-antiguas-30-dias", noncurrent_version_expiration=Duration.days(30)),
            ],
            removal_policy=RemovalPolicy.RETAIN if retener else RemovalPolicy.DESTROY,
            auto_delete_objects=not retener,
            # F0012: el navegador sube el examen directo a S3 con un POST prefirmado (firma, tipo y tamaño acotados)
            cors=[s3.CorsRule(allowed_methods=[s3.HttpMethods.POST], allowed_origins=["https://*"],
                              allowed_headers=["*"], max_age=300)],
        )

        # F0012: un archivo que GuardDuty marcó con amenaza no se puede descargar (ni para leerlo)
        self.bucket.add_to_resource_policy(iam.PolicyStatement(
            sid="SinDescargaDeArchivosConAmenaza", effect=iam.Effect.DENY, principals=[iam.AnyPrincipal()],
            actions=["s3:GetObject", "s3:GetObjectVersion"], resources=[self.bucket.arn_for_objects("*")],
            conditions={"StringEquals": {"s3:ExistingObjectTag/GuardDutyMalwareScanStatus": "THREATS_FOUND"}}))

        self.workgroup = athena.CfnWorkGroup(
            self, "WorkGroup",
            name=entorno.workgroup,
            description="Consultas del proyecto HLF (hlf_raw e hlf_historial)",
            recursive_delete_option=not retener,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                bytes_scanned_cutoff_per_query=entorno.athena_limite_bytes,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(selected_engine_version="AUTO"),
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.bucket.bucket_name}/athena-resultados/",
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_S3")),
            ),
        )

        self.rds: rds.DatabaseInstance | None = None
        if entorno.crear_rds:
            self.rds = rds.DatabaseInstance(
                self, "Postgres",
                engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
                instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO),
                vpc=red.vpc,
                vpc_subnets=red.subredes_datos,
                security_groups=[red.sg_rds],
                credentials=rds.Credentials.from_generated_secret("hlf_admin"),
                database_name="hlf",
                allocated_storage=20,
                max_allocated_storage=50,
                storage_type=rds.StorageType.GP3,
                storage_encrypted=True,
                publicly_accessible=False,
                multi_az=False,
                backup_retention=Duration.days(7 if retener else 1),
                deletion_protection=retener,
                removal_policy=RemovalPolicy.SNAPSHOT if retener else RemovalPolicy.DESTROY,
                cloudwatch_logs_exports=["postgresql"],
                cloudwatch_logs_retention=logs.RetentionDays.ONE_MONTH,
                auto_minor_version_upgrade=True,
            )
            CfnOutput(self, "RdsHost", value=self.rds.db_instance_endpoint_address,
                      description="HLF_DB_HOST")
            CfnOutput(self, "RdsSecreto", value=self.rds.secret.secret_arn,
                      description="HLF_DB_SECRET_ID (usuario y clave en Secrets Manager)")

        CfnOutput(self, "Bucket", value=self.bucket.bucket_name, description="HLF_S3_BUCKET")
        CfnOutput(self, "AthenaWorkGroup", value=self.workgroup.name, description="HLF_ATHENA_WORKGROUP")
