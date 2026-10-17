"""Texto de un examen con Amazon Textract (F0012), leyendo el archivo directamente desde S3 (no pasa por disco).

AnalyzeDocument síncrono (imágenes y PDF de una página); para un PDF de varias páginas, StartDocumentAnalysis y espera.
Devuelve las líneas en orden de lectura y, de las tablas, cada fila como una línea "celda | celda" (los laboratorios
suelen informar los resultados en tablas: así la fila queda junta como cita).
"""
from __future__ import annotations

import time

ESPERA_MAX_S = 120


def _texto(bloques: list[dict]) -> str:
    por_id = {b["Id"]: b for b in bloques}
    lineas = [b["Text"] for b in bloques if b["BlockType"] == "LINE" and b.get("Text")]
    for tabla in (b for b in bloques if b["BlockType"] == "TABLE"):
        celdas = [por_id[i] for r in tabla.get("Relationships", []) if r["Type"] == "CHILD" for i in r["Ids"]
                  if por_id.get(i, {}).get("BlockType") == "CELL"]
        filas: dict[int, list[tuple[int, str]]] = {}
        for c in celdas:
            palabras = [por_id[i].get("Text", "") for r in c.get("Relationships", []) if r["Type"] == "CHILD"
                        for i in r["Ids"] if por_id.get(i, {}).get("BlockType") == "WORD"]
            filas.setdefault(c["RowIndex"], []).append((c["ColumnIndex"], " ".join(palabras)))
        for _, celdas_fila in sorted(filas.items()):
            lineas.append(" | ".join(t for _, t in sorted(celdas_fila) if t))
    return "\n".join(lineas)


def extraer(textract, bucket: str, clave: str) -> str:
    documento = {"S3Object": {"Bucket": bucket, "Name": clave}}
    try:
        r = textract.analyze_document(Document=documento, FeatureTypes=["TABLES"])
        return _texto(r.get("Blocks", []))
    except Exception as e:  # noqa: BLE001 — PDF de varias páginas: análisis asíncrono
        if "UnsupportedDocument" not in type(e).__name__ and "UnsupportedDocument" not in str(e):
            raise
    job = textract.start_document_analysis(DocumentLocation=documento, FeatureTypes=["TABLES"])["JobId"]
    inicio, espera, bloques, token = time.time(), 1.0, [], None
    while True:
        r = textract.get_document_analysis(JobId=job, **({"NextToken": token} if token else {}))
        if r["JobStatus"] == "IN_PROGRESS":
            if time.time() - inicio > ESPERA_MAX_S:
                raise TimeoutError("Textract no terminó a tiempo")
            time.sleep(espera)
            espera = min(espera * 1.5, 5)
            continue
        if r["JobStatus"] != "SUCCEEDED":
            raise RuntimeError(f"Textract: {r['JobStatus']} {r.get('StatusMessage', '')}")
        bloques += r.get("Blocks", [])
        token = r.get("NextToken")
        if not token:
            return _texto(bloques)
