from app.agents.runtime import OpenAIAgentsRuntime
from app.db.models import ResearchIdea, WorkflowLink


def test_openai_agents_runtime_starts_temporal_research_workflow(db):
    idea = ResearchIdea(title="Agent Runtime Idea", thesis="test", universe="US equities")
    db.add(idea)
    db.flush()

    result = OpenAIAgentsRuntime().run_research_workflow(db, idea.id)

    assert result["workflow_type"] == "ResearchWorkflow"
    assert idea.status == "RESEARCHING"
    link = db.query(WorkflowLink).filter_by(workflow_id=result["workflow_id"]).one()
    assert link.meta["input"]["agent_runtime"] == "openai_agents_sdk_temporal_activity"
