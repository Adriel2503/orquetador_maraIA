"""Modelos Pydantic para request/response del orquestador"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal


class ChatConfig(BaseModel):
    """Configuración del chatbot que viene en el request desde n8n"""
    nombre_bot: str
    id_empresa: int
    rol_bot: str
    tipo_bot: str
    objetivo_principal: str
    frase_saludo: Optional[str] = None
    archivo_saludo: Optional[str] = None
    personalidad: Optional[str] = None
    tono_com: Optional[str] = None
    frase_des: Optional[str] = None
    frase_no_sabe: Optional[str] = None
    modalidad: Optional[str] = None
    temas_esc: Optional[str] = None
    frase_esc: Optional[str] = None
    motivo_der: Optional[str] = None
    motivo_so: Optional[str] = None
    fecha_formateada: Optional[str] = None
    fecha_iso: Optional[str] = None
    duracion_cita_minutos: Optional[int] = None
    slots: Optional[int] = None
    agendar_usuario: Optional[bool] = None
    agendar_sucursal: Optional[bool] = None

    @field_validator('agendar_usuario', 'agendar_sucursal', mode='before')
    @classmethod
    def convert_agendar_to_bool(cls, v):
        """
        Convierte 1/0 o "1"/"0" a bool; "null"/"" a None.
        n8n envía valores numéricos 1 y 0 para agendar_usuario y agendar_sucursal.
        """
        if v is None or v == "null" or v == "":
            return None
        if v in (1, "1", True):
            return True
        if v in (0, "0", False):
            return False
        return v


class ChatRequest(BaseModel):
    """Request que recibe el orquestador desde n8n"""
    message: str
    session_id: str  # identificador de conversación/persona
    config: ChatConfig


class ChatResponse(BaseModel):
    """Response que devuelve el orquestador a n8n"""
    reply: str
    session_id: str
    agent_used: Optional[str] = None  # "venta" | "cita" | "reserva" | null si respondió el orquestador
    action: Optional[str] = None      # "schedule" | "info" | "clarify" | "escalate" | "none"


class OrquestradorDecision(BaseModel):
    """
    Structured output del orquestador: decisión de delegación o respuesta directa.
    Este modelo se usa con OpenAI structured output para garantizar formato consistente.
    """
    action: Literal["delegate", "respond"] = Field(
        description="'delegate' si debe llamar a un agente especializado, 'respond' si el orquestador responde directamente"
    )
    agent_name: Optional[Literal["reserva", "venta", "cita"]] = Field(
        default=None,
        description="Nombre del agente al que delegar. Solo si action='delegate'"
    )
    response: str = Field(
        description="Respuesta al usuario. Si action='delegate', puede ser un mensaje transitorio. Si action='respond', es la respuesta final."
    )
