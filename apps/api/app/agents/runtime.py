from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ResearchIdea
from app.services.workflows import start_workflow


class OpenAIAgentsRuntime:
    def run_research_workflow(self, db: Session, research_idea_id: str) -> dict[str, str]:
        idea = db.get(ResearchIdea, research_idea_id)
        if not idea:
            raise ValueError("research idea not found")
        idea.status = "RESEARCHING"
        return start_workflow(
            db,
            "ResearchWorkflow",
            "research_idea",
            research_idea_id,
            {"research_idea_id": research_idea_id, "agent_runtime": "openai_agents_sdk_temporal_activity"},
        )
