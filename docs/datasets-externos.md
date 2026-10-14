# Datasets síntoma–enfermedad para la priorización dinámica (HLF)

**Desafío:** Ambulatorio dinámico HLF: priorización clínica evolutiva y gestión inteligente del recurso box
**Hospital Clínico Dra. Eloísa Díaz La Florida (HLF), SSMSO** · Hackatón AWS Breaking Barriers Chile 2026

---

## Enfoque

La mayoría de los catálogos públicos de "síntoma → enfermedad" sirven para **diagnosticar** a partir de síntomas. El desafío del HLF pide otra cosa: detectar **deterioro mientras el paciente espera**. Las señales son consultas de urgencia, hospitalizaciones, descompensaciones crónicas y, sobre todo, **texto libre en la ficha clínica electrónica (RCE)**. Por eso los datasets están ordenados según lo bien que encajan con ese problema, no con el diagnóstico.

---

## 1. Prioridad alta: texto clínico en español, sobre todo de Chile

### Chilean Waiting List Corpus (U. de Chile, 2020)
- **Qué es:** interconsultas reales y anonimizadas de listas de espera de hospitales públicos chilenos, de especialidades médicas y odontológicas.
- **Tamaño:** un subconjunto de unas 9.000 interconsultas anotado con 10 tipos de entidad (enfermedad, hallazgo, procedimiento, abreviatura, etc.), 6 atributos y relaciones.
- **Formato:** texto con anotaciones Standoff, más una versión CoNLL lista para entrenar extracción de entidades (NER). También está en Hugging Face.
- **Uso en el desafío:** es el dataset más parecido a los datos del HLF. Permite extraer diagnósticos y hallazgos del texto libre de la derivación para calcular la prioridad inicial.
- **Licencia:** la descripción indica CC BY-NC-SA 4.0, pero la ficha de Zenodo marca "Other (Not Open)". Para un hackatón no debería ser problema; si el proyecto sigue después, conviene confirmarla con los autores.
- **Enlaces:** [Zenodo](https://zenodo.org/record/7555181) · [Paper](https://aclanthology.org/2020.clinicalnlp-1.32/)

### SympTEMIST (Barcelona Supercomputing Center)
- **Qué es:** 1.000 casos clínicos en español con unas 12.200 menciones de síntomas, signos y hallazgos.
- **Normalización:** las menciones están mapeadas a **SNOMED CT**.
- **Uso en el desafío:** reconocer síntomas en las notas de urgencia u hospitalización y llevarlos a códigos estándar.
- **Enlaces:** [Zenodo](https://zenodo.org/records/10635215) · [Descripción del corpus](https://temu.bsc.es/symptemist/corpus-description/)

---

## 2. Relación síntoma–enfermedad con severidad

### DDXPlus (NeurIPS 2022)
- **Qué es:** unos 1,3 millones de pacientes **sintéticos**, cada uno con su patología real y su diagnóstico diferencial.
- **Contenido:** 49 patologías, 110 síntomas y 113 antecedentes.
- **Severidad:** cada patología tiene un nivel de severidad de 1 a 5, donde 1 es lo más grave.
- **Licencia:** CC-BY.
- **Uso en el desafío:** es el mejor punto de partida si quieren un puntaje basado en síntomas y antecedentes, porque la severidad ya viene incluida.
- **Limitación:** las patologías son sobre todo respiratorias o de urgencia, no de especialidad ambulatoria.
- **Enlaces:** [Figshare](https://figshare.com/articles/dataset/DDXPlus_Dataset/20043374) · [Paper](https://arxiv.org/abs/2205.09148)

### Kaggle: Disease Symptom Description Dataset
- **Identificador:** `itachi9604/disease-symptom-description-dataset`
- **Qué es:** relaciona unas 41 enfermedades con unos 130 síntomas e incluye `Symptom-severity.csv`, con un peso de severidad por síntoma. No pude abrir la página para confirmar estas cifras.
- **Uso en el desafío:** sirve para una demo rápida.
- **Limitación:** son datos de juguete sin validación clínica, y no conviene presentarlo como evidencia.

### gretelai/symptom_to_diagnosis (Hugging Face)
- **Qué es:** descripciones de síntomas en lenguaje natural, en inglés, con unas 22 etiquetas de diagnóstico.
- **Licencia:** Apache-2.0.
- **Uso en el desafío:** probar un clasificador o un LLM sobre texto libre.
- **Enlace:** [Hugging Face](https://huggingface.co/datasets/gretelai/symptom_to_diagnosis/tree/1718fcb269c001211a8a2c62e74ca96825bf1377)

---

## 3. Para ponderar la carga de enfermedad

### CIE-10 Chile (DEIS/MINSAL) con el paquete R `ciecl`
- **Qué es:** el catálogo oficial chileno de CIE-10 (v2018), con búsqueda, validación y normalización de códigos.
- **Funciones clave:** `cie_comorbid()` calcula los índices de comorbilidad de **Charlson** y **Elixhauser** a partir de códigos CIE-10.
- **Uso en el desafío:** subir automáticamente la prioridad de pacientes con diabetes, hipertensión o insuficiencia renal sin entrenar ningún modelo.
- **Enlace:** [Documentación](https://docs.ropensci.org/ciecl/articles/ciecl.html)

### Human Phenotype Ontology (HPO)
- **Qué es:** una ontología abierta de fenotipos y síntomas vinculados a enfermedades.
- **Limitación:** está orientada a enfermedades raras y es menos útil para este caso.
- **Enlace:** [OBO Foundry](https://www.obofoundry.org/ontology/hp)

---

## 4. Triage real, pero no sirve para este hackatón

### MIMIC-IV-ED y derivados (PhysioNet)
- **Qué es:** datos reales de urgencia, con motivo de consulta, signos vitales y nivel de urgencia.
- **Limitación:** requieren acceso acreditado con curso y aprobación, que tarda días, así que no alcanza para el hackatón (14 al 16 de octubre).
- **Enlace:** [PhysioNet](https://www.physionet.org/content/mimic-iv-ext-cds/)

---

## Resumen comparativo

| Dataset | Idioma | Tipo | Severidad | Licencia | Uso principal |
|---|---|---|---|---|---|
| Chilean Waiting List Corpus | Español (Chile) | Real, anonimizado | No | CC BY-NC-SA 4.0 (por confirmar) | NER sobre interconsultas |
| SympTEMIST | Español | Casos clínicos | No | Ver Zenodo | NER de síntomas → SNOMED CT |
| DDXPlus | Francés / inglés | Sintético | Sí (1–5 por patología) | CC-BY | Puntaje síntoma–patología |
| Kaggle itachi9604 | Inglés | Juguete | Sí (peso por síntoma) | Ver Kaggle | Demo rápida |
| gretelai/symptom_to_diagnosis | Inglés | Texto natural | No | Apache-2.0 | Clasificador o LLM |
| CIE-10 Chile + `ciecl` | Español | Catálogo | Charlson / Elixhauser | Ver fuente | Carga de comorbilidad |
| MIMIC-IV-ED | Inglés | Real | Nivel de urgencia | Acceso acreditado | No viable en el hackatón |

---

## Cómo combinarlos para mejorar la priorización

1. **Extraer:** un modelo de extracción de entidades entrenado con Chilean Waiting List y SympTEMIST saca diagnósticos y síntomas del texto de la interconsulta y de cada nuevo evento en la ficha.
2. **Ponderar:** cada hallazgo suma según:
   - la severidad (escala de DDXPlus o una tabla propia validada por el equipo clínico),
   - la comorbilidad de Charlson,
   - factores como la edad.
3. **Reevaluar:** cada consulta de urgencia, hospitalización o cambio de tratamiento suma puntos con decaimiento en el tiempo.
   *Caso de don Manuel:* "diabético + 2 urgencias por hiperglicemia + derivación a oftalmología" debería subir la alerta por riesgo de retinopatía.
4. **Explicar:** el sistema muestra por qué cambió la prioridad, algo clave para que el gestor clínico confíe en él.

### Puntaje de ejemplo

```
prioridad(t) = w1·severidad_derivación
             + w2·Charlson
             + w3·factor_edad
             + Σ_eventos [ w_evento · e^(−λ·(t − t_evento)) ]
```

Los pesos `w` y `λ` deben calibrarse con el equipo clínico del HLF.

---

## Brecha de datos

No encontré un dataset público con listas de espera chilenas a nivel de paciente con su evolución. Para la demo probablemente habrá que **generar trayectorias sintéticas** o usar los datos que entregue el HLF.
