from dashscope import TextEmbedding

from app.config import settings

BATCH_SIZE = 25


class EmbeddingService:
    @staticmethod
    def embed_single(text: str) -> list[float]:
        """"单个文本转向量"""
        resp = TextEmbedding.call(
            model=TextEmbedding.Models.text_embedding_v2,
            input=text,
            api_key=settings.DASHSCOPE_API_KEY
        )
        if resp.status_code != 200:
            raise RuntimeError(f"向量化失败：{resp.message}")
        return resp.output["embeddings"][0]["embedding"]

    @staticmethod
    def embed_batch(texts: list[str]) -> list[list[float]]:
        """"
        因为 DashScope API 单次请求有上限
        如果文档分块后是 80 块，会自动拆成 25 + 25 + 25 + 5 四次请求
        批量转向量，25条分一组切分
        """
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            resp = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v2,
                input=batch,
                api_key=settings.DASHSCOPE_API_KEY
            )
            if resp.status_code != 200:
                raise RuntimeError(f"向量化失败：{resp.message}")
            for emb in resp.output["embeddings"]:
                all_embeddings.append(emb["embedding"])
        return all_embeddings
