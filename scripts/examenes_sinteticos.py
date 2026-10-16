"""Exámenes externos sintéticos (F0012): 10 informes de laboratorio inventados, en PDF y en foto (PNG), con su lectura
esperada. Sirven para las pruebas locales (el texto) y para evaluar Textract + Claude en AWS (los archivos).

    python scripts/examenes_sinteticos.py --destino data/examenes_sinteticos     # escribe los 10 archivos + esperado.json
    python scripts/examenes_sinteticos.py --evaluar --bucket <bucket> --prefijo hlf/pruebas/ocr/   # Textract + Claude reales

Ningún dato es real: laboratorios, valores y fechas son ficticios. Dos documentos ponen a prueba lo que NO se debe
inventar: uno sin fecha y uno con un examen fuera de los 8 tipos (debe quedar vacío).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# (archivo, formato, texto del informe, lectura esperada: tipo, valor (unidad del motor), fecha, lugar)
DOCUMENTOS = [
    ("01_glicemia_mgdl", "pdf", "LABORATORIO CLINICO ANDES\nPaciente: [anonimizado]\nFecha de toma de muestra: 12/08/2026\n"
     "Examen | Resultado | Unidad | Valor de referencia\nGlicemia en ayunas | 156 | mg/dL | 70 - 110",
     {"tipo_medicion": "glicemia", "valor": 156.0, "fecha_examen": "2026-08-12", "lugar": "LABORATORIO CLINICO ANDES"}),
    ("02_glicemia_mmol", "png", "CENTRO MEDICO LOS ALERCES\nFecha: 03/09/2026\nGlucosa plasmatica | 7,2 | mmol/L | 3,9 - 5,5",
     {"tipo_medicion": "glicemia", "valor": 129.7, "fecha_examen": "2026-09-03", "lugar": "CENTRO MEDICO LOS ALERCES"}),
    ("03_hba1c", "pdf", "LABORATORIO DEL SUR\nFecha de emision: 20/09/2026\nHemoglobina glicosilada (HbA1c) | 8,4 | % | 4,0 - 6,0",
     {"tipo_medicion": "HbA1c", "valor": 8.4, "fecha_examen": "2026-09-20", "lugar": "LABORATORIO DEL SUR"}),
    ("04_presion", "png", "CONSULTA PARTICULAR DR. EJEMPLO\nControl del 5 de octubre de 2026\nPresion arterial sistolica: 168 mmHg\n"
     "Presion arterial diastolica: 98 mmHg",
     {"tipo_medicion": "presion_sistolica", "valor": 168.0, "fecha_examen": "2026-10-05",
      "lugar": "CONSULTA PARTICULAR DR. EJEMPLO"}),
    ("05_saturacion", "pdf", "SERVICIO DE URGENCIA PRIVADO NORTE\nFecha: 28/09/2026\nSaturacion de oxigeno (SpO2): 89 %",
     {"tipo_medicion": "saturacion_o2", "valor": 89.0, "fecha_examen": "2026-09-28",
      "lugar": "SERVICIO DE URGENCIA PRIVADO NORTE"}),
    ("06_peak_flow", "png", "CLINICA RESPIRATORIA COSTA\nEspirometria del 15/08/2026\nPeak flow (PEF): 290 L/min",
     {"tipo_medicion": "peak_flow", "valor": 290.0, "fecha_examen": "2026-08-15", "lugar": "CLINICA RESPIRATORIA COSTA"}),
    ("07_phq9", "pdf", "CENTRO DE SALUD MENTAL AURORA\nFecha de aplicacion: 01/10/2026\nCuestionario PHQ-9 | Puntaje total | 19 puntos",
     {"tipo_medicion": "PHQ9", "valor": 19.0, "fecha_examen": "2026-10-01", "lugar": "CENTRO DE SALUD MENTAL AURORA"}),
    ("08_eva", "png", "KINESIOLOGIA INTEGRAL\nEvaluacion 22/09/2026\nEscala visual analoga del dolor (EVA): 8/10",
     {"tipo_medicion": "escala_dolor_eva", "valor": 8.0, "fecha_examen": "2026-09-22", "lugar": "KINESIOLOGIA INTEGRAL"}),
    ("09_sin_fecha", "pdf", "LABORATORIO ESTRELLA\nGlicemia | 132 | mg/dL",
     {"tipo_medicion": "glicemia", "valor": 132.0, "fecha_examen": None, "lugar": "LABORATORIO ESTRELLA"}),
    ("10_tipo_no_admitido", "png", "LABORATORIO CORDILLERA\nFecha: 10/09/2026\nColesterol total | 245 | mg/dL | < 200",
     {"tipo_medicion": None, "valor": None, "fecha_examen": "2026-09-10", "lugar": "LABORATORIO CORDILLERA"}),
]


def _pdf(texto: str) -> bytes:
    """Un PDF de una página con el texto (Helvetica). Sin dependencias."""
    lineas = texto.split("\n")
    contenido = "BT /F1 12 Tf 50 780 Td 16 TL " + " ".join(
        "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for l in lineas) + " ET"
    objetos = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream"]
    salida, posiciones = b"%PDF-1.4\n", []
    for i, o in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posiciones)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return salida


def _png(texto: str) -> bytes:
    """Una 'foto' del informe: texto negro sobre fondo claro (Pillow)."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    try:
        fuente = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        fuente = ImageFont.load_default()
    img = Image.new("RGB", (1400, 120 + 48 * len(texto.split("\n"))), (250, 248, 240))
    dibujo = ImageDraw.Draw(img)
    for i, linea in enumerate(texto.split("\n")):
        dibujo.text((60, 60 + 48 * i), linea, fill=(20, 20, 20), font=fuente)
    salida = io.BytesIO()
    img.save(salida, format="PNG")
    return salida.getvalue()


def escribir(destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    rutas, esperado = [], {}
    for nombre, formato, texto, lectura in DOCUMENTOS:
        ruta = destino / f"{nombre}.{formato}"
        ruta.write_bytes(_pdf(texto) if formato == "pdf" else _png(texto))
        rutas.append(ruta)
        esperado[ruta.name] = lectura
    (destino / "esperado.json").write_text(json.dumps(esperado, ensure_ascii=False, indent=2), encoding="utf-8")
    return rutas


def evaluar(bucket: str, prefijo: str, destino: Path) -> int:
    """Sube los 10 archivos, los lee con Textract + Claude y compara con lo esperado (solo valores con cita)."""
    import boto3
    from priorizacion import config
    from servicios.ocr_examenes import extraccion, texto
    s3, textract = boto3.client("s3"), boto3.client("textract", region_name=config.AWS_REGION)
    rutas = escribir(destino)
    esperado = json.loads((destino / "esperado.json").read_text(encoding="utf-8"))
    aciertos = total = inventados = 0
    for ruta in rutas:
        clave = prefijo.rstrip("/") + "/" + ruta.name
        s3.put_object(Bucket=bucket, Key=clave, Body=ruta.read_bytes(),
                      ContentType="application/pdf" if ruta.suffix == ".pdf" else "image/png")
        contenido = texto.extraer(textract, bucket, clave)
        propuesta, _ = extraccion.proponer(contenido)
        lectura = extraccion.validar(propuesta, contenido)
        for campo in ("tipo_medicion", "valor", "fecha_examen"):
            total += 1
            obtenido, ideal = lectura.valor(campo), esperado[ruta.name][campo]
            if campo == "valor" and obtenido is not None:
                obtenido = float(obtenido)
            ok = obtenido == ideal
            aciertos += ok
            c = lectura.campos[campo]
            if c.valor is not None and (not c.cita or extraccion.normalizar(c.cita) not in extraccion.normalizar(contenido)):
                inventados += 1
            print(f"  {'✔' if ok else '✘'} {ruta.name:<26} {campo:<14} esperado {ideal} · obtenido {obtenido}")
    print(f"\n{aciertos}/{total} campos correctos · {inventados} propuestas sin cita literal (debe ser 0)")
    return 0 if inventados == 0 else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--destino", type=Path, default=RAIZ / "data" / "examenes_sinteticos")
    p.add_argument("--evaluar", action="store_true")
    p.add_argument("--bucket")
    p.add_argument("--prefijo", default="hlf/pruebas/ocr/")
    args = p.parse_args(argv)
    if args.evaluar:
        if not args.bucket:
            p.error("--evaluar requiere --bucket")
        return evaluar(args.bucket, args.prefijo, args.destino)
    for r in escribir(args.destino):
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
