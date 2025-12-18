import pytest


@pytest.mark.asyncio
async def test_agent_ask_simple(agent_client):
    """Basic health check for /ask: in-domain question returns an answer string."""
    resp = await agent_client.post("/ask", json={"query": "Where is Bus B1 now?"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("answer"), str)
    assert data["answer"].strip() != ""


@pytest.mark.asyncio
async def test_agent_ask_out_of_domain(agent_client):
    """Out-of-domain queries should trigger the guardrail answer, not hallucinations."""
    resp = await agent_client.post("/ask", json={"query": "Who is the president of India?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "transport assistant" in data.get("answer", "").lower()
