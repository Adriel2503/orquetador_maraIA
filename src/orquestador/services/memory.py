"""
Sistema de memoria del orquestador.
Guarda historial de conversación por session_id.
Protegido con asyncio.Lock para evitar race conditions en entorno async.
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime

from cachetools import TTLCache


# TTLCache con límite de tamaño para evitar memory leak en producción multiempresa.
# maxsize=10000 → máximo 10.000 sesiones activas simultáneamente (LRU eviction al superar límite)
# ttl=7200      → sesión expira si no recibe mensajes en 2 horas
# El TTL se renueva en cada add() al re-asignar la clave, manteniendo vivas conversaciones activas.
_MEMORY_STORE: TTLCache = TTLCache(maxsize=10000, ttl=7200)
_memory_lock = asyncio.Lock()


class MemoryManager:
    """
    Gestiona la memoria del orquestador.
    Guarda últimos N turnos por session_id.
    Todos los métodos son async y usan un lock para acceso thread-safe.
    """
    
    @staticmethod
    async def add(
        session_id: int,
        user_message: str,
        agent_used: Optional[str],
        response: str
    ) -> None:
        """
        Agrega un turno a la memoria.
        
        Args:
            session_id: ID de la sesión/usuario (int, unificado con n8n)
            user_message: Mensaje del usuario
            agent_used: Agente que manejó el mensaje ("reserva" | "venta" | "cita" | None)
            response: Respuesta final al usuario (ya mejorada)
        """
        async with _memory_lock:
            history = list(_MEMORY_STORE.get(session_id, []))
            history.append({
                "user": user_message,
                "agent": agent_used,
                "response": response,
                "timestamp": datetime.now().isoformat()
            })
            # Re-asignar (no append in-place) para renovar el TTL de la sesión en TTLCache.
            # Así la sesión se mantiene viva mientras el usuario siga enviando mensajes.
            _MEMORY_STORE[session_id] = history[-10:]
    
    @staticmethod
    async def get(session_id: int, limit: int = 10) -> List[Dict]:
        """
        Obtiene los últimos N turnos de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario (int)
            limit: Cantidad máxima de turnos a retornar
        
        Returns:
            Lista de turnos (dict con user, agent, response)
        """
        async with _memory_lock:
            history = _MEMORY_STORE.get(session_id, [])
            return history[-limit:]
    
    @staticmethod
    async def get_current_agent(session_id: int) -> Optional[str]:
        """
        Obtiene el agente actualmente activo en la conversación.
        
        Args:
            session_id: ID de la sesión/usuario (int)
        
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
    async def clear(session_id: int) -> None:
        """
        Limpia la memoria de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario (int)
        """
        async with _memory_lock:
            _MEMORY_STORE.pop(session_id, None)
    
    @staticmethod
    async def get_stats() -> Dict:
        """Retorna estadísticas de uso de memoria (debug)"""
        async with _memory_lock:
            return {
                "total_sessions": len(_MEMORY_STORE),
                "max_sessions": _MEMORY_STORE.maxsize,
                "session_ttl_seconds": _MEMORY_STORE.ttl,
                "sessions": {
                    sid: len(turns)
                    for sid, turns in _MEMORY_STORE.items()
                }
            }


# Singleton global
memory_manager = MemoryManager()


__all__ = ["memory_manager", "MemoryManager"]
