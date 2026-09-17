from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "tasks.html")


@router.get("/tasks/new", response_class=HTMLResponse)
def new_task_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "task_form.html")


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_details_page(request: Request, task_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "task_details.html")


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_page(request: Request, task_id: int) -> HTMLResponse:
    return templates.TemplateResponse(request, "task_form.html")


@router.get("/daily-update", response_class=HTMLResponse)
def daily_update_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "daily_update.html")


@router.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "performance.html")


@router.get("/manager", response_class=HTMLResponse)
def manager_dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "manager_dashboard.html")


@router.get("/manager/assistant", response_class=HTMLResponse)
def ai_assistant_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "ai_assistant.html")


@router.get("/manager/import-export", response_class=HTMLResponse)
def import_export_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "import_export.html")


@router.get("/manager/daily-report", response_class=HTMLResponse)
def daily_report_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "daily_report.html")
