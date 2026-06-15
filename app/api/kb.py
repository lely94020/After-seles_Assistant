from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query

from app.schemas.kb import DocumentResponse, DocumentDetailResponse
from app.services.kb_service import KbService

router=APIRouter()

@router.post("/upload",response_model=DocumentResponse)
async def upload(
        file:UploadFile=File(...),
        title:str=Form(...),
        doc_type:str=Form(...),
        product_model:str|None=Form(None),
        product_series:str|None=Form(None),
        svc:KbService=Depends(),
)->DocumentResponse:
    doc=await svc.upload(file,title,doc_type,product_model,product_series)
    return DocumentResponse.model_validate(doc)

@router.get("/search")
async def search_chunks(
        q:str=Query(...,description="搜索关键词或问题"),
        top_k:int=Query(5,ge=1,le=20),
        svc:KbService=Depends()
):
    """语义搜索知识库"""
    hits=await svc.search_chunks(q,top_k)
    return {"query":q,"results":hits}

@router.get("/{doc_id}",response_model=DocumentDetailResponse)
async def get_document(doc_id:int,svc:KbService=Depends())->DocumentDetailResponse:
    doc=await svc.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404,detail="文档不存在")
    return DocumentDetailResponse.model_validate(doc)

@router.get("/",response_model=list[DocumentResponse])
async def list_docs(skip:int=0,limit:int=20,svc:KbService=Depends()):
    docs=await svc.list_documents(skip,limit)
    return [DocumentResponse.model_validate(d) for d in docs]