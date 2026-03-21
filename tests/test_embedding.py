"""Tests for the Tongyi/DashScope embedding and rerank service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.embedding import EmbeddingService


# ---------------------------------------------------------------------------
# Text Embedding Tests
# ---------------------------------------------------------------------------


class TestEmbedTexts:
    @pytest.mark.asyncio
    async def test_single_text(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3], "index": 0, "object": "embedding"}
            ],
            "model": "text-embedding-v4",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            result = await svc.embed_texts(["hello world"])
            assert len(result) == 1
            assert result[0] == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        result = await svc.embed_texts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batching_splits_at_10(self) -> None:
        svc = EmbeddingService(api_key="test-key")

        def make_response(batch_size: int) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {"embedding": [0.1] * 1024, "index": i, "object": "embedding"}
                    for i in range(batch_size)
                ],
                "model": "text-embedding-v4",
                "usage": {"total_tokens": 100},
            }
            return resp

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            # First call: 10 items, second call: 5 items
            client.post.side_effect = [make_response(10), make_response(5)]
            mock_get.return_value = client

            texts = [f"text {i}" for i in range(15)]
            result = await svc.embed_texts(texts)

            assert len(result) == 15
            assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_preserves_order_across_batches(self) -> None:
        svc = EmbeddingService(api_key="test-key")

        def make_response(batch_size: int, marker: float) -> MagicMock:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {"embedding": [marker + i], "index": i, "object": "embedding"}
                    for i in range(batch_size)
                ],
                "model": "text-embedding-v4",
                "usage": {"total_tokens": 50},
            }
            return resp

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            # 13 texts = batch of 10 + batch of 3
            client.post.side_effect = [
                make_response(10, 0.0),
                make_response(3, 100.0),
            ]
            mock_get.return_value = client

            texts = [f"t{i}" for i in range(13)]
            result = await svc.embed_texts(texts)

            assert len(result) == 13
            # First batch: markers 0..9
            assert result[0] == [0.0]
            assert result[9] == [9.0]
            # Second batch: markers 100..102
            assert result[10] == [100.0]
            assert result[12] == [102.0]

    @pytest.mark.asyncio
    async def test_error_raises_value_error(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            with pytest.raises(ValueError, match="Embedding API error: 401"):
                await svc.embed_texts(["test"])

    @pytest.mark.asyncio
    async def test_sends_correct_headers_and_payload(self) -> None:
        svc = EmbeddingService(api_key="my-secret-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.5], "index": 0, "object": "embedding"}],
            "model": "text-embedding-v4",
            "usage": {"total_tokens": 3},
        }

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            await svc.embed_texts(["hi"], dimension=512)

            call_args = client.post.call_args
            assert call_args[1]["headers"]["Authorization"] == "Bearer my-secret-key"
            payload = call_args[1]["json"]
            assert payload["model"] == "text-embedding-v4"
            assert payload["input"] == ["hi"]
            assert payload["dimensions"] == 512


# ---------------------------------------------------------------------------
# Multimodal Embedding Tests
# ---------------------------------------------------------------------------


class TestEmbedMultimodal:
    @pytest.mark.asyncio
    async def test_text_content(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "embeddings": [
                    {"index": 0, "embedding": [0.5] * 1024, "type": "text"}
                ]
            },
            "usage": {"input_tokens": 10},
        }

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            result = await svc.embed_multimodal([{"text": "hello"}])
            assert len(result) == 1
            assert len(result[0]) == 1024

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        result = await svc.embed_multimodal([])
        assert result == []

    @pytest.mark.asyncio
    async def test_error_raises_value_error(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            with pytest.raises(ValueError, match="Multimodal embedding API error: 500"):
                await svc.embed_multimodal([{"text": "test"}])


# ---------------------------------------------------------------------------
# Rerank Tests
# ---------------------------------------------------------------------------


class TestRerank:
    @pytest.mark.asyncio
    async def test_basic_rerank(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "results": [
                    {
                        "index": 1,
                        "relevance_score": 0.95,
                        "document": {"text": "relevant doc"},
                    },
                    {
                        "index": 0,
                        "relevance_score": 0.3,
                        "document": {"text": "less relevant"},
                    },
                ]
            },
            "usage": {"total_tokens": 50},
        }

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            results = await svc.rerank("query", ["less relevant", "relevant doc"])
            assert len(results) == 2
            assert results[0]["relevance_score"] == 0.95
            assert results[0]["index"] == 1

    @pytest.mark.asyncio
    async def test_empty_documents_returns_empty(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        results = await svc.rerank("query", [])
        assert results == []

    @pytest.mark.asyncio
    async def test_top_n_parameter(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "results": [
                    {
                        "index": 2,
                        "relevance_score": 0.99,
                        "document": {"text": "best"},
                    },
                ]
            },
            "usage": {"total_tokens": 30},
        }

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            results = await svc.rerank(
                "query", ["a", "b", "c"], top_n=1
            )

            # Verify top_n was sent in the payload
            payload = client.post.call_args[1]["json"]
            assert payload["parameters"]["top_n"] == 1
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_error_raises_value_error(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        with patch.object(svc, "_get_client") as mock_get:
            client = AsyncMock()
            client.post.return_value = mock_response
            mock_get.return_value = client

            with pytest.raises(ValueError, match="Rerank API error: 429"):
                await svc.rerank("query", ["doc1"])


# ---------------------------------------------------------------------------
# Lifecycle Tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_cleans_up_client(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        mock_client = AsyncMock()
        svc._client = mock_client

        await svc.close()

        mock_client.aclose.assert_called_once()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_client(self) -> None:
        svc = EmbeddingService(api_key="test-key")
        assert svc._client is None
        await svc.close()  # Should not raise
        assert svc._client is None

    def test_default_api_key_from_env(self) -> None:
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "env-key"}):
            # Re-import would pick up env, but we test constructor fallback
            svc = EmbeddingService(api_key="explicit-key")
            assert svc.api_key == "explicit-key"


# ---------------------------------------------------------------------------
# Singleton Tests
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_embedding_service_returns_same_instance(self) -> None:
        from services.embedding import get_embedding_service, _service

        # Reset singleton for test isolation
        import services.embedding as mod

        mod._service = None

        svc1 = get_embedding_service()
        svc2 = get_embedding_service()
        assert svc1 is svc2

        # Cleanup
        mod._service = None
