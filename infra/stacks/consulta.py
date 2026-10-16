"""Consulta en lenguaje natural (F0009): Knowledge Base del equipo clínico sobre S3 Vectors y permisos de consulta.

- Vectores en **S3 Vectors** (bucket e índice propios): menor costo fijo que OpenSearch Serverless para ~650 documentos.
- Embeddings con **Amazon Titan Text Embeddings V2** (1024 dimensiones; multilingüe), permitido en la cuenta.
- Fuente de datos: el prefijo `kb/equipo/` del bucket de datos, que escribe la preparación (servicios/preparacion_kb).
- La consulta corre en la API (ECS), que ya tiene la sesión de Cognito, la conexión a RDS y salida a los servicios de
  AWS. Una Lambda necesitaría estar en la VPC para llegar a RDS y, sin NAT, endpoints privados para Bedrock y Athena.
  Las políticas de este stack se adjuntan a las tareas del backend (ver backend.py).
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

from config.entornos import Entorno

from .datos import DatosStack

MODELO_EMBEDDINGS = "amazon.titan-embed-text-v2:0"
DIMENSIONES = 1024
BASES_ATHENA = ("hlf_raw", "hlf_historial")


class ConsultaStack(Stack):
    def __init__(self, scope: Construct, id: str, *, entorno: Entorno, datos: DatosStack, **kwargs) -> None:
        super().__init__(scope, id, description="HLF priorización: consulta en lenguaje natural (KB y permisos)", **kwargs)
        self.prefijo_kb = f"{entorno.prefijo_s3}/kb/equipo"

        vectores = s3vectors.CfnVectorBucket(self, "Vectores", vector_bucket_name=f"hlf-kb-{entorno.nombre}")
        indice = s3vectors.CfnIndex(
            self, "IndiceEquipo",
            vector_bucket_name=vectores.vector_bucket_name, index_name="equipo-clinico",
            data_type="float32", dimension=DIMENSIONES, distance_metric="cosine",
            # El texto del fragmento y los metadatos de Bedrock no se filtran: no cuentan en el límite de 2 KB filtrable
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]))
        indice.add_dependency(vectores)

        modelo_emb = f"arn:aws:bedrock:{self.region}::foundation-model/{MODELO_EMBEDDINGS}"
        rol_kb = iam.Role(
            self, "RolKb", assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}),
            description="Rol de servicio de la Knowledge Base del equipo clínico")
        rol_kb.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[modelo_emb]))
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject"], resources=[datos.bucket.arn_for_objects(f"{self.prefijo_kb}/*")]))
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[datos.bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{self.prefijo_kb}/*"]}}))
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                     "s3vectors:QueryVectors", "s3vectors:GetIndex", "s3vectors:ListVectors"],
            resources=[indice.attr_index_arn]))

        self.kb = bedrock.CfnKnowledgeBase(
            self, "KbEquipo",
            name=f"hlf-equipo-clinico-{entorno.nombre}",
            description="Perfiles de pacientes, resúmenes por especialidad y box, y diccionario de datos (F0009)",
            role_arn=rol_kb.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=modelo_emb,
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=DIMENSIONES, embedding_data_type="FLOAT32")))),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=indice.attr_index_arn, vector_bucket_arn=vectores.attr_vector_bucket_arn)),
        )
        self.kb.node.add_dependency(rol_kb)

        self.fuente = bedrock.CfnDataSource(
            self, "FuenteEquipo",
            knowledge_base_id=self.kb.attr_knowledge_base_id,
            name="kb-equipo-s3",
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3", s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=datos.bucket.bucket_arn, inclusion_prefixes=[f"{self.prefijo_kb}/"])),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=600, overlap_percentage=15))),
        )

        # KB del paciente (F0010): solo preguntas frecuentes. Índice propio en el mismo bucket de vectores; la base de
        # datos impide registrar en ella algo que no sea faq_paciente
        self.prefijo_kb_paciente = f"{entorno.prefijo_s3}/kb/paciente"
        indice_paciente = s3vectors.CfnIndex(
            self, "IndicePaciente",
            vector_bucket_name=vectores.vector_bucket_name, index_name="paciente-faq",
            data_type="float32", dimension=DIMENSIONES, distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]))
        indice_paciente.add_dependency(vectores)
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject"], resources=[datos.bucket.arn_for_objects(f"{self.prefijo_kb_paciente}/*")]))
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[datos.bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{self.prefijo_kb_paciente}/*"]}}))
        rol_kb.add_to_policy(iam.PolicyStatement(
            actions=["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                     "s3vectors:QueryVectors", "s3vectors:GetIndex", "s3vectors:ListVectors"],
            resources=[indice_paciente.attr_index_arn]))
        self.kb_paciente = bedrock.CfnKnowledgeBase(
            self, "KbPaciente",
            name=f"hlf-paciente-faq-{entorno.nombre}",
            description="Preguntas frecuentes del paciente (F0010). Nunca datos de pacientes",
            role_arn=rol_kb.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=modelo_emb,
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=DIMENSIONES, embedding_data_type="FLOAT32")))),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=indice_paciente.attr_index_arn, vector_bucket_arn=vectores.attr_vector_bucket_arn)),
        )
        self.kb_paciente.node.add_dependency(rol_kb)
        self.fuente_paciente = bedrock.CfnDataSource(
            self, "FuentePaciente",
            knowledge_base_id=self.kb_paciente.attr_knowledge_base_id,
            name="kb-paciente-s3",
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3", s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=datos.bucket.bucket_arn, inclusion_prefixes=[f"{self.prefijo_kb_paciente}/"])),
        )

        kb_arn = self.kb.attr_knowledge_base_arn
        kb_paciente_arn = self.kb_paciente.attr_knowledge_base_arn
        glue = [self.format_arn(service="glue", resource="catalog")]
        for base in BASES_ATHENA:
            glue += [self.format_arn(service="glue", resource="database", resource_name=base),
                     self.format_arn(service="glue", resource="table", resource_name=f"{base}/*")]
        self.politica_consulta = iam.ManagedPolicy(
            self, "PoliticaConsulta", description="Consultar la KB del equipo clínico y Athena (solo lectura) — F0009",
            statements=[
                iam.PolicyStatement(sid="Kb", actions=["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                                    resources=[kb_arn, kb_paciente_arn]),
                iam.PolicyStatement(sid="PerfilModelo", actions=["bedrock:GetInferenceProfile"],
                                    resources=[self.format_arn(service="bedrock", resource="inference-profile",
                                                               resource_name="*")]),
                iam.PolicyStatement(sid="Athena", actions=[
                    "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
                    "athena:StopQueryExecution", "athena:GetWorkGroup"],
                    resources=[self.format_arn(service="athena", resource="workgroup", resource_name=entorno.workgroup)]),
                iam.PolicyStatement(sid="Catalogo", actions=["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable",
                                                             "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"],
                                    resources=glue),
                iam.PolicyStatement(sid="ResultadosAthena", actions=["s3:PutObject", "s3:GetObject",
                                                                     "s3:AbortMultipartUpload"],
                                    resources=[datos.bucket.arn_for_objects("athena-resultados/*")]),
                iam.PolicyStatement(sid="ListarBucket", actions=["s3:ListBucket", "s3:GetBucketLocation"],
                                    resources=[datos.bucket.bucket_arn]),
            ])
        self.politica_preparacion = iam.ManagedPolicy(
            self, "PoliticaPreparacion", description="Subir los documentos de la KB y sincronizarla — F0009",
            statements=[
                iam.PolicyStatement(sid="Documentos", actions=["s3:PutObject", "s3:GetObject"],
                                    resources=[datos.bucket.arn_for_objects(f"{self.prefijo_kb}/*"),
                                               datos.bucket.arn_for_objects(f"{self.prefijo_kb_paciente}/*")]),
                iam.PolicyStatement(sid="Ingesta", actions=["bedrock:StartIngestionJob", "bedrock:GetIngestionJob"],
                                    resources=[kb_arn, kb_paciente_arn]),
            ])

        if datos.clave is not None:        # F0013: bucket con clave propia → leer y escribir requiere la clave
            datos.clave.grant_decrypt(rol_kb)
            kms_datos = iam.PolicyStatement(sid="ClaveDatos", actions=["kms:Decrypt", "kms:GenerateDataKey"],
                                            resources=[datos.clave.key_arn])
            self.politica_consulta.add_statements(kms_datos)
            self.politica_preparacion.add_statements(kms_datos)

        CfnOutput(self, "SalidaKb", value=self.kb.attr_knowledge_base_id)
        CfnOutput(self, "SalidaFuenteKb", value=self.fuente.attr_data_source_id)
        CfnOutput(self, "SalidaKbPaciente", value=self.kb_paciente.attr_knowledge_base_id)
