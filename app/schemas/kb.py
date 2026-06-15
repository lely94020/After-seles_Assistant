from pydantic import BaseModel

class DocumentResponse(BaseModel):
    id:int
    title:str
    doc_type:str
    product_model:str|None=None
    chunk_count:int
    status:str

    model_config = {"from_attributes":True}

class ChunkResponse(BaseModel):
    id:int
    chunk_index:int
    content:str
    chunk_type:str
    parent_title:str|None=None
    token_count:int|None=None

    model_config = {"from_attributes":True}

class DocumentDetailResponse(DocumentResponse):
    chunks:list[ChunkResponse]=[]