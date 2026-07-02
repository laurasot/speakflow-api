"""Tests para el servicio de embeddings semánticos."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.embedding_service import EmbeddingService, get_embedding_service


class TestEmbeddingService:
    def test_disabled_uses_difflib_fallback(self):
        """Con enable=False, debe usar difflib sin cargar el modelo."""
        service = EmbeddingService(enable=False)

        assert service.enabled is False
        assert service._model is None

        # Debe funcionar usando difflib
        similarity = service.similarity("hello world", "hello there")
        assert 0.0 <= similarity <= 1.0

    def test_singleton_pattern(self):
        """EmbeddingService debe ser singleton."""
        service1 = EmbeddingService(enable=False)
        service2 = EmbeddingService(enable=False)

        assert service1 is service2

    @patch("sentence_transformers.SentenceTransformer")
    def test_enabled_loads_model(self, mock_transformer):
        """Con enable=True, debe intentar cargar el modelo."""
        mock_model = MagicMock()
        mock_transformer.return_value = mock_model

        # Reset singleton para este test
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._load_attempted = False

        service = EmbeddingService(enable=True)

        mock_transformer.assert_called_once_with("BAAI/bge-small-en-v1.5")
        assert service.enabled is True
        assert service._model is mock_model

    @patch("sentence_transformers.SentenceTransformer")
    def test_enabled_uses_embeddings(self, mock_transformer):
        """Con modelo cargado, debe usar embeddings en lugar de difflib."""
        import numpy as np

        mock_model = MagicMock()
        # Simula vectores normalizados
        mock_model.encode.side_effect = [
            np.array([1.0, 0.0, 0.0]),  # texto 1
            np.array([0.8, 0.6, 0.0]),  # texto 2
        ]
        mock_transformer.return_value = mock_model

        # Reset singleton
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._load_attempted = False

        service = EmbeddingService(enable=True)
        similarity = service.similarity("text one", "text two")

        assert mock_model.encode.call_count == 2
        assert 0.0 <= similarity <= 1.0

    @patch("sentence_transformers.SentenceTransformer")
    def test_falls_back_on_error(self, mock_transformer):
        """Si falla la carga del modelo, debe caer a difflib."""
        mock_transformer.side_effect = RuntimeError("Model not found")

        # Reset singleton
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._load_attempted = False

        service = EmbeddingService(enable=True)

        assert service.enabled is False
        assert service._model is None

        # Debe funcionar usando fallback
        similarity = service.similarity("hello", "hello there")
        assert 0.0 <= similarity <= 1.0

    def test_get_embedding_service_singleton(self):
        """get_embedding_service debe retornar singleton."""
        # Reset singleton
        from app.services import embedding_service

        embedding_service._embedding_service = None
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._load_attempted = False

        service1 = get_embedding_service(enable=False)
        service2 = get_embedding_service(enable=False)

        assert service1 is service2


class TestDifflibFallback:
    def test_similar_texts_high_score(self):
        """Textos similares deben tener score alto con difflib."""
        service = EmbeddingService(enable=False)

        similarity = service.similarity(
            "What's your approach to handling race conditions?",
            "Could you explain your approach to race conditions?",
        )

        # difflib debería dar un score alto (>=0.7) para estos textos
        assert similarity >= 0.7

    def test_different_texts_low_score(self):
        """Textos diferentes deben tener score bajo con difflib."""
        service = EmbeddingService(enable=False)

        similarity = service.similarity(
            "What's your approach to handling race conditions?",
            "Tell me about your hobbies",
        )

        # difflib debería dar un score bajo (<0.4) para estos textos
        assert similarity < 0.4

    def test_case_insensitive(self):
        """difflib fallback debe ser case-insensitive."""
        service = EmbeddingService(enable=False)

        s1 = service.similarity("Hello World", "hello world")
        s2 = service.similarity("hello world", "hello world")

        assert s1 == s2 == 1.0
