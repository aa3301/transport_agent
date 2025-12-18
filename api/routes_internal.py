from fastapi import APIRouter, HTTPException
from models.plan import AgentPlan

router = APIRouter()

@router.post("/agent/plan")
async def submit_plan(plan: AgentPlan):
    """Internal: submit plan for agent execution"""
    try:
        return {"message": "Plan received", "plan": plan}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
