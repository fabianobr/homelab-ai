from pydantic.v2 import BaseModel, Field

class TodoBase(BaseModel):
    title: str
    description: str | None = None
    done: bool = False

class TodoCreate(TodoBase):
    pass

class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    done: bool | None = None

class Todo(TodoBase):
    id: int = Field(default_factory=int)

#