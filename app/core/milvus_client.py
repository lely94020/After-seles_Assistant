from pymilvus import MilvusClient
from pymilvus import DataType

from app.config import settings

COLLECTION_NAME = "kb_chunks"
EMBEDDING_DIM = 1536

_milvus_client: MilvusClient | None = None


def get_milvus_client() -> MilvusClient:
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(uri=f"http://{settings.MILVUS_HOST}")
        _init_collection(_milvus_client)
    return _milvus_client


def _init_collection(client: MilvusClient) -> None:
    if client.has_collection(COLLECTION_NAME):
        return

    # 手动定义 schema，确保能存额外字段（content、chunk_type 等）
    schema = client.create_schema(
        auto_id=False,
        enable_dynamic_field=True,  # 允许存 content、parent_title 等自定义字段,方便搜索时直接取出，不用再回 MySQL 查
    )
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
    schema.add_field(field_name="chunk_id", datatype=DataType.INT64)

    # 准备索引参数（加速搜索）
    # IVF_FLAT + COSINE = 一种索引算法 + 余弦相似度计算方式，用于加速"找最相似向量"
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 128}
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params
    )
