import pytest
from unittest.mock import AsyncMock, MagicMock
from apps.worker.agents.paper_tag_agent import PaperTagAgent
from libs.schemas.library import PaperTagResult, ParagraphTag


class TestPaperTagAgent:
    @pytest.mark.asyncio
    async def test_run_returns_tag_result(self):
        mock_gateway = MagicMock()
        mock_gateway.chat_structured = AsyncMock(return_value=PaperTagResult(
            field="Computer Vision",
            sub_field="3D Anomaly Detection",
            keywords=["point cloud", "memory bank"],
            methods=["PatchCore"],
            datasets=["MVTec 3D-AD"],
            benchmarks=["AUROC"],
            innovation_points=["First to apply..."],
            paragraph_tags=[],
        ))

        agent = PaperTagAgent(gateway=mock_gateway)
        result = await agent.run(
            paper_text="We propose a method for 3D anomaly detection...",
            metadata={"title": "Test Paper", "year": 2024},
        )

        assert result.field == "Computer Vision"
        assert "point cloud" in result.keywords
        assert mock_gateway.chat_structured.called

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        mock_gateway = MagicMock()
        mock_gateway.chat_structured = AsyncMock(side_effect=Exception("LLM error"))

        agent = PaperTagAgent(gateway=mock_gateway)
        result = await agent.run(
            paper_text="Some paper text...",
            metadata={"title": "Failing Paper"},
        )

        assert result.field == ""
        assert result.keywords == []

    @pytest.mark.asyncio
    async def test_truncates_long_text(self):
        mock_gateway = MagicMock()
        mock_gateway.chat_structured = AsyncMock(return_value=PaperTagResult(field="AI"))

        agent = PaperTagAgent(gateway=mock_gateway)
        long_text = "x" * 20000
        await agent.run(paper_text=long_text, metadata={"title": "Long"})

        # Verify the user content sent to LLM was truncated
        call_args = mock_gateway.chat_structured.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        user_msg = [m for m in messages if m["role"] == "user"][0]
        assert len(user_msg["content"]) < 20000  # truncated at 8000 chars of paper text
