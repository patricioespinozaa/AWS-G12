#!/usr/bin/env bash
# Crea (o recrea) la instancia RDS PostgreSQL del proyecto con AWS CLI, si la cuenta del hackatón se limpió.
# Después de esto, cargar los datos con:  python -m db restaurar
#
# Requisitos: AWS CLI v2 configurado (aws configure / SSO) con permisos sobre RDS, EC2 y Secrets Manager.
# Uso:        bash db/infra/crear_rds.sh
# Variables opcionales: AWS_REGION, HLF_RDS_ID, HLF_RDS_CLASE, HLF_DB_NAME
#
# Queda accesible por internet SOLO desde tu IP (security group). Es aceptable para el dataset sintético;
# con datos reales del HLF la base debe ser privada (sin acceso público) y accederse desde la VPC.
set -euo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}"
ID="${HLF_RDS_ID:-hlf-priorizacion}"
CLASE="${HLF_RDS_CLASE:-db.t4g.micro}"
BASE="${HLF_DB_NAME:-hlf}"
USUARIO="hlf_admin"
SG_NOMBRE="${ID}-sg"
export AWS_REGION="$REGION"

echo "Región: $REGION · instancia: $ID ($CLASE) · base: $BASE"

if aws rds describe-db-instances --db-instance-identifier "$ID" >/dev/null 2>&1; then
  echo "La instancia $ID ya existe; no se crea de nuevo."
else
  VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
  SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$SG_NOMBRE" Name=vpc-id,Values="$VPC" \
        --query 'SecurityGroups[0].GroupId' --output text)
  if [ "$SG" = "None" ]; then
    SG=$(aws ec2 create-security-group --group-name "$SG_NOMBRE" --vpc-id "$VPC" \
          --description "PostgreSQL HLF solo desde IPs autorizadas" --query GroupId --output text)
  fi
  MI_IP=$(curl -s https://checkip.amazonaws.com)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 5432 --cidr "${MI_IP}/32" \
    >/dev/null 2>&1 || echo "La regla para ${MI_IP}/32 ya existía."

  echo "Creando la instancia (tarda entre 5 y 10 minutos)…"
  aws rds create-db-instance \
    --db-instance-identifier "$ID" \
    --engine postgres \
    --db-instance-class "$CLASE" \
    --allocated-storage 20 --storage-type gp3 --storage-encrypted \
    --db-name "$BASE" \
    --master-username "$USUARIO" --manage-master-user-password \
    --vpc-security-group-ids "$SG" \
    --publicly-accessible --no-multi-az \
    --backup-retention-period 1 \
    --tags Key=proyecto,Value=hlf-priorizacion >/dev/null
fi

aws rds wait db-instance-available --db-instance-identifier "$ID"
read -r HOST SECRETO < <(aws rds describe-db-instances --db-instance-identifier "$ID" \
  --query 'DBInstances[0].[Endpoint.Address,MasterUserSecret.SecretArn]' --output text)

cat <<EOF

Instancia lista. Para cargar los datos (en esta misma terminal):

  export AWS_REGION=$REGION
  export HLF_DB_HOST=$HOST
  export HLF_DB_NAME=$BASE
  export HLF_DB_SECRET_ID=$SECRETO
  python -m db restaurar

EOF
