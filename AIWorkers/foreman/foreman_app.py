import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC = Path(__file__).parent / "static"
COOKIE = "foreman_session"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
ERRORS = {ValueError: 400, LookupError: 404, RuntimeError: 409}


class NewTaskBody(BaseModel):
    kind: str
    target: str
    name: str = ""


class TaskEditBody(BaseModel):
    name: str | None = None
    notes: str | None = None
    active: bool | None = None
    deployed: str | None = None  # "2026-10-26", or "" to move it back to Ongoing Jobs


class ScheduleBody(BaseModel):
    enabled: bool
    start: str
    end: str
    days: list[int]
    mode: str = "window"  # or "until_awake"


class ChatHoldBody(BaseModel):
    minutes: int = 5


class StretchBody(BaseModel):
    minutes: int


class RestBody(BaseModel):
    minutes: int


class RunBody(BaseModel):
    minutes: int = 0
    until: str = ""


def create_app(foreman) -> FastAPI:
    app = FastAPI(title="Foreman", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    _add_pages(app, foreman)
    _add_api(app, foreman)
    for kind, status in ERRORS.items():  # refusals reach the page as readable messages
        app.add_exception_handler(kind, lambda request, error, status=status: JSONResponse({"detail": str(error)}, status_code=status))
    return app


def _signed_in(request: Request, token: str) -> bool:
    # Same guard as the Warden: only Ben's local browser, holding the session cookie
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    return host in LOCAL_HOSTS and secrets.compare_digest(request.cookies.get(COOKIE, ""), token)


def _add_pages(app: FastAPI, foreman) -> None:
    @app.get("/login")
    def login(token: str = ""):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
        return response

    @app.get("/")
    def page(request: Request):
        if not _signed_in(request, foreman.token):
            return HTMLResponse("<p>The Foreman needs its login link: see data/foreman_login.txt.</p>", status_code=401)
        return FileResponse(STATIC / "foreman.html", headers={"Cache-Control": "no-cache"})


def _add_api(app: FastAPI, foreman) -> None:
    def guard(request: Request) -> None:
        if not _signed_in(request, foreman.token):
            raise HTTPException(401, "Open the Foreman login link first.")

    @app.get("/api/state")
    def state(request: Request):
        guard(request)
        return foreman.state()

    @app.get("/api/busy")
    def busy(request: Request):
        # For the Minis' Bit, who has no cookie: only whether a worker is running, and only to this machine. The GPU desk
        # can't tell him, because a task Ben runs by hand never takes a lease there
        if (request.client.host if request.client else "") not in {"127.0.0.1", "::1"}:
            raise HTTPException(403, "Only from this machine.")
        return {"running": foreman.run.running()}

    @app.post("/api/tasks")
    def add_task(body: NewTaskBody, request: Request):
        guard(request)
        foreman.add_task(body.kind, body.target, body.name)
        return foreman.state()

    @app.patch("/api/tasks/{task_id}")
    def edit_task(task_id: int, body: TaskEditBody, request: Request):
        guard(request)
        foreman.tasks.update(task_id, **body.model_dump(exclude_none=True))
        return foreman.state()

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int, request: Request):
        guard(request)
        if foreman.run.running() and foreman.run.task.id == task_id:
            raise RuntimeError("Stop that task before deleting it.")
        foreman.tasks.delete(task_id)
        return foreman.state()

    @app.post("/api/tasks/{task_id}/run")
    def run(task_id: int, body: RunBody, request: Request):
        guard(request)
        foreman.run_now(task_id, body.minutes, body.until)
        return foreman.state()

    @app.get("/api/tasks/{task_id}/results")
    def results(task_id: int, request: Request):
        guard(request)
        return {"text": foreman.results(task_id)}

    @app.post("/api/free-time")
    def free_time(body: RunBody, request: Request):
        guard(request)
        foreman.give_time(body.minutes)
        return foreman.state()

    @app.post("/api/stop")
    def stop(request: Request):
        guard(request)
        foreman.stop()
        return foreman.state()

    @app.post("/api/stretch")
    def stretch(body: StretchBody, request: Request):
        guard(request)
        foreman.stretch(body.minutes)
        return foreman.state()

    @app.post("/api/chat-hold")
    def chat_hold(body: ChatHoldBody, request: Request):
        guard(request)
        foreman.hold_for_chat(body.minutes)
        return {"ok": True}

    @app.post("/api/chat-hold/end")
    def end_chat_hold(request: Request):
        guard(request)
        foreman.end_chat_hold()
        return {"ok": True}

    @app.put("/api/schedule")
    def schedule(body: ScheduleBody, request: Request):
        guard(request)
        try:
            foreman.settings.set_schedule(body.enabled, body.start, body.end, body.days, body.mode)
        except ValueError as error:
            raise HTTPException(400, str(error) if "mode" in str(error) else "Times are HH:MM, like 03:00.")
        return foreman.state()

    @app.put("/api/rest")
    def rest(body: RestBody, request: Request):
        guard(request)
        try:
            foreman.settings.set_rest(body.minutes)
        except ValueError as error:
            raise HTTPException(400, str(error))
        return foreman.state()
