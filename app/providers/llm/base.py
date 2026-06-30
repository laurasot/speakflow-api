from typing import Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel


@runtime_checkable
class LLMProvider(Protocol):
    """Contrato que todos los proveedores de LLM deben cumplir."""

    provider_name: str

    def create_llm(self) -> BaseChatModel:
        """Crea y devuelve un LLM compatible con LangChain."""
        ...

    @property
    def enabled(self) -> bool:
        """Retorna True si el proveedor tiene API key configurada."""
        ...
