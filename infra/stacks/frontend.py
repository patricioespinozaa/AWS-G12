"""Frontend: bucket S3 privado + CloudFront. Una sola URL HTTPS para la web y la API.

- `/*`     → S3 (solo CloudFront lo lee, con Origin Access Control).
- `/api/*` → ALB interno por un VPC origin de CloudFront, sin caché. Igual que el proxy de Vite en desarrollo:
             el frontend usa rutas relativas y no necesita CORS.
Las rutas de la SPA (/bandeja, /ficha/…) se resuelven con una CloudFront Function en el comportamiento por
defecto. No se usan páginas de error de la distribución porque también reescribirían los 404 de la API.

Login (F0007): aquí se crea el app client de Cognito, porque su URL de retorno es la de esta distribución, y su
configuración se publica en SSM para la API. `/api/*` reenvía la cabecera Authorization (ver POLITICA_API).
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Annotations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import custom_resources as cr
from constructs import Construct

from config.entornos import Entorno

from .backend import BackendStack
from .identidad import IdentidadStack
from .red import RedStack

# Sin extensión en el último segmento = ruta de la SPA → index.html. Con extensión = archivo real de S3.
FUNCION_SPA = """
function handler(event) {
  var request = event.request;
  var ultimo = request.uri.split('/').pop();
  if (ultimo.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
"""
PREFIX_LIST_CLOUDFRONT = "com.amazonaws.global.cloudfront.origin-facing"
# Orígenes locales permitidos como retorno del login, para desarrollo contra el User Pool de AWS
RETORNOS_LOCALES = ["http://localhost:5173/", "http://localhost:8000/"]


class FrontendStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, red: RedStack, backend: BackendStack,
                 identidad: IdentidadStack, dist: Path, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: frontend (S3 + CloudFront)", **kwargs)

        bucket = s3.Bucket(
            self, "Web",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            # Es un build: se regenera con npm run build, no hace falta conservarlo
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # El ALB solo acepta tráfico desde CloudFront. El ID de la prefix list cambia por región:
        # se consulta al desplegar, no al sintetizar (no requiere credenciales en `cdk synth`).
        prefix_list = cr.AwsCustomResource(
            self, "PrefixListCloudFront",
            on_create=_buscar_prefix_list(), on_update=_buscar_prefix_list(),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE),
            install_latest_aws_sdk=False,
        )
        ec2.CfnSecurityGroupIngress(
            self, "AlbDesdeCloudFront",
            group_id=red.sg_alb.security_group_id,
            ip_protocol="tcp", from_port=80, to_port=80,
            source_prefix_list_id=prefix_list.get_response_field("PrefixLists.0.PrefixListId"),
            description="CloudFront (VPC origin) al ALB interno",
        )

        api = origins.VpcOrigin.with_application_load_balancer(
            backend.alb,
            http_port=80,
            protocol_policy=cf.OriginProtocolPolicy.HTTP_ONLY,
            read_timeout=Duration.seconds(60),
            keepalive_timeout=Duration.seconds(60),
        )
        # /api/* no se guarda en caché (TTL 0), pero la política debe nombrar Authorization: CloudFront no la
        # reenvía en los GET con CachingDisabled y la API recibiría las peticiones sin la sesión
        politica_api = cf.CachePolicy(
            self, "PoliticaApi",
            comment="API: sin caché, reenvía Authorization",
            default_ttl=Duration.seconds(0), min_ttl=Duration.seconds(0), max_ttl=Duration.seconds(1),
            header_behavior=cf.CacheHeaderBehavior.allow_list("Authorization"),
            query_string_behavior=cf.CacheQueryStringBehavior.all(),
            cookie_behavior=cf.CacheCookieBehavior.none(),
            enable_accept_encoding_gzip=True, enable_accept_encoding_brotli=True,
        )
        rutas_spa = cf.Function(self, "RutasSpa", code=cf.FunctionCode.from_inline(FUNCION_SPA),
                                runtime=cf.FunctionRuntime.JS_2_0,
                                comment="Rutas de la SPA a index.html")

        self.distribucion = cf.Distribution(
            self, "Distribucion",
            comment=f"HLF priorización ({entorno.nombre})",
            default_root_object="index.html",
            price_class=cf.PriceClass.PRICE_CLASS_100,
            http_version=cf.HttpVersion.HTTP2_AND_3,
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cf.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cf.ResponseHeadersPolicy.SECURITY_HEADERS,
                function_associations=[cf.FunctionAssociation(function=rutas_spa,
                                                               event_type=cf.FunctionEventType.VIEWER_REQUEST)],
                compress=True,
            ),
            additional_behaviors={
                "/api/*": cf.BehaviorOptions(
                    origin=api,
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                    cache_policy=politica_api,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=cf.ResponseHeadersPolicy.SECURITY_HEADERS,
                    compress=True,
                ),
            },
        )

        if (dist / "index.html").exists():
            # Los archivos de Vite llevan hash en el nombre: caché de un año. index.html, sin caché.
            archivos = s3deploy.BucketDeployment(
                self, "WebArchivos",
                sources=[s3deploy.Source.asset(str(dist), exclude=["index.html"])],
                destination_bucket=bucket,
                cache_control=[s3deploy.CacheControl.from_string("public, max-age=31536000, immutable")],
                prune=False,      # conserva los archivos de la versión anterior para navegadores con index viejo
            )
            indice = s3deploy.BucketDeployment(
                self, "WebIndice",
                sources=[s3deploy.Source.asset(str(dist), exclude=["*", "!index.html"])],
                destination_bucket=bucket,
                cache_control=[s3deploy.CacheControl.from_string("no-cache")],
                prune=False,
                distribution=self.distribucion,
                distribution_paths=["/index.html"],
            )
            indice.node.add_dependency(archivos)
        else:
            Annotations.of(self).add_warning(
                f"No existe {dist / 'index.html'}: la web no se publica. Corre `npm run build` en web/ y despliega de nuevo.")

        # Login (F0007): app client público (sin secreto) con authorization code + PKCE, retorno a esta distribución
        url_app = f"https://{self.distribucion.distribution_domain_name}/"
        cliente = cognito.UserPoolClient(
            self, "ClienteWeb",
            user_pool=identidad.user_pool,
            user_pool_client_name=f"hlf-web-{entorno.nombre}",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=[url_app, *RETORNOS_LOCALES],
                logout_urls=[url_app, *RETORNOS_LOCALES]),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True,
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.hours(12),       # una jornada; después, login de nuevo
            enable_token_revocation=True,
        )
        ssm.StringParameter(
            self, "ConfigLogin",
            parameter_name=entorno.parametro_cognito,
            description="Login de la Administradora (F0007): lo lee la API para verificar tokens",
            string_value=Stack.of(self).to_json_string({
                "region": self.region, "user_pool_id": identidad.user_pool.user_pool_id,
                "client_id": cliente.user_pool_client_id, "dominio": identidad.url_dominio}),
        )

        CfnOutput(self, "Url", value=f"https://{self.distribucion.distribution_domain_name}",
                  description="URL de la app")
        CfnOutput(self, "BucketWeb", value=bucket.bucket_name)
        CfnOutput(self, "DistribucionId", value=self.distribucion.distribution_id)


def _buscar_prefix_list() -> cr.AwsSdkCall:
    return cr.AwsSdkCall(
        service="EC2",
        action="describeManagedPrefixLists",
        parameters={"Filters": [{"Name": "prefix-list-name", "Values": [PREFIX_LIST_CLOUDFRONT]}]},
        physical_resource_id=cr.PhysicalResourceId.of(PREFIX_LIST_CLOUDFRONT),
        output_paths=["PrefixLists.0.PrefixListId"],
    )
