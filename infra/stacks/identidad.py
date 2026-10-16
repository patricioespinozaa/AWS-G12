"""Identidad (F0007): Cognito User Pool de la Administradora, con un solo grupo (`administracion`).

- Sin registro abierto: las cuentas se crean con infra/scripts/crear_cuenta.sh (una por persona, nunca compartida).
- Hosted UI de Cognito para el login (authorization code + PKCE). El app client y su URL de retorno se crean en
  FrontendStack, junto a la distribución de CloudFront, y su configuración queda en un parámetro de SSM que la API
  lee al verificar tokens (así no hay dependencia circular entre backend y frontend).
"""
from __future__ import annotations

from aws_cdk import Aws, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

from config.entornos import Entorno

GRUPO = "administracion"


class IdentidadStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: identidad (Cognito)", **kwargs)

        self.user_pool = cognito.UserPool(
            self, "Usuarias",
            user_pool_name=f"hlf-priorizacion-{entorno.nombre}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            sign_in_case_sensitive=False,
            standard_attributes=cognito.StandardAttributes(
                fullname=cognito.StandardAttribute(required=False, mutable=True),
                email=cognito.StandardAttribute(required=False, mutable=True)),
            password_policy=cognito.PasswordPolicy(min_length=12, require_lowercase=True, require_uppercase=True,
                                                   require_digits=True, require_symbols=False,
                                                   temp_password_validity=Duration.days(3)),
            # Opcional en la demo; obligatorio antes de usar datos reales (F0013)
            mfa=cognito.Mfa.REQUIRED if entorno.mfa_obligatorio else cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN if entorno.retener_datos else RemovalPolicy.DESTROY,
        )
        cognito.CfnUserPoolGroup(self, "GrupoAdministracion", user_pool_id=self.user_pool.user_pool_id,
                                 group_name=GRUPO, description="Administradora del HLF: única con acceso a la app")

        # Prefijo único por cuenta y entorno (el dominio de Cognito es global dentro de la región)
        prefijo = f"hlf-{entorno.nombre}-{Aws.ACCOUNT_ID}"
        self.dominio = self.user_pool.add_domain("Dominio", cognito_domain=cognito.CognitoDomainOptions(
            domain_prefix=prefijo))
        self.url_dominio = self.dominio.base_url()

        CfnOutput(self, "SalidaUserPool", value=self.user_pool.user_pool_id)
        CfnOutput(self, "SalidaDominioLogin", value=self.url_dominio)
