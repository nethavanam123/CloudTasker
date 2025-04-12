import os
from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict
from fastapi import FastAPI, Request, Form, HTTPException, Depends, status, Path
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import google.oauth2.id_token
from google.auth.transport import requests
from google.cloud import firestore
import starlette.status as status
from datetime import timedelta


# Firebase Admin SDK JSON key
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "firebase-key2.json"

# Initialize FastAPI app
app = FastAPI()

# Firestore setup
firestore_db = firestore.Client()
firebase_request_adapter = requests.Request()

# Static + template setup
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ------------------------
# Helper: Auth + Firestore
# ------------------------
def get_user_from_token(id_token_str: str):
    try:
        claims = google.oauth2.id_token.verify_firebase_token(id_token_str, firebase_request_adapter)

        # Token expiration time and grace period (e.g., 5 minutes)
        expiration_time = datetime.utcfromtimestamp(claims["exp"])
        grace_period = timedelta(minutes=5)
        current_time = datetime.utcnow()

        # If the token is within the grace period of expiration, allow it
        if current_time < expiration_time + grace_period:
            print("Token is within the grace period.")
        else:
            raise HTTPException(status_code=401, detail="Token expired")

        user_id = claims["user_id"]
        user_doc_ref = firestore_db.collection("users").document(user_id)

        if not user_doc_ref.get().exists:
            user_doc_ref.set({
                "name": "New User",
                "email": claims.get("email", ""),
            })

        user_data = user_doc_ref.get().to_dict()
        user_data["id"] = user_id
        return user_data

    except Exception as e:
        print(f"Error verifying token or fetching user: {e}")
        raise HTTPException(status_code=401, detail="Token verification failed")

def get_current_user(request: Request):
    # Extract the token from the Authorization header
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    # The token should be in the format "Bearer <token>"
    token = auth_header.split("Bearer ")[-1]
    
    try:
        # Verify the token with Firebase Auth
        decoded_token = auth.verify_id_token(token)
        user_id = decoded_token.get("uid")
        
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {"user_id": user_id}

    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ------------------------
# Routes
# ------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    id_token = request.cookies.get("token")
    user = None
    boards = []

    if id_token:
        try:
            user = get_user_from_token(id_token)
            if user:
                user_id = user["id"]
                created_boards = firestore_db.collection("task_boards") \
                    .where("created_by", "==", user_id).stream()

                member_boards = firestore_db.collection("task_boards") \
                    .where("members", "array_contains", user_id).stream()

                boards = [
                    {"id": doc.id, **doc.to_dict()}
                    for doc in list(created_boards) + list(member_boards)
                ]
        except HTTPException as e:
            return HTMLResponse(f"Error: {e.detail}", status_code=e.status_code)

    return templates.TemplateResponse("main.html", {
        "request": request,
        "user": user,
        "boards": boards
    })



@app.get("/create-task-board", response_class=HTMLResponse)
async def create_board_form(request: Request):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse("create_task_board.html", {
        "request": request,
        "user": user
    })


@app.post("/create-task-board")
async def create_board_post(request: Request):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

    form = await request.form()
    title = form["title"]

    # Check for existing board with the same title for this user
    existing_boards = firestore_db.collection("task_boards")\
        .where("title", "==", title)\
        .where("created_by", "==", user["id"]).stream()

    if any(existing_boards):
        # Redirect back or raise an error - here we redirect to home with query param for feedback
        return RedirectResponse("/?error=duplicate_board_title", status_code=302)

    board_id = str(uuid4())

    board_data = {
        "title": title,
        "created_by": user["id"],
        "created_at": firestore.SERVER_TIMESTAMP,
        "members": []  # For invited users
    }

    firestore_db.collection("task_boards").document(board_id).set(board_data)

    return RedirectResponse(f"/task-board/{board_id}", status_code=302)


@app.get("/task-board/{board_id}", response_class=HTMLResponse)
async def view_board(request: Request, board_id: str):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        return RedirectResponse("/", status_code=302)

    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=404, detail="Board not found")

    board_data = board_doc.to_dict()
    board_data["id"] = board_doc.id

    tasks_query = firestore_db.collection("tasks").where("board_id", "==", board_id)
    tasks = [t.to_dict() | {"id": t.id} for t in tasks_query.stream()]

    # Fetch user documents for members
    members = board_data.get("members", [])
    users_map = {}
    for member_id in members:
        user_doc = firestore_db.collection("users").document(member_id).get()
        if user_doc.exists:
            users_map[member_id] = user_doc.to_dict()

    return templates.TemplateResponse("task_board.html", {
        "request": request,
        "user": user,
        "board": board_data,
        "tasks": tasks,
        "users_map": users_map,
    })



# Add user to board (only by creator)
@app.post("/task-board/{board_id}/add-user")
async def add_user_to_board(request: Request, board_id: str, user_email: str = Form(...)):
    # Get the Firebase token from cookies
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    # Ensure requester is authenticated
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Reference to the board
    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    # Check board existence
    if not board_doc.exists:
        raise HTTPException(status_code=404, detail="Board not found")

    board_data = board_doc.to_dict()

    # Only allow the board creator to add users
    if board_data["created_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the board creator can add users")

    # Lookup user by email from 'users' collection
    users_ref = firestore_db.collection("users")
    user_query = users_ref.where("email", "==", user_email).limit(1).stream()
    user_to_add = next(user_query, None)

    if not user_to_add:
        raise HTTPException(status_code=404, detail="User with that email not found")

    user_to_add_id = user_to_add.id

    # Add user to 'members' if not already included
    if user_to_add_id not in board_data.get("members", []):
        board_ref.update({
            "members": firestore.ArrayUnion([user_to_add_id])
        })

    # Redirect back to board page
    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)


# Remove user from board (only by the creator)
@app.post("/task-board/{board_id}/remove-user")
async def remove_user_from_board(request: Request, board_id: str, user_email: str = Form(...)):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=404, detail="Board not found")

    board_data = board_doc.to_dict()

    if board_data["created_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the board creator can remove users")

    # Find user by email
    users_ref = firestore_db.collection("users")
    user_query = users_ref.where("email", "==", user_email).limit(1).stream()
    user_to_remove = next(user_query, None)

    if not user_to_remove:
        raise HTTPException(status_code=404, detail="User with that email not found")

    user_id_to_remove = user_to_remove.id

    # Prevent removing the board creator
    if user_id_to_remove == board_data["created_by"]:
        raise HTTPException(status_code=400, detail="Cannot remove the board creator")

    # Remove user from board
    board_ref.update({
        "members": firestore.ArrayRemove([user_id_to_remove])
    })

    # Unassign any tasks assigned to this user
    tasks = firestore_db.collection("tasks") \
        .where("board_id", "==", board_id) \
        .where("assigned_to", "==", user_id_to_remove).stream()

    for task in tasks:
        firestore_db.collection("tasks").document(task.id).update({
            "assigned_to": None,
            "unassigned_due_to_removal": True
        })

    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)



# Rename board (only by creator)
@app.post("/task-board/{board_id}/rename")
async def rename_board(request: Request, board_id: str, new_title: str = Form(...)):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=404, detail="Board not found")

    board_data = board_doc.to_dict()

    if board_data["created_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the board creator can rename the board")

    # Update the title
    board_ref.update({"title": new_title})

    # Redirect back to the task board view
    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)

   
@app.post("/task-board/{board_id}/add-task")
async def add_task(request: Request, board_id: str, title: str = Form(...), due_date: str = Form(...)):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

    # Validate and parse due date
    try:
        due_date_obj = datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Verify board exists
    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()
    if not board_doc.exists:
        raise HTTPException(status_code=404, detail="Board not found")

    board_data = board_doc.to_dict()

    # Check permission
    if user["id"] != board_data["created_by"] and user["id"] not in board_data.get("members", []):
        raise HTTPException(status_code=403, detail="Not authorized to add tasks to this board")

    # Create the task
    task_data = {
        "title": title,
        "due_date": due_date_obj,
        "completed": False,
        "completed_at": None,
        "board_id": board_id,
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_by": user["id"]
    }

    firestore_db.collection("tasks").add(task_data)

    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)


@app.post("/task/{task_id}/complete")
async def complete_task(request: Request, task_id: str):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

    task_ref = firestore_db.collection("tasks").document(task_id)
    task_doc = task_ref.get()

    if not task_doc.exists:
        raise HTTPException(status_code=404, detail="Task not found")

    task_ref.update({
        "completed": True,
        "completed_at": datetime.utcnow()
    })

    task_data = task_doc.to_dict()
    return RedirectResponse(f"/task-board/{task_data['board_id']}", status_code=status.HTTP_302_FOUND)


templates = Jinja2Templates(directory="templates")

def datetimeformat(value, format="%B %d, %Y"):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

templates.env.filters["datetimeformat"] = datetimeformat       

# Add edit task route
@app.post("/task-board/{board_id}/tasks/{task_id}")
async def edit_task(
    request: Request,
    board_id: str,
    task_id: str,
    title: str = Form(...),
    description: str = Form(""),
    assigned_to: str = Form(""),
    due_date: str = Form(...)
):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user_id = user["id"]

    # Get the board document to verify permissions
    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

    board_data = board_doc.to_dict()

    if user_id != board_data.get("created_by") and user_id not in board_data.get("members", []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    # Get the task document
    task_ref = firestore_db.collection("tasks").document(task_id)
    task_doc = task_ref.get()

    if not task_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task_data = task_doc.to_dict()

    if task_data["board_id"] != board_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not belong to this board")

    try:
        due_date_obj = datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format")

    update_data = {
        "title": title,
        "description": description,
        "assigned_to": assigned_to,
        "due_date": due_date_obj,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    task_ref.update(update_data)

    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)



# Add delete task route
@app.post("/task-board/{board_id}/tasks/{task_id}/delete")
async def delete_task(
    request: Request,
    board_id: str,
    task_id: str,
):
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user_id = user["id"]

    # Verify board exists
    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

    board_data = board_doc.to_dict()

    if user_id != board_data.get("created_by") and user_id not in board_data.get("members", []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this task")

    # Get task reference (root-level collection like in edit)
    task_ref = firestore_db.collection("tasks").document(task_id)
    task_doc = task_ref.get()

    if not task_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task_data = task_doc.to_dict()

    if task_data["board_id"] != board_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not belong to this board")

    # Delete the task
    task_ref.delete()

    return RedirectResponse(f"/task-board/{board_id}", status_code=status.HTTP_302_FOUND)


# Board Deletion
@app.post("/task-board/{board_id}/delete")
async def delete_task_board(request: Request, board_id: str):
    # Retrieve token from cookies
    id_token = request.cookies.get("token")
    user = get_user_from_token(id_token) if id_token else None

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user_id = user["id"]

    # Reference the board in Firestore
    board_ref = firestore_db.collection("task_boards").document(board_id)
    board_doc = board_ref.get()

    if not board_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

    board_data = board_doc.to_dict()

    # Only creator can delete the board
    if board_data.get("created_by") != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the creator can delete this board")

    # Board must not have other members
    if len(board_data.get("members", [])) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Board has other users")

    # Board must not have tasks
    task_check = firestore_db.collection("tasks").where("board_id", "==", board_id).limit(1).get()
    if task_check:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Board still has tasks")

    # Delete the board
    board_ref.delete()

    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)



