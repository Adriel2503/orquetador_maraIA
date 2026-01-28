"""
Sistema de memoria del orquestador.
Guarda historial de conversación por session_id.
Protegido con asyncio.Lock para evitar race conditions en entorno async.
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime


# Storage en memoria (dict simple - para MVP)
# Protegido con asyncio.Lock para sincronización entre corutinas
_MEMORY_STORE: Dict[str, List[Dict]] = {}
_memory_lock = asyncio.Lock()


class MemoryManager:
    """
    Gestiona la memoria del orquestador.
    Guarda últimos N turnos por session_id.
    Todos los métodos son async y usan un lock para acceso thread-safe.
    """
    
    @staticmethod
    async def add(
        session_id: str,
        user_message: str,
        agent_used: Optional[str],
        response: str
    ) -> None:
        """
        Agrega un turno a la memoria.
        
        Args:
            session_id: ID de la sesión/usuario
            user_message: Mensaje del usuario
            agent_used: Agente que manejó el mensaje ("reserva" | "venta" | "cita" | None)
            response: Respuesta final al usuario (ya mejorada)
        """
        async with _memory_lock:
            if session_id not in _MEMORY_STORE:
                _MEMORY_STORE[session_id] = []
            
            _MEMORY_STORE[session_id].append({
                "user": user_message,
                "agent": agent_used,
                "response": response,
                "timestamp": datetime.now().isoformat()
            })
            
            # Mantener solo últimos 10 turnos
            _MEMORY_STORE[session_id] = _MEMORY_STORE[session_id][-10:]
    
    @staticmethod
    async def get(session_id: str, limit: int = 10) -> List[Dict]:
        """
        Obtiene los últimos N turnos de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario
            limit: Cantidad máxima de turnos a retornar
        
        Returns:
            Lista de turnos (dict con user, agent, response)
        """
        async with _memory_lock:
            history = _MEMORY_STORE.get(session_id, [])
            return history[-limit:]
    
    @staticmethod
    async def get_current_agent(session_id: str) -> Optional[str]:
        """
        Obtiene el agente actualmente activo en la conversación.
        
        Args:
            session_id: ID de la sesión/usuario
        
        Returns:
            Nombre del agente activo o None
        """
        async with _memory_lock:
            history = _MEMORY_STORE.get(session_id, [])
            if not history:
                return None
            
            for turn in reversed(history):
                if turn.get("agent"):
                    return turn["agent"]
            
            return None
    
    @staticmethod
    async def clear(session_id: str) -> None:
        """
        Limpia la memoria de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario
        """
        async with _memory_lock:
            if session_id in _MEMORY_STORE:
                del _MEMORY_STORE[session_id]
    
    @staticmethod
    async def get_stats() -> Dict:
        """Retorna estadísticas de uso de memoria (debug)"""
        async with _memory_lock:
            return {
                "total_sessions": len(_MEMORY_STORE),
                "sessions": {
                    sid: len(turns)
                    for sid, turns in _MEMORY_STORE.items()
                }
            }


# Singleton global
memory_manager = MemoryManager()


__all__ = ["memory_manager", "MemoryManager"]
