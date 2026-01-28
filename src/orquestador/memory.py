"""
Sistema de memoria del orquestador.
Guarda historial de conversación por session_id.
"""

from typing import Dict, List, Optional
from datetime import datetime


# Storage en memoria (dict simple - para MVP)
# NOTA: Sin protección contra race conditions. Para producción con múltiples workers/instancias,
# migrar a Redis o usar threading.Lock para sincronización
# Migrar a Redis después
_MEMORY_STORE: Dict[str, List[Dict]] = {}


class MemoryManager:
    """
    Gestiona la memoria del orquestador.
    Guarda últimos N turnos por session_id.
    """
    
    @staticmethod
    def add(
        session_id: str,
        user_message: str,
        agent_used: Optional[str],
        response: str
    ):
        """
        Agrega un turno a la memoria.
        
        Args:
            session_id: ID de la sesión/usuario
            user_message: Mensaje del usuario
            agent_used: Agente que manejó el mensaje ("reserva" | "venta" | "cita" | None)
            response: Respuesta final al usuario (ya mejorada)
        """
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
        
        print(f"[MEMORY] Guardado turno para {session_id}. Total: {len(_MEMORY_STORE[session_id])}")
    
    @staticmethod
    def get(session_id: str, limit: int = 10) -> List[Dict]:
        """
        Obtiene los últimos N turnos de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario
            limit: Cantidad máxima de turnos a retornar
        
        Returns:
            Lista de turnos (dict con user, agent, response)
        """
        history = _MEMORY_STORE.get(session_id, [])
        return history[-limit:]
    
    @staticmethod
    def get_current_agent(session_id: str) -> Optional[str]:
        """
        Obtiene el agente actualmente activo en la conversación.
        
        Args:
            session_id: ID de la sesión/usuario
        
        Returns:
            Nombre del agente activo o None
        """
        history = _MEMORY_STORE.get(session_id, [])
        if not history:
            return None
        
        # Buscar el último turno con agente asignado
        for turn in reversed(history):
            if turn.get("agent"):
                return turn["agent"]
        
        return None
    
    @staticmethod
    def clear(session_id: str):
        """
        Limpia la memoria de una sesión.
        
        Args:
            session_id: ID de la sesión/usuario
        """
        if session_id in _MEMORY_STORE:
            del _MEMORY_STORE[session_id]
            print(f"[MEMORY] Limpiada memoria de {session_id}")
    
    @staticmethod
    def get_stats():
        """Retorna estadísticas de uso de memoria (debug)"""
        return {
            "total_sessions": len(_MEMORY_STORE),
            "sessions": {
                session_id: len(turns)
                for session_id, turns in _MEMORY_STORE.items()
            }
        }


# Singleton global
memory_manager = MemoryManager()


__all__ = ["memory_manager", "MemoryManager"]
