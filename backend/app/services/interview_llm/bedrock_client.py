import json
import logging
import asyncio
import os
from typing import Any, AsyncIterator
from concurrent.futures import ThreadPoolExecutor

import botocore.exceptions

from app.core.config import settings
from app.services.interview_llm.token_tracker import estimate_cost, token_tracker

try:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    import botocore.parsers
except ImportError:
    raise ImportError("boto3 is required for Bedrock integration. Install it with: pip install boto3")

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)


class BedrockError(Exception):
    pass


class BedrockInterviewClient:
    """AWS Bedrock client for LLM interactions using bearer token authentication."""

    def __init__(self) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Bedrock Runtime client with bearer token authentication."""
        if not self.settings.AWS_BEARER_TOKEN_BEDROCK:
            raise BedrockError("AWS_BEARER_TOKEN_BEDROCK is not configured.")

        if not self.settings.AWS_REGION:
            raise BedrockError("AWS_REGION is not configured.")

        try:
            # Create Bedrock Runtime client with dummy credentials since we use bearer token auth
            self.client = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.AWS_REGION,
                aws_access_key_id="dummy",
                aws_secret_access_key="dummy",
            )

            # Configure bearer token authentication by modifying the client's auth handler
            self._configure_bearer_token_auth()

            logger.info(
                "Bedrock client initialized successfully with region=%s",
                self.settings.AWS_REGION,
            )
        except Exception as exc:
            raise BedrockError(f"Failed to initialize Bedrock client: {exc}") from exc

    def _configure_bearer_token_auth(self) -> None:
        """Configure bearer token authentication for Bedrock API calls."""
        original_make_request = self.client._make_api_call

        def make_request_with_bearer_token(operation_name, api_params):
            # Intercept and add bearer token to the request
            try:
                result = original_make_request(operation_name, api_params)
                return result
            except Exception as exc:
                # If auth fails, try with bearer token in headers
                if "UnauthorizedException" in str(exc) or "AuthorizationException" in str(exc):
                    logger.debug("Retrying with bearer token authentication")
                raise

        # Add bearer token to the session headers
        if hasattr(self.client, "_session"):
            session = self.client._session
            session.user_agent_extra = f"bearer-token-auth"

        # Set up custom event handler for adding bearer token
        def add_bearer_token(request, **kwargs):
            request.headers["Authorization"] = f"Bearer {self.settings.AWS_BEARER_TOKEN_BEDROCK}"

        self.client.meta.events.register("before-send", add_bearer_token)

    def _models_to_try(self, primary: str) -> list[str]:
        """Get list of models to try, including fallback models."""
        seen: set[str] = set()
        models: list[str] = []
        for m in [primary, *self.settings.interview_fallback_model_list]:
            if m and m not in seen:
                seen.add(m)
                models.append(m)
        return models



    def _prepare_bedrock_messages(self, messages: list[dict[str, str]]) -> str:
        """Convert OpenAI-style messages to Bedrock prompt format."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        return "\n".join(prompt_parts)

    @traceable(name="Bedrock Chat Completion", run_type="llm")
    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        json_mode: bool = False,
        operation: str | None = None,
    ) -> str:
        """Invoke Bedrock model with retry logic and timeout handling."""
        if not self.settings.AWS_BEARER_TOKEN_BEDROCK:
            raise BedrockError("AWS_BEARER_TOKEN_BEDROCK is not configured.")

        last_error: Exception | None = None

        for attempt_model in self._models_to_try(model):
            for retry in range(3):
                try:
                    # Prepare the prompt
                    prompt = self._prepare_bedrock_messages(messages)
                    if json_mode:
                        prompt += "\n\nReturn ONLY valid JSON."

                    # Prepare request body for Bedrock
                    body = json.dumps({
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": self._extract_system_prompt(messages),
                    })

                    # Run in executor to handle blocking I/O
                    loop = asyncio.get_event_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            self._executor,
                            self._invoke_bedrock,
                            attempt_model,
                            body,
                        ),
                        timeout=120.0,
                    )

                    res_dict = response
                    content = res_dict["content"]
                    input_tokens = res_dict["input_tokens"]
                    output_tokens = res_dict["output_tokens"]

                    try:
                        from langsmith import get_current_run_tree
                        run_tree = get_current_run_tree()
                        if run_tree:
                            if run_tree.metadata is None:
                                run_tree.metadata = {}
                            run_tree.metadata.update({
                                "ls_provider": "bedrock",
                                "ls_model_name": attempt_model,
                            })
                            if input_tokens is not None or output_tokens is not None:
                                cost_dict = estimate_cost(attempt_model, input_tokens or 0, output_tokens or 0)
                                
                                usage_block = {
                                    "input_tokens": input_tokens or 0,
                                    "output_tokens": output_tokens or 0,
                                    "total_tokens": (input_tokens or 0) + (output_tokens or 0),
                                    "prompt_tokens": input_tokens or 0,
                                    "completion_tokens": output_tokens or 0,
                                    "input_cost": cost_dict["input_cost"],
                                    "output_cost": cost_dict["output_cost"],
                                    "total_cost": cost_dict["total_cost"]
                                }
                                
                                try:
                                    if run_tree.outputs is None:
                                        run_tree.outputs = {}
                                    run_tree.outputs["usage_metadata"] = usage_block
                                    run_tree.outputs["response_metadata"] = {
                                        "token_usage": {
                                            "prompt_tokens": input_tokens or 0,
                                            "completion_tokens": output_tokens or 0,
                                            "total_tokens": (input_tokens or 0) + (output_tokens or 0)
                                        }
                                    }
                                except Exception as set_exc:
                                    logger.warning("Failed to set usage_metadata in outputs: %s", set_exc)

                                try:
                                    if run_tree.extra is None:
                                        run_tree.extra = {}
                                    run_tree.extra["token_usage"] = {
                                        "prompt_tokens": input_tokens or 0,
                                        "completion_tokens": output_tokens or 0,
                                        "total_tokens": (input_tokens or 0) + (output_tokens or 0)
                                    }
                                    run_tree.extra["usage_metadata"] = usage_block
                                    
                                    # update metadata (which is stored in extra['metadata'])
                                    if run_tree.metadata is not None:
                                        run_tree.metadata["usage_metadata"] = usage_block
                                        run_tree.metadata["token_usage"] = {
                                            "prompt_tokens": input_tokens or 0,
                                            "completion_tokens": output_tokens or 0,
                                            "total_tokens": (input_tokens or 0) + (output_tokens or 0)
                                        }
                                except Exception as set_exc:
                                    logger.warning("Failed to set extra/metadata token usage: %s", set_exc)
                                try:
                                    tracker = token_tracker.get()
                                    if tracker is not None:
                                        tracker["prompt_tokens"] += input_tokens or 0
                                        tracker["completion_tokens"] += output_tokens or 0
                                        tracker["input_cost"] = tracker.get("input_cost", 0.0) + cost_dict["input_cost"]
                                        tracker["output_cost"] = tracker.get("output_cost", 0.0) + cost_dict["output_cost"]
                                        tracker["total_cost"] = tracker.get("total_cost", 0.0) + cost_dict["total_cost"]
                                except Exception as tracker_exc:
                                    logger.warning("Failed to update token tracker: %s", tracker_exc)
                    except Exception as exc:
                        logger.warning("Failed to log usage to LangSmith: %s", exc)

                    return content.strip()

                except asyncio.TimeoutError:
                    last_error = BedrockError(f"Request timeout for model {attempt_model}")
                    logger.warning(
                        "Bedrock request timeout model=%s retry=%s",
                        attempt_model,
                        retry,
                    )
                    continue

                except botocore.exceptions.BotoCoreError as exc:
                    last_error = exc
                    logger.warning(
                        "Bedrock request failed model=%s retry=%s: %s",
                        attempt_model,
                        retry,
                        exc,
                    )
                    continue

                except botocore.exceptions.ClientError as exc:
                    error_code = exc.response.get("Error", {}).get("Code", "Unknown")
                    if error_code == "ThrottlingException":
                        last_error = BedrockError("Rate limited by Bedrock.")
                        continue
                    if error_code in ["ServiceUnavailableException", "InternalServerError"]:
                        last_error = BedrockError(f"Bedrock server error: {error_code}")
                        continue
                    if error_code == "UnauthorizedException":
                        raise BedrockError(
                            f"Authentication failed. Check AWS_BEARER_TOKEN_BEDROCK and AWS_REGION: {error_code}"
                        ) from exc

                    # Other client errors
                    detail = str(exc)[:500]
                    raise BedrockError(f"Bedrock request failed: {detail}") from exc

                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Bedrock request error model=%s retry=%s: %s",
                        attempt_model,
                        retry,
                        exc,
                    )
                    continue

        raise BedrockError(f"All model attempts failed. Last error: {last_error}")

    def _invoke_bedrock(self, model: str, body: str) -> dict[str, Any]:
        """Synchronous wrapper for Bedrock API call returning content and token usage."""
        try:
            response = self.client.invoke_model(
                modelId=model,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read().decode("utf-8"))

            # Extract input and output tokens from headers/body
            input_tokens = None
            output_tokens = None

            headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
            for key in ["x-amzn-bedrock-input-token-count", "X-Amzn-Bedrock-Input-Token-Count", "x-amzn-bedrock-input-token-count".lower()]:
                if key in headers:
                    try:
                        input_tokens = int(headers[key])
                        break
                    except (ValueError, TypeError):
                        pass

            for key in ["x-amzn-bedrock-output-token-count", "X-Amzn-Bedrock-Output-Token-Count", "x-amzn-bedrock-output-token-count".lower()]:
                if key in headers:
                    try:
                        output_tokens = int(headers[key])
                        break
                    except (ValueError, TypeError):
                        pass

            if input_tokens is None or output_tokens is None:
                usage = response_body.get("usage", {})
                if usage:
                    if input_tokens is None:
                        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
                    if output_tokens is None:
                        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
                if input_tokens is None:
                    input_tokens = response_body.get("input_token_count") or response_body.get("prompt_token_count")
                if output_tokens is None:
                    output_tokens = response_body.get("output_token_count") or response_body.get("completion_token_count")

            # Extract content from response based on model type
            content = ""
            # Handle OpenAI-style format (choices array)
            if "choices" in response_body:
                choices = response_body["choices"]
                if isinstance(choices, list) and len(choices) > 0:
                    message = choices[0].get("message", {})
                    content = message.get("content", "")
            # Handle Bedrock native format
            elif "content" in response_body:
                content = response_body["content"]
                if isinstance(content, list) and len(content) > 0:
                    content = content[0].get("text", "")
            elif "output" in response_body:
                content = response_body["output"]
            elif "completion" in response_body:
                content = response_body["completion"]
            elif "text" in response_body:
                content = response_body["text"]
            else:
                logger.warning("Unexpected Bedrock response format: %s", response_body)
                content = json.dumps(response_body)

            return {
                "content": content,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }

        except json.JSONDecodeError as exc:
            raise BedrockError(f"Failed to parse Bedrock response JSON: {exc}") from exc

    def _extract_system_prompt(self, messages: list[dict[str, str]]) -> str:
        """Extract system prompt from messages if present."""
        for msg in messages:
            if msg.get("role") == "system":
                return msg.get("content", "")
        return ""

    @traceable(name="Bedrock Stream Completion", run_type="llm")
    async def stream_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.4,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Stream completion from Bedrock model."""
        if not self.settings.AWS_BEARER_TOKEN_BEDROCK:
            raise BedrockError("AWS_BEARER_TOKEN_BEDROCK is not configured.")

        try:
            # Prepare the prompt
            prompt = self._prepare_bedrock_messages(messages)

            # Prepare request body for Bedrock streaming
            body = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": self._extract_system_prompt(messages),
            })

            # Run streaming in executor
            loop = asyncio.get_event_loop()
            async for chunk in await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    self._stream_bedrock,
                    model,
                    body,
                ),
                timeout=120.0,
            ):
                yield chunk

        except asyncio.TimeoutError:
            raise BedrockError("Stream request timeout")

    def _stream_bedrock(self, model: str, body: str) -> AsyncIterator[str]:
        """Synchronous wrapper for Bedrock streaming API call."""
        try:
            response = self.client.invoke_model_with_response_stream(
                modelId=model,
                body=body,
                contentType="application/json",
            )

            event_stream = response.get("body")
            for event in event_stream:
                if "chunk" in event:
                    chunk = json.loads(event["chunk"]["bytes"].decode("utf-8"))
                    if "content" in chunk:
                        content = chunk["content"]
                        if isinstance(content, list) and len(content) > 0:
                            yield content[0].get("text", "")
                    elif "output" in chunk:
                        yield chunk["output"]

        except Exception as exc:
            raise BedrockError(f"Stream failed: {exc}") from exc

