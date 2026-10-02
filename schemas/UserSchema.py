from pydantic import BaseModel

class UserCreate(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    role: str
    password: str