import re
from collections import defaultdict

from sqlalchemy import  text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.milvus_client import get_milvus_client,COLLECTION_NAME
from app.models.kb import KbDocument
from app.services.embedding_service import EmbeddingService

# 提取型号的正则（海康型号格式：字母开头+连字符+数字）
_MODEL_PATTERN_STANDARD=re.compile(r"[A-Za-z]{2,}-[\w-]+")  #用于将正则表达式字符串编译成一个正则表达式对象

# 宽松匹配：字母数字混合长度≥4的词（如 H100、7608N-K2、小米300）
_MODEL_PATTERN_LOOSE = re.compile(r"\b[A-Za-z0-9\u4e00-\u9fff]{2,}?\d+[A-Za-z0-9\u4e00-\u9fff-]*\b")


def extract_model(text: str) -> str | None:
    # 优先标准格式
    m = _MODEL_PATTERN_STANDARD.search(text)
    if m:
        return m.group()
    # 宽松匹配兜底
    m = _MODEL_PATTERN_LOOSE.search(text)
    if m:
        return m.group()
    return None

class HybridSearchService:
    def __init__(self,db:AsyncSession):
        self.db=db

    async def search(
            self,
            query:str,
            model_number:str|None=None,
            top_k:int=10,
            k_rrf:int=60
    )->list[dict]:
        """
        混合检索 + RRF 融合 + 业务规则加权
        返回: [{"chunk_id", "content", "document_id", "model_number",
         "score", "sources":["vector"|"keyword"]}, ...]
        """

        #如果意图分类已给型号就用，否则从问题中自己提取
        if not model_number:
            model_number=extract_model(query)
            # 非标准格式的型号去 Device 表校验，查不到就丢弃
            if model_number and not _MODEL_PATTERN_STANDARD.match(model_number):
                from sqlalchemy import select
                from app.models.device import Device
                r = await self.db.execute(
                    select(Device.id).where(Device.model_number ==model_number)
                )
                if r.scalar_one_or_none() is None:
                    model_number = None
        #向量检索
        query_embedding=EmbeddingService.embed_single(query)
        milvus=get_milvus_client()
        vector_hits=milvus.search(
            collection_name=COLLECTION_NAME,
            data=[query_embedding],
            limit=top_k,
            output_fields=["chunk_id","content","document_id","parent_title","product_series","doc_version"]
        )

        #关键词检索（MySQL LIKE + 型号精确匹配）
        keyword_hits=await self._keyword_search(query,model_number,top_k)

        #RRF融合
        doc_chunks:dict[int,dict]={}    # chunk_id -> chunk info
        rrf_scores:dict[int,float]=defaultdict(float)

        for rank,hit in enumerate(vector_hits[0]):
            entity=hit.get("entity",{})
            chunk_id=hit["id"]
            doc_chunks[chunk_id]={
                "chunk_id":chunk_id,
                "content":entity.get("content",""),
                "document_id":entity.get("document_id",0),
                "parent_title":entity.get("parent_title",""),
                "sources":["vector"] #记录了该块是被哪路检索召回的
            }
            rrf_scores[chunk_id]+=1.0/(k_rrf+rank+1)

        for rank,row in enumerate(keyword_hits):
            chunk_id=row.chunk_id
            rrf_scores[chunk_id]+=1.0/(k_rrf+rank+1)
            if chunk_id not in doc_chunks:
                doc_chunks[chunk_id]={
                    "chunk_id":chunk_id,
                    "content":row.content,
                    "document_id":row.document_id,
                    "parent_title":row.parent_title or "",
                    "sources":["keyword"]
                }
            else:
                doc_chunks[chunk_id]["sources"].append("keyword")

        #查询文档信息用于业务加权
        doc_ids=list(c["document_id"] for c in doc_chunks.values())
        doc_info_map={}
        if doc_ids:
            from sqlalchemy import select
            r=await self.db.execute(
                select(KbDocument.id,KbDocument.product_model,
                       KbDocument.product_series,KbDocument.status)
                .where(KbDocument.id.in_(doc_ids))
            )
            doc_info_map={row[0]:row for row in r.all()}

        #业务规则加权
        for chunk_id,score in rrf_scores.items():
            info=doc_chunks[chunk_id]
            doc_id=info["document_id"]
            doc_info=doc_info_map.get(doc_id)

            if doc_info:
                mn=doc_info[1]
                series=doc_info[2]
                status=doc_info[3]

                #型号精准命中 x1.5
                if model_number and mn and mn.strip().upper()==model_number.strip().upper():
                    rrf_scores[chunk_id]=score*1.5
                #系列命中 x1.2
                elif model_number and series and model_number[:3] in series:
                    rrf_scores[chunk_id]=score*1.2
                #过期降权
                if status=="expired":
                    rrf_scores[chunk_id]*=0.3

        #排序列 top-N
        sorted_chunks=sorted(rrf_scores.items(),key=lambda x:x[1],reverse=True)
        results=[]
        for chunk_id,score in sorted_chunks[:top_k]:
            r=doc_chunks[chunk_id]
            r["score"]=round(score,4)
            results.append(r)
        return results

    async def _keyword_search(
            self,query:str,model_number:str|None,limit:int
    )->list:
        """MySQL关键词检索"""
        conditions=[]
        params={}

        if model_number:
            conditions.append("content LIKE :model")
            params["model"]=f"%{model_number}%"

        #提取问题中的关键中文词做LIKE
        keywords=re.findall(r"[\u4e00-\u9fff]{2,}",query)
        if keywords:
            like_clauses=[]
            for i,kw in enumerate(keywords[:3]):    #最多取3个关键词
                key=f"kw{i}"
                like_clauses.append(f"content LIKE :{key}")
                params[key]=f"%{kw}%"
            if like_clauses:
                conditions.append(f"({' OR '.join(like_clauses)})")

        if not conditions:
            return []

        sql=f"""
        SELECT id AS chunk_id,content,document_id,parent_title
        FROM kb_chunks
        WHERE {' AND '.join(conditions)}
        LIMIT :limit
        """
        params["limit"]=limit

        r=await self.db.execute(text(sql),params)   #通过 :param 占位符传入字典 params 中防止 SQL 注入
        return r.fetchall() #获得所有行原始数据