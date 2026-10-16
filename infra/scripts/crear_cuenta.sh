#!/usr/bin/env bash
# Crea la cuenta de una Administradora en el User Pool (F0007) y la agrega al grupo `administracion`.
#
#   bash infra/scripts/crear_cuenta.sh <usuario> "<Nombre Apellido>" [correo]      # ENTORNO=demo por defecto
#
# Una cuenta por persona, nunca compartida: cada carga y decisión queda a su nombre. Imprime una clave temporal
# (una sola vez, no se guarda); en el primer ingreso Cognito pide cambiarla. Con correo, la persona puede
# recuperar su clave sola. Para quitar el acceso: ver infra/README.md ("Cuentas").
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Uso: bash infra/scripts/crear_cuenta.sh <usuario> \"<Nombre Apellido>\" [correo]" >&2
    exit 2
fi
usuario="$1"; nombre="$2"; correo="${3:-}"
entorno="${ENTORNO:-demo}"
stack="Hlf$(tr '[:lower:]' '[:upper:]' <<< "${entorno:0:1}")${entorno:1}-Identidad"

pool=$(aws cloudformation describe-stacks --stack-name "$stack" \
    --query "Stacks[0].Outputs[?OutputKey=='SalidaUserPool'].OutputValue" --output text)
if [ -z "$pool" ] || [ "$pool" = "None" ]; then
    echo "No encontré el User Pool en el stack $stack. ¿Está desplegado?" >&2
    exit 1
fi

# Clave temporal que cumple la política (12+ caracteres, mayúscula, minúscula y número)
temporal=$(python -c "import secrets, string; a=string.ascii_letters+string.digits; \
print('Hlf-' + ''.join(secrets.choice(a) for _ in range(14)) + secrets.choice('0123456789') + 'aZ')")

atributos=("Name=name,Value=$nombre")
if [ -n "$correo" ]; then
    atributos+=("Name=email,Value=$correo" "Name=email_verified,Value=true")
fi

aws cognito-idp admin-create-user --user-pool-id "$pool" --username "$usuario" \
    --user-attributes "${atributos[@]}" --temporary-password "$temporal" --message-action SUPPRESS >/dev/null
aws cognito-idp admin-add-user-to-group --user-pool-id "$pool" --username "$usuario" --group-name administracion

echo "Cuenta creada en $stack: $usuario ($nombre)"
echo "Clave temporal (se pide cambiarla en el primer ingreso; no queda guardada en ningún lado): $temporal"
