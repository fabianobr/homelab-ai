from fastapi import APIRouter, HTTPException
from typing import List
from models import Todo, TodoCreate, TodoUpdate

router = APIRouter()
todo_store = {}
last_id = 0

@router.post("/todos", status_code=201, response_model=Todo)
def create_todo(todo: TodoCreate):
    global last_id
    last_id += 1
    new_todo = Todo(id=last_id, **todo.model_dump())
    todo_store[last_id] = new_todo
    return new_todo

@router.get("/todos", response_model=List[Todo])
def read_todos():
    return list(todo_store.values())

@router.get("/todos/{todo_id}", response_model=Todo)
def read_todo(todo_id: int):
    if todo_id not in todo_store:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo_store[todo_id]

@router.put("/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: int, todo_update: TodoUpdate):
    if todo_id not in todo_store:
        raise HTTPException(status_code=404, detail="Todo not found")
    stored_todo = todo_store[todo_id]
    updated_data = todo_update.model_dump(exclude_unset=True)
    updated_todo = stored_todo.model_copy(update=updated_data)
    todo_store[todo_id] = updated_todo
    return updated_todo

@router.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: int):
    if todo_id not in todo_store:
        raise HTTPException(status_code=404, detail="Todo not found")
    del todo_store[todo_id]

#