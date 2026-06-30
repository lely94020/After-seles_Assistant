from pydantic import BaseModel, field_serializer

from app.core.data_mask import mask_phone


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    user_type: str = "end_user"
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    user_type: str
    company_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}

    @field_serializer("phone")  #单独控制phone字段输出格式
    @classmethod
    def _mask_phone(cls, v: str | None) -> str | None:
        return mask_phone(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
