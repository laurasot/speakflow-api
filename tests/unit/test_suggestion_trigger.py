import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.transcript import ConversationTurn, SuggestionMessage, TranscriptMessage
from app.services.suggestion_service import SuggestionService
from app.services.suggestion_trigger import SuggestionState, SuggestionTrigger


def make_transcript(
    source: str = "system",
    text: str = "What is your experience?",
    is_final: bool = True,
    session_id: str = "test-session",
) -> TranscriptMessage:
    return TranscriptMessage(
        session_id=session_id,
        source=source,
        text=text,
        is_final=is_final,
        timestamp=1717000000000,
        provider="mock",
        language="en",
        start_time=0.0,
        end_time=1.0,
    )


@pytest.fixture
def mock_suggestion_service():
    service = MagicMock(spec=SuggestionService)
    service.enabled = True
    service.generate = AsyncMock(return_value=SuggestionMessage(
        session_id="test-session",
        source="system",
        suggestion="You could say...",
        based_on="What is your experience?",
        trigger_reason="silence",
        timestamp=1717000000000,
    ))
    return service


@pytest.fixture
def mock_send_suggestion():
    return AsyncMock()


@pytest.fixture
def trigger(mock_suggestion_service, mock_send_suggestion):
    return SuggestionTrigger(
        suggestion_service=mock_suggestion_service,
        send_suggestion=mock_send_suggestion,
    )


class TestIsQuestion:
    def test_question_mark_is_detected(self, trigger):
        assert trigger._is_question("What is your name?") is True
        assert trigger._is_question("How does this work?") is True

    def test_question_starters_detected(self, trigger):
        assert trigger._is_question("What is the approach") is True
        assert trigger._is_question("How do you handle this") is True
        assert trigger._is_question("Could you explain") is True
        assert trigger._is_question("Can you tell me") is True

    def test_spanish_questions_detected(self, trigger):
        assert trigger._is_question("¿Qué experiencia tienes?") is True
        assert trigger._is_question("Cómo manejas los errores") is True
        assert trigger._is_question("Puedes explicar eso") is True

    def test_statement_not_detected(self, trigger):
        assert trigger._is_question("That sounds good") is False
        assert trigger._is_question("I understand") is False
        assert trigger._is_question("Let me explain") is False


class TestIsRepeat:
    def test_similar_questions_detected(self, trigger):
        current = "What's your approach to handling race conditions?"
        previous = "Could you explain your approach to race conditions?"
        assert trigger._is_repeat(current, previous) is True

    def test_different_questions_not_detected(self, trigger):
        current = "What's your approach to handling race conditions?"
        previous = "Tell me about your hobbies"
        assert trigger._is_repeat(current, previous) is False

    def test_none_previous_returns_false(self, trigger):
        assert trigger._is_repeat("What is this?", None) is False


class TestHasFillerWords:
    def test_filler_words_detected(self, trigger):
        state = SuggestionState()
        state.conversation_context.append(ConversationTurn(
            source="microphone",
            text="um well I think uh",
            timestamp=1717000000000,
        ))
        assert trigger._has_filler_words(state) is True

    def test_no_filler_words(self, trigger):
        state = SuggestionState()
        state.conversation_context.append(ConversationTurn(
            source="microphone",
            text="I have extensive experience with Python",
            timestamp=1717000000000,
        ))
        assert trigger._has_filler_words(state) is False

    def test_filler_in_system_not_counted(self, trigger):
        state = SuggestionState()
        state.conversation_context.append(ConversationTurn(
            source="system",
            text="um can you explain",
            timestamp=1717000000000,
        ))
        assert trigger._has_filler_words(state) is False


class TestEvaluate:
    async def test_non_final_transcript_ignored(self, trigger, mock_suggestion_service):
        transcript = make_transcript(is_final=False)
        await trigger.evaluate(transcript)
        assert mock_suggestion_service.generate.call_count == 0

    async def test_system_question_starts_timer_waiting_for_mic(self, trigger):
        transcript = make_transcript(source="system", text="What is your experience?")
        await trigger.evaluate(transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is not None
        assert state.pending_suggestion is True
        assert state.waiting_for == "microphone"

    async def test_mic_response_cancels_speaker_timer(self, trigger):
        system_transcript = make_transcript(source="system", text="What is your experience?")
        await trigger.evaluate(system_transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is not None

        mic_transcript = make_transcript(source="microphone", text="I have 5 years of experience")
        await trigger.evaluate(mic_transcript)

        assert state.suggestion_timer is None
        assert state.pending_suggestion is False
        assert state.waiting_for is None

    async def test_user_question_starts_timer_waiting_for_system(self, trigger):
        transcript = make_transcript(source="microphone", text="Could you clarify the timeline?")
        await trigger.evaluate(transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is not None
        assert state.pending_suggestion is True
        assert state.waiting_for == "system"
        assert state.pending_trigger_reason == "user_question"

    async def test_speaker_response_cancels_user_question_timer(self, trigger):
        mic_transcript = make_transcript(source="microphone", text="Could you clarify the timeline?")
        await trigger.evaluate(mic_transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is not None

        system_transcript = make_transcript(source="system", text="Sure, it's 3 months")
        await trigger.evaluate(system_transcript)

        assert state.suggestion_timer is None
        assert state.pending_suggestion is False

    async def test_non_question_does_not_start_timer(self, trigger):
        transcript = make_transcript(source="system", text="That sounds great")
        await trigger.evaluate(transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is None

    async def test_mic_statement_does_not_start_timer(self, trigger):
        transcript = make_transcript(source="microphone", text="I understand the requirements")
        await trigger.evaluate(transcript)

        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is None

    async def test_context_is_accumulated(self, trigger):
        t1 = make_transcript(source="system", text="Hello")
        t2 = make_transcript(source="microphone", text="Hi there")
        t3 = make_transcript(source="system", text="How are you?")

        await trigger.evaluate(t1)
        await trigger.evaluate(t2)
        await trigger.evaluate(t3)

        state = trigger.get_or_create_state("test-session")
        assert len(state.conversation_context) == 3


class TestCleanup:
    async def test_cleanup_cancels_timer(self, trigger):
        transcript = make_transcript(source="system", text="What is your experience?")
        await trigger.evaluate(transcript)
        
        state = trigger.get_or_create_state("test-session")
        assert state.suggestion_timer is not None
        
        trigger.cleanup_session("test-session")
        
        assert "test-session" not in trigger._states


class TestConversationTurn:
    def test_role_for_microphone(self):
        turn = ConversationTurn(source="microphone", text="test", timestamp=123)
        assert turn.role == "User"

    def test_role_for_system(self):
        turn = ConversationTurn(source="system", text="test", timestamp=123)
        assert turn.role == "Speaker"
