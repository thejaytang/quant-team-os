from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runtime import OpenAIAgentsRuntime
from app.api.compat import APIRouter, Depends, HTTPException
from app.core.auth import require_any_role
from app.db.models import ResearchIdea
from app.db.session import get_db
from app.schemas import ResearchIdeaCreate
from app.services.audit import write_audit_log

router = APIRouter(prefix="/api/v1/research-ideas", tags=["research"])


@router.post("")
def create_research_idea(payload: ResearchIdeaCreate, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    idea = ResearchIdea(**payload.model_dump())
    db.add(idea)
    db.flush()
    write_audit_log(db, "research_idea.created", "research_idea", idea.id, payload.model_dump(), actor=payload.proposed_by)
    return idea


@router.get("")
def list_research_ideas(db: Session = Depends(get_db)):
    return db.scalars(select(ResearchIdea).order_by(ResearchIdea.created_at.desc())).all()


@router.get("/{idea_id}")
def get_research_idea(idea_id: str, db: Session = Depends(get_db)):
    idea = db.get(ResearchIdea, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="research idea not found")
    return idea


@router.post("/{idea_id}/start-agent-workflow")
def start_agent_workflow(idea_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    return start_research_workflow(idea_id, db, _user)


@router.post("/{idea_id}/start-workflow")
def start_research_workflow(idea_id: str, db: Session = Depends(get_db), _user=Depends(require_any_role("researcher", "admin"))):
    try:
        return OpenAIAgentsRuntime().run_research_workflow(db, idea_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="research idea not found") from exc
