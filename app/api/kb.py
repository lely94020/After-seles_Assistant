from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query

from app.schemas.kb import DocumentResponse, DocumentDetailResponse, ScanExpiredResponse, StatusUpdateRequest, TopReferencedResponse
from app.services.kb_service import KbService

router=APIRouter()

@router.post("/upload",response_model=DocumentResponse)
async def upload(
        file:UploadFile=File(...),
        title:str=Form(...),
        doc_type:str=Form(...),
        product_model:str|None=Form(None),
        product_series:str|None=Form(None),
        replace_doc_id:int|None=Form(None),
        svc:KbService=Depends(),
)->DocumentResponse:
    doc=await svc.upload(
        file,title,doc_type,
        product_model,product_series,
        replace_doc_id
    )
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

@router.get("/top-referenced", response_model=list[TopReferencedResponse])
async def top_referenced(
        limit: int = Query(10, ge=1, le=50),
        svc: KbService = Depends(),
):
    """高频引用文档统计，用于预警重要文档过期"""
    docs = await svc.get_top_referenced(limit)
    return [TopReferencedResponse.model_validate(d) for d in docs]

@router.post("/scan-expired", response_model=ScanExpiredResponse)
async def scan_expired(
        svc: KbService = Depends(),
) -> ScanExpiredResponse:
    """手动触发过期扫描（>90天 → review_due，>180天 expired → archived）"""
    result = await svc.scan_expired()
    return ScanExpiredResponse(**result)

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

    # ========== 管理员：生命周期管理 ==========


@router.patch("/{doc_id}/status", response_model=DocumentResponse)
async def update_status(
        doc_id: int,
        body: StatusUpdateRequest,
        svc: KbService = Depends(),
) -> DocumentResponse:
    """管理员手动修改文档状态（active / review_due / expired / archived）"""
    doc = await svc.update_status(doc_id, body.status)
    return DocumentResponse.model_validate(doc)


@router.post("/{doc_id}/renew", response_model=DocumentResponse)
async def renew_document(
        doc_id: int,
        svc: KbService = Depends(),
) -> DocumentResponse:
    """管理员确认文档仍有效，重置 updated_at 并恢复 active"""
    doc = await svc.renew_document(doc_id)
    return DocumentResponse.model_validate(doc)





