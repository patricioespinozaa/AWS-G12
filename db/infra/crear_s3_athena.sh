#!/usr/bin/env bash
# Crea (si no existen) el bucket S3 y el workgroup de Athena de la capa de consulta (docs/feature/F0003).
# Después: python -m db athena publicar   y   python -m db athena exportar
#
# Requisitos: AWS CLI v2 configurado con permisos sobre S3 y Athena.
# Uso:        bash db/infra/crear_s3_athena.sh
# Variables opcionales: AWS_REGION, HLF_S3_BUCKET, HLF_ATHENA_WORKGROUP, HLF_ATHENA_LIMITE_BYTES
#
# El bucket queda privado (Block Public Access), versionado y cifrado (SSE-S3). Los resultados de Athena se borran
# a los 7 días. El workgroup impone su configuración y corta toda consulta que escanee más de 1 GB (control de costo).
set -euo pipefail

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}"
CUENTA=$(aws sts get-caller-identity --query Account --output text)
BUCKET="${HLF_S3_BUCKET:-hlf-priorizacion-${CUENTA}-${REGION}}"
WORKGROUP="${HLF_ATHENA_WORKGROUP:-hlf-priorizacion}"
LIMITE="${HLF_ATHENA_LIMITE_BYTES:-1073741824}"
export AWS_REGION="$REGION"

echo "Región: $REGION · bucket: $BUCKET · workgroup: $WORKGROUP"

if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "El bucket $BUCKET ya existe."
else
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  echo "Bucket creado."
fi

aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{
  "Rules": [
    {"ID": "resultados-athena-7-dias", "Status": "Enabled", "Filter": {"Prefix": "athena-resultados/"},
     "Expiration": {"Days": 7}},
    {"ID": "versiones-antiguas-30-dias", "Status": "Enabled", "Filter": {"Prefix": ""},
     "NoncurrentVersionExpiration": {"NoncurrentDays": 30}}
  ]}'
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=proyecto,Value=hlf-priorizacion}]'

CONFIG="ResultConfiguration={OutputLocation=s3://${BUCKET}/athena-resultados/,EncryptionConfiguration={EncryptionOption=SSE_S3}},EnforceWorkGroupConfiguration=true,PublishCloudWatchMetricsEnabled=true,BytesScannedCutoffPerQuery=${LIMITE},EngineVersion={SelectedEngineVersion=AUTO}"
if aws athena get-work-group --work-group "$WORKGROUP" >/dev/null 2>&1; then
  aws athena update-work-group --work-group "$WORKGROUP" --configuration-updates \
    "ResultConfigurationUpdates={OutputLocation=s3://${BUCKET}/athena-resultados/,EncryptionConfiguration={EncryptionOption=SSE_S3}},EnforceWorkGroupConfiguration=true,BytesScannedCutoffPerQuery=${LIMITE}"
  echo "Workgroup $WORKGROUP actualizado."
else
  aws athena create-work-group --name "$WORKGROUP" --configuration "$CONFIG" \
    --description "Consultas del proyecto HLF (raw e historial)" --tags Key=proyecto,Value=hlf-priorizacion
  echo "Workgroup $WORKGROUP creado."
fi

cat <<EOF

Listo. En esta misma terminal:

  export AWS_REGION=$REGION
  export HLF_S3_BUCKET=$BUCKET
  export HLF_ATHENA_WORKGROUP=$WORKGROUP

  python -m db athena publicar      # raw a S3 + tablas en Athena + verificación
  python -m db athena exportar      # historial nocturno de RDS a S3 (requiere conexión a RDS)
EOF
