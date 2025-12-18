# api/routes_user.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from core.singleton import supervisor_agent, subscription_service, fleet_service
from models.schemas import AskRequest, SubscribeRequest
from core.auth import get_current_user
from core.response import ok, error

router = APIRouter()

@router.post("/ask")
async def ask(req: AskRequest, user: dict = Depends(get_current_user)):
    """Ask the multi-agent system a natural-language query."""
    try:
        result = await supervisor_agent.handle_user_query(req.query)
        # return only the user-facing answer
        if isinstance(result, dict) and "answer" in result:
            return ok(result["answer"])
        return ok(result)
    except Exception as e:
        # centralized exception handler should catch this in production
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/subscribe")
async def subscribe(sub: SubscribeRequest, user: dict = Depends(get_current_user)):
    try:
        # reuse existing in-memory service for now; later migrate to DB-backed service
        resp = subscription_service.add_subscription(sub)  # sub is pydantic; service expects models.Subscription in current code
        return ok(resp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def status(bus_id: str):
    result = await fleet_service.get_bus_status(bus_id)
    if not result:
        raise HTTPException(status_code=404, detail="Bus not found")
    return result
@router.delete("/subscribe")
async def unsubscribe(user_id: str, bus_id: str, stop_id: str): 
    
    """Unsubscribe user from bus updates""" 
    try:
        await subscription_service.remove_subscription(user_id, bus_id, stop_id) 
        return {"message": f"Unsubscribed user {user_id} from bus {bus_id} / stop {stop_id}"}
    except Exception as e: 
        raise HTTPException(status_code=500, detail=str(e))
