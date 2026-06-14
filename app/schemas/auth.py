from pydantic import BaseModel

class LoginRequest(BaseModel):
    username:str
    password:str

class RegisterRequest(BaseModel):
    username:str
    password:str
    user_type:str="end_user"
    company_name:str|None=None
    email:str|None=None
    phone:str|None=None

class UserResponse(BaseModel):
    id:int
    username:str
    user_type:str
    company_name:str|None=None
    email:str|None=None
    phone:str|None=None
    is_active:bool

    model_config = {"from_attributes":True}
    #它允许你直接 UserResponse.model_validate(orm_user_object)，Pydantic 会自动从 ORM 对象的属性中提取值，不用手动一个一个复制

class TokenResponse(BaseModel):
    access_token:str
    token_type:str="bearer"
    user:UserResponse