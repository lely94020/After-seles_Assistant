from datetime import datetime
from pydantic import BaseModel

class MessageResponse(BaseModel):
    id:int
    role:str
    content:str
    citations:list|None=None    #引文
    confidence:float|None=None
    created_at:datetime|None=None

    model_config = {"from_attributes":True}

class ConversationResponse(BaseModel):
    id:int
    title:str
    status:str
    intent:str|None=None
    key_facts:dict|None=None
    step_index:int
    user_type:str|None=None
    created_at:datetime|None=None
    updated_at:datetime|None=None

    model_config = {"from_attributes":True}

class ConversationDetailResponse(ConversationResponse):
    messages:list[MessageResponse]=[]

class ChatWithContextRequest(BaseModel):
    question:str