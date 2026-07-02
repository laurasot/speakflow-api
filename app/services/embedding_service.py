"""Servicio de similitud semántica usando embeddings.

Proporciona detección de repeticiones basada en embeddings (BAAI/bge-small-en-v1.5)
en lugar de comparación textual (difflib.SequenceMatcher).

La carga del modelo es lazy: solo se inicializa si `enable_semantic_similarity=True`.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Servicio de embeddings para similitud semántica (singleton)."""

    _instance: "EmbeddingService | None" = None
    _model: "SentenceTransformer | None" = None
    _enabled: bool = False
    _load_attempted: bool = False

    def __new__(cls, enable: bool = False) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(enable)
        return cls._instance

    def _initialize(self, enable: bool = False) -> None:
        """Inicializa el servicio (lazy loading del modelo)."""
        if self._load_attempted:
            return

        self._enabled = enable
        if not enable:
            logger.info("Semantic similarity disabled (using text-based difflib)")
            self._load_attempted = True
            return

        try:
            logger.info("Loading embedding model: BAAI/bge-small-en-v1.5 (~130 MB)")
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            logger.info("Embedding model loaded successfully")
            self._load_attempted = True

        except Exception as exc:
            logger.error("Failed to load embedding model: %s", exc, exc_info=True)
            logger.warning("Falling back to text-based similarity (difflib)")
            self._enabled = False
            self._load_attempted = True

    @property
    def enabled(self) -> bool:
        """True si el modelo de embeddings está cargado y disponible."""
        return self._enabled and self._model is not None

    def similarity(self, text1: str, text2: str) -> float:
        """Calcula similitud entre dos textos (0-1, más alto = más similar).

        Si embeddings están habilitados, usa similitud coseno de vectores.
        Si no, usa difflib.SequenceMatcher (fallback textual).
        """
        if not self._enabled or self._model is None:
            # Fallback: similitud textual con difflib
            from difflib import SequenceMatcher

            return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

        try:
            import numpy as np

            # Embeddings + similitud coseno
            emb1 = self._model.encode(text1, convert_to_numpy=True)
            emb2 = self._model.encode(text2, convert_to_numpy=True)

            # Similitud coseno: dot(a, b) / (norm(a) * norm(b))
            similarity = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))

            logger.debug(
                "Semantic similarity computed",
                extra={
                    "extra": {
                        "text1_len": len(text1),
                        "text2_len": len(text2),
                        "similarity": similarity,
                    }
                },
            )

            return similarity

        except Exception as exc:
            logger.error("Error computing embedding similarity: %s", exc, exc_info=True)
            # Fallback: similitud textual
            from difflib import SequenceMatcher

            return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


# Singleton global (lazy init)
_embedding_service: EmbeddingService | None = None


def get_embedding_service(enable: bool = False) -> EmbeddingService:
    """Obtiene el servicio de embeddings (singleton).

    Args:
        enable: True para cargar el modelo de embeddings, False para usar difflib.
    """
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = EmbeddingService(enable=enable)

    return _embedding_service
