# agent/base_agent.py
import asyncio
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    def __init__(self):
        self._running = False
        self._task = None

    @abstractmethod
    async def loop_once(self):
        raise NotImplementedError()

    async def start_loop(self):
        self._running = True
        while self._running:
            try:
                await self.loop_once()
            except Exception as e:
                print("Agent loop error:", e)
            await asyncio.sleep(0)  # loop runner logic in subclass

    async def stop(self):
        self._running = False
