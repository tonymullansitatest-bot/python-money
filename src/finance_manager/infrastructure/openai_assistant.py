import os

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

DEFAULT_MODEL = "gpt-6.1-terra"
MAX_PROMPT_LENGTH = 4000


class AssistantError(Exception):
    """A safe, user-facing assistant error."""


class OpenAIAssistant:
    def ask(self, prompt: str) -> str:
        prompt = prompt.strip()
        if not prompt:
            raise AssistantError("Enter a question or text to summarise.")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise AssistantError(
                f"Text must be at most {MAX_PROMPT_LENGTH} characters."
            )
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise AssistantError("Set OPENAI_API_KEY and restart the application.")

        model = os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
        try:
            with OpenAI(
                base_url="https://api.openai.com/v1", timeout=45.0, max_retries=0
            ) as client:
                response = client.responses.create(
                    model=model,
                    instructions=(
                        "Help with general personal finance questions and summarise "
                        "the supplied text. Do not claim access to the user's accounts "
                        "or provide personalised investment or tax advice."
                    ),
                    input=prompt,
                    store=False,
                    max_output_tokens=2048,
                )
        except AuthenticationError:
            raise AssistantError(
                "OpenAI authentication failed. Check OPENAI_API_KEY."
            ) from None
        except APITimeoutError:
            raise AssistantError(
                "The OpenAI request timed out. Please try again."
            ) from None
        except APIConnectionError:
            raise AssistantError(
                "Could not connect to OpenAI. Check your connection."
            ) from None
        except RateLimitError:
            raise AssistantError(
                "OpenAI rejected the request due to a rate or quota limit."
            ) from None
        except APIError:
            raise AssistantError(
                "OpenAI could not complete the request. "
                "Check model access and try again."
            ) from None

        if response.status != "completed":
            raise AssistantError(
                "OpenAI returned an incomplete response. Please try again."
            )
        answer = response.output_text.strip()
        if not answer:
            raise AssistantError("OpenAI returned no text. Please try again.")
        return answer
