"""Red: VPC en 2 zonas y los security groups de todo el sistema.

Los tres security groups viven aquí, con las reglas entre ellos, para que ningún stack tenga que modificar
recursos de otro (eso crea dependencias circulares en CloudFormation). La única regla que llega de afuera es
la de CloudFront hacia el ALB, que agrega el stack de frontend.
"""
from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from config.entornos import Entorno


class RedStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: red (VPC y security groups)", **kwargs)
        con_nat = entorno.nat_gateways > 0

        subredes = [ec2.SubnetConfiguration(name="publica", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)]
        if con_nat:
            subredes.append(ec2.SubnetConfiguration(name="privada", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                                                    cidr_mask=24))
        subredes.append(ec2.SubnetConfiguration(name="aislada", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                                                cidr_mask=24))

        self.vpc = ec2.Vpc(
            self, "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.40.0.0/16"),
            max_azs=2,
            nat_gateways=entorno.nat_gateways,
            subnet_configuration=subredes,
            # Gratis: el tráfico a S3 (descarga de CSV, Athena) no sale a internet
            gateway_endpoints={"S3": ec2.GatewayVpcEndpointOptions(service=ec2.GatewayVpcEndpointAwsService.S3)},
        )

        # Dónde va cada cosa. Sin NAT, las tareas necesitan IP pública para llegar a ECR, S3 y Bedrock;
        # igual son inalcanzables desde internet porque su security group solo acepta al ALB.
        self.tipo_subred_backend = ec2.SubnetType.PRIVATE_WITH_EGRESS if con_nat else ec2.SubnetType.PUBLIC
        self.subredes_backend = ec2.SubnetSelection(subnet_type=self.tipo_subred_backend)
        self.ip_publica_backend = not con_nat
        self.subredes_alb = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS if con_nat else ec2.SubnetType.PRIVATE_ISOLATED)
        self.subredes_datos = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)

        self.sg_alb = ec2.SecurityGroup(
            self, "SgAlb", vpc=self.vpc, allow_all_outbound=False,
            description="ALB interno: entrada solo desde CloudFront (regla en el stack de frontend)")
        self.sg_backend = ec2.SecurityGroup(
            self, "SgBackend", vpc=self.vpc, allow_all_outbound=True,
            description="Tareas del backend: entrada solo desde el ALB")
        self.sg_rds = ec2.SecurityGroup(
            self, "SgRds", vpc=self.vpc, allow_all_outbound=False,
            description="RDS PostgreSQL: entrada solo desde el backend")

        self.sg_alb.add_egress_rule(self.sg_backend, ec2.Port.tcp(8000), "ALB a la API")
        self.sg_backend.add_ingress_rule(self.sg_alb, ec2.Port.tcp(8000), "ALB a la API")
        self.sg_rds.add_ingress_rule(self.sg_backend, ec2.Port.tcp(5432), "API y tareas de carga a PostgreSQL")
