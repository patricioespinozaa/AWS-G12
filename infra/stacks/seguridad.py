"""Seguridad (F0013): WAF en CloudFront, CloudTrail con bloqueo de objetos y AWS Backup de RDS.

Todo se activa por flag en infra/config/entornos.py. WAF y CloudTrail tienen costo fijo: el plan los deja para el
entorno con datos reales (`piloto`). Las claves KMS propias (flag `cmk`) viven en el stack de cada dominio
(datos, logs del backend; el canal ya tiene las suyas desde F0010 y F0012).
"""
from __future__ import annotations

from aws_cdk import Annotations, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_backup as backup
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_events as events
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

from config.entornos import Entorno

from .datos import DatosStack

# Reglas administradas de AWS: (nombre, prioridad, reglas que solo cuentan en vez de bloquear)
REGLAS_ADMINISTRADAS = [
    # SizeRestrictions_BODY bloquea cuerpos > 8 KB: la vista Cargas sube los CSV por la API
    ("AWSManagedRulesCommonRuleSet", 10, ["SizeRestrictions_BODY"]),
    ("AWSManagedRulesKnownBadInputsRuleSet", 20, []),
    ("AWSManagedRulesSQLiRuleSet", 30, []),
]


def nombre_boveda_copia(entorno: Entorno) -> str:
    return f"hlf-{entorno.nombre}-copia"


class RespaldoCopiaStack(Stack):
    """Bóveda de AWS Backup en otra región, destino de la copia diaria de RDS."""

    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: bóveda de respaldo en otra región (F0013)", **kwargs)
        backup.BackupVault(self, "Copia", backup_vault_name=nombre_boveda_copia(entorno),
                           removal_policy=RemovalPolicy.RETAIN)


class SeguridadStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, datos: DatosStack, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: WAF, CloudTrail y respaldo (F0013)", **kwargs)

        # -- WAF en CloudFront ------------------------------------------------------------------------------
        self.web_acl: wafv2.CfnWebACL | None = None
        if entorno.waf:
            if entorno.region and entorno.region != "us-east-1":
                raise ValueError("El WAF de CloudFront se crea en us-east-1: despliega el entorno en esa región "
                                 f"o desactiva `waf` (región actual: {entorno.region})")
            reglas = []
            if entorno.waf_solo_chile:
                reglas.append(wafv2.CfnWebACL.RuleProperty(
                    name="SoloChile", priority=0, action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(not_statement=wafv2.CfnWebACL.NotStatementProperty(
                        statement=wafv2.CfnWebACL.StatementProperty(
                            geo_match_statement=wafv2.CfnWebACL.GeoMatchStatementProperty(country_codes=["CL"])))),
                    visibility_config=_visibilidad("SoloChile")))
            reglas.append(wafv2.CfnWebACL.RuleProperty(
                name="LimitePorIp", priority=5, action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                statement=wafv2.CfnWebACL.StatementProperty(rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                    limit=entorno.waf_limite_ip, aggregate_key_type="IP", evaluation_window_sec=300)),
                visibility_config=_visibilidad("LimitePorIp")))
            for nombre, prioridad, solo_contar in REGLAS_ADMINISTRADAS:
                reglas.append(wafv2.CfnWebACL.RuleProperty(
                    name=nombre, priority=prioridad,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name=nombre,
                            rule_action_overrides=[wafv2.CfnWebACL.RuleActionOverrideProperty(
                                name=r, action_to_use=wafv2.CfnWebACL.RuleActionProperty(count={}))
                                for r in solo_contar] or None)),
                    visibility_config=_visibilidad(nombre)))
            self.web_acl = wafv2.CfnWebACL(
                self, "Waf", name=f"hlf-{entorno.nombre}", scope="CLOUDFRONT",
                description="HLF: reglas administradas, inyección SQL y límite por IP (F0013)",
                default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
                visibility_config=_visibilidad(f"hlf-{entorno.nombre}"), rules=reglas)
            CfnOutput(self, "SalidaWaf", value=self.web_acl.attr_arn)

        # -- CloudTrail: quién cambió la infraestructura o leyó secretos ------------------------------------
        self.trail: cloudtrail.Trail | None = None
        if entorno.cloudtrail:
            bucket = s3.Bucket(
                self, "Auditoria",
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption=s3.BucketEncryption.KMS if datos.clave else s3.BucketEncryption.S3_MANAGED,
                encryption_key=datos.clave,
                enforce_ssl=True, versioned=True,
                object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
                object_lock_enabled=True,
                object_lock_default_retention=s3.ObjectLockRetention.governance(Duration.days(365)),
                lifecycle_rules=[s3.LifecycleRule(id="auditoria-2-anios", expiration=Duration.days(730))],
                removal_policy=RemovalPolicy.RETAIN,
            )
            self.trail = cloudtrail.Trail(
                self, "Trail", trail_name=f"hlf-{entorno.nombre}", bucket=bucket, encryption_key=datos.clave,
                is_multi_region_trail=True, include_global_service_events=True, enable_file_validation=True,
                management_events=cloudtrail.ReadWriteType.ALL)
            CfnOutput(self, "SalidaBucketAuditoria", value=bucket.bucket_name)

        # -- AWS Backup de RDS, con copia en otra región ----------------------------------------------------
        self.plan_respaldo: backup.BackupPlan | None = None
        if entorno.respaldo:
            if datos.rds is None:
                Annotations.of(self).add_warning_v2("hlf:respaldo-sin-rds", "respaldo=True sin RDS: no hay nada que respaldar")
            else:
                boveda = backup.BackupVault(self, "Boveda", backup_vault_name=f"hlf-{entorno.nombre}",
                                            encryption_key=datos.clave, removal_policy=RemovalPolicy.RETAIN)
                copias = []
                if entorno.respaldo_region_copia:
                    destino = backup.BackupVault.from_backup_vault_arn(
                        self, "BovedaCopia",
                        f"arn:aws:backup:{entorno.respaldo_region_copia}:{self.account}:backup-vault:"
                        f"{nombre_boveda_copia(entorno)}")
                    copias = [backup.BackupPlanCopyActionProps(destination_backup_vault=destino,
                                                               delete_after=Duration.days(entorno.dias_respaldo_rds))]
                self.plan_respaldo = backup.BackupPlan(self, "Plan", backup_plan_name=f"hlf-{entorno.nombre}",
                                                       backup_vault=boveda)
                self.plan_respaldo.add_rule(backup.BackupPlanRule(
                    rule_name="diario", schedule_expression=events.Schedule.cron(minute="0", hour="9"),  # UTC
                    delete_after=Duration.days(entorno.dias_respaldo_rds), copy_actions=copias))
                self.plan_respaldo.add_selection("Rds", resources=[
                    backup.BackupResource.from_rds_database_instance(datos.rds)])


def _visibilidad(nombre: str) -> wafv2.CfnWebACL.VisibilityConfigProperty:
    return wafv2.CfnWebACL.VisibilityConfigProperty(cloud_watch_metrics_enabled=True, metric_name=nombre,
                                                    sampled_requests_enabled=True)
