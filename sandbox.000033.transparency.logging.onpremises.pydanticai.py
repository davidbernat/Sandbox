from pydantic import BaseModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai import Agent, RunContext, InstrumentationSettings
from pydantic_ai import PartStartEvent, PartDeltaEvent, FinalResultEvent, FunctionToolCallEvent, SystemPromptPart, \
    FunctionToolResultEvent, TextPartDelta, ToolCallPartDelta, UserPromptPart, ToolReturnPart, ToolCallPart
import httpx
import json
import asyncio
import textwrap
import time

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Author: starlight.ai
# Maintainer: David Bernat
# Date: 1/19/25
# Purpose: transparently log local LLM request/response of PydanticAI structured coercion system

# This write-up will be brief and improved at a future time. In short, this example demonstrates the classic PydanticAI
# CityLocation example in which a generic LLM is coerced to provide structured output (CityLocation) which can then be
# validation-checked by Pydantic. PydanticAI is the auxiliary package which claims responsibility for LLM agent (Agent)
# configuration (and setup), but also prompt coercions and transformation so the LLM does what is necessary to return a
# result which can most easily and performatively be decoded into any requested structured data  (i.e., CityLocation).
#
# There are a few serious limitations to the transparency of PydanticAI that this extensive description seeks to resolve
# and provide a wide example for downstream users to satisfy their own needs. In short, this code here allows a new user
# to rapidly see what PydanticAI does internally to its LLM prompts within the first ten minutes of test-driving the
# package. Even following PydanticAI guidelines there are explicit limitations in the transparency of the process, which
# appear to include no easy access to the underlying request/response send from/to the Agent client, and even the events
# PydanticAI directly exposes seem only to fire after a round-trip to the LLM has occurred and been processed. Oh, well?
#
# In short, PydanticAI makes three key modifications to the prompt, but only three key modifications: a. a specialized
# at runtime function "final_result" is created with parameters which match the output_type object key fields and is set
# to required; de facto the LLM choosing this tool means that the LLM expects its querying to be completed, and by using
# a tool function with parameters which match the output_type data object, the parsing and validation are much easier.
# (Very clever!) b. a prompted_output_template is added to the PydanticAI object which constructs the relationship with
# the LLM itself, which, in short, says "Always respond with a JSON object that's compatible with this schema: {schema}
# Don't include any text or Markdown fencing before or after." It is these two approaches above which do the majority of
# the heavy lifting of the entire PydanticAI platform as a structured data client, and can easily be replicated outside
# the PydanticAI dependency itself. c. automatic retries (new request/response to the LLM) are managed automatically if
# the arguments of final_result cannot be parsed into output_type and/or fail structured Pydantic validators of type. It
# is unclear (at the time of writing we did not check) whether retry prompts are (slightly) different than its previous.
# This work took multiple days over several weeks, including personal and code generation sessions with numerous
# pitfalls and challenges. A careful consideration is that httpx logging seems to only be supported by the PydanticAI
# "chat models" if asynchronous, so be careful of different thread-contexts loading to ensure the logger is loaded
# properly. The code is presented here as-is for now to move on to pressing matters that are my responsibility. Thanks,
# and users should feel free to create GitHub Issues in this repository to ask questions or request PRs to improve this.
#
# In particularly, this allows on-premise (i.e., local) LLM users, privacy conscience, curious souls, or technical
# wizards to get total transparency into what PydanticAI does without absurd LogFire requirements pushed down throats.


# EXECUTIVE SUMMARY:
# Prompt: Read [this file] and please provide a very short executive summary sentence to a broad technical audience
# (i.e., GitHub) as to why this script.py exists (what innate problems it solves to them), and about five succinct
# bulletin items of its reasons, benefits, or features. Less is more in clarity.
#
# Purpose: This transparency logging script demonstrates PydanticAI's request/response architecture and solves its
# critical "black box" problem for local LLM users needing to know what transmutations its internal architecture makes.
#
# Key Innate Problems Solved
# 
# 1. HTTP Client Interception: Custom httpx AsyncClient hooks directly into PydanticAI's internal request/response flow 
#     for complete visibility                          
# 2. Event Stream Analysis: Comprehensive parsing of request messages (system prompts, user prompts, tool calls, tool 
#     returns) with proper correlation
# 3. Zero-Cost Transparency: Achieves full logging without requiring LogFire or external dependencies
# 4. Self-Contained Solution: Single file provides both client-side and agent-side visibility without complex setup
# 
# Benefits
# 
# 1. Complete Message History: Both request and response sides visible in single log stream with run_id correlation
# 2. Tool Call Transparency: All tool invocations logged from request preparation through final response
# 3. LLM Behavior Insight: Direct access to PydanticAI's prompt modification and structured output mechanisms                                                            
# 4. Developer Experience: Immediate visibility into model coercion, retries, and decision-making patterns
# 
# Features
# 
# - Real-time HTTP request/response logging with redaction
#     - Complete message parts parsing (SystemPromptPart, UserPromptPart, ToolReturnPart, ToolCallPart)
# - Correlation via run_id across entire conversation
# - Usage statistics tracking and model information logging
# - Compatible with any PydanticAI model without configuration changes


# START user constructed package functions for advancing transparency in PydanticAI stack

def create_underneath_pydanticai_logging_client() -> httpx.AsyncClient:
    """Create AsyncClient to access comprehensive request/response logging underneath PydanticAI limitation structure"""
    # Note: this creates the async functions which are called upon request & response each, and then the logger itself.
    # These loggers are then formatted with info/debug loggers for our previously stated use cases with PydanticAI.

    async def log_request(request: httpx.Request):
        """How to log outgoing HTTP requests"""
        logger.info(f"→ {request.method} {request.url}")

        # sanitize the headers to remove confidential information
        sanitized_headers = {}
        for key, value in request.headers.items():
            if key.lower() in ['authorization', 'cookie', 'x-api-key']: sanitized_headers[key] = '[REDACTED]'
            else: sanitized_headers[key] = value
        logger.debug(f"Headers: {json.dumps(sanitized_headers)}")

        # log the outgoing request if present
        if request.content:
            try:
                body = json.loads(request.content.decode())
                logger.info(f"Body: {json.dumps(body)}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.info(f"Body: JSON decoding failed {len(request.content)} bytes")

    async def log_response(response: httpx.Response):
        """How to log incoming HTTP responses"""
        logger.info(f"← {response.status_code} {response.request.url}")
        logger.debug(f"Headers: {json.dumps(dict(response.headers))}")

        # read the log body (for non-streaming)
        try:
            content = await response.aread()
            if content:
                try:
                    # ollama returns what is a double-space delineated list of data fields? and hence not valid JSON?
                    # for this reason we set the exception type to info and more-or-less print the unformatted result
                    body = json.loads(content.decode())
                    logger.info(f"Body: {json.dumps(body)}")
                except json.JSONDecodeError:
                    logger.info(f"Body: JSON decoding failed {content.decode()[:500]}...")
        except Exception as e:
            logger.error(f"Body: an unknown error occurred error={e}")

    return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0),
                             event_hooks={"request": [log_request], "response": [log_response]})


class PydanticAIAgentEventHandler:
    """simple class for inspecting runtime PydanticAI message stacks, before transmuted into HTTP requests/responses"""
    # Note: this does not need to be a class; only the static function is necessary, but we use container classes

    @staticmethod
    async def handle_event(ctx: RunContext, event_stream):
        # Log request information from ctx before processing events
        logger.info(f"event_type=request_start run_id={ctx.run_id} total_messages={len(ctx.messages)}")

        # Log complete message parts from message history. Each message is a list of parts, and each part is either a
        # Prompt type (either system or user) or part of the Tool structure added by Pydantic, i.e., Return or Call.
        for i, message in enumerate(ctx.messages):
            if hasattr(message, 'parts'):
                for j, part in enumerate(message.parts):
                    if hasattr(part, 'content'):
                        if isinstance(part, (SystemPromptPart, UserPromptPart)):
                            # Note: response values are also added here, often as last user_prompt as content= ? (sigh)
                            part_type = "system_prompt" if isinstance(part, SystemPromptPart) else "user_prompt"
                            logger.info(f"event_type={part_type} message_index={i} part_index={j} content={part.content[:200]}...")
                        elif isinstance(part, ToolReturnPart):
                            logger.info(f"event_type=tool_return message_index={i} part_index={j} tool_name={part.tool_name} tool_call_id={part.tool_call_id} content={part.content[:200]}...")
                        elif isinstance(part, ToolCallPart):
                            logger.info(f"event_type=tool_call_request message_index={i} part_index={j} tool_name={part.tool_name} tool_call_id={part.tool_call_id} args={part.args}")

        # Log dependencies context (i.e., the input variables that were used at request tme)
        if hasattr(ctx, 'deps') and ctx.deps:
            logger.info(f"event_type=deps_context category={ctx.deps.category}")

        # Log model information if available (eh why not)
        # Buried in here is also prompted_output_template which appears to be PydanticAI also??? (sigh) todo: what else?
        # see also: https://github.com/pydantic/pydantic-ai/blob/59981e8d9c8eb6f6af6ac64404be0217ab75e63e/pydantic_ai_slim/pydantic_ai/profiles/__init__.py#L44
        if hasattr(ctx, 'model') and ctx.model:
            model_name = getattr(ctx.model, 'model_name', 'unknown')
            model_system = getattr(ctx.model, 'system', 'unknown')
            model_profile = getattr(ctx.model, 'profile', 'unknown')
            logger.info(f"event_type=model_information model_name={model_name} model_system={model_system}")
            logger.info(f"event_type=model_information model_profile={model_profile}")
            try: logger.info(f"event_type=model_alterations prompted_output_template={textwrap.dedent(model_profile.prompted_output_template).replace("\n", " ")}")
            except: pass

        # Log usage statistics if available (these are useful for secondary tracking of round trip usages system-wide)
        if hasattr(ctx, 'usage') and ctx.usage:
            logger.info(f"event_type=usage_context run_id={ctx.run_id} input_tokens={getattr(ctx.usage, 'input_tokens', 'unknown')} output_tokens={getattr(ctx.usage, 'output_tokens', 'unknown')}")

        # Process response events (despite log nomenclature these can be assured to be only of response return values)
        # Their structure is different (sigh) and consist of the LLM text generation (if any, i.e. if Tool is required),
        # its Tool usage (Call, Result), and any PydanticAI post-processing (i.e., extracting structured final results).
        async for event in event_stream:
            if isinstance(event, PartStartEvent):
                logger.info(f"event_type=part_start run_id={ctx.run_id} index={event.index} part={event.part}")
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    logger.info(f"event_type=text_delta run_id={ctx.run_id} index={event.index} content={event.delta.content_delta}")
                elif isinstance(event.delta, ToolCallPartDelta):
                    logger.info(f"event_type=tool_call_delta run_id={ctx.run_id} index={event.index} args={event.delta.args_delta}")
            elif isinstance(event, FunctionToolCallEvent):
                logger.info(f"event_type=tool_call run_id={ctx.run_id} tool={event.part.tool_name} args={event.part.args}")
            elif isinstance(event, FunctionToolResultEvent):
                logger.info(f"event_type=tool_result run_id={ctx.run_id} tool_call_id={event.tool_call_id} result={event.result.content}")
            elif isinstance(event, FinalResultEvent):
                logger.info(f"event_type=final_result run_id={ctx.run_id} tool_name={event.tool_name}")
            else:
                logger.info(f"event_type={type(event).__name__} run_id={ctx.run_id}")

# END user constructed package functions for advancing transparency in PydanticAI stack


# START construction of simplified use case, following the template of the CityLocation example. (notice the ADDED)

class CityLocation(BaseModel):
    city: str
    state: str
    population: int
prompt = "How many people live in the capital of Montana?"

# We are using Ollama, but our solution should be model dependent. Define the core LLM characteristics
# ADDED: we use our own async client with logging and hook into OllamaProvider
# Note: our async client does not inherit from the base PydanticAI client, and this would be an important improvement
ollama_endpoint = "http://127.0.0.1:11434/v1"
ollama_model_name = "qwen2.5:3b"

# client_with_logging = None  # may pass None to use PydanticAI default mechanism
client_with_logging = create_underneath_pydanticai_logging_client()
provider = OllamaProvider(base_url=ollama_endpoint, http_client=client_with_logging)
llm = OpenAIChatModel(model_name=ollama_model_name, provider=provider)

# ADDED: event_stream_handler points to our event handler static function (it is not a class) and we set the
# instrument=InstrumentationSettings(include_content=True) so that more information is provided in (ctx, events)
start = time.perf_counter()
agent = Agent(llm, output_type=CityLocation,
              event_stream_handler=PydanticAIAgentEventHandler.handle_event,
              instrument=InstrumentationSettings(include_content=True))  # add full message for event_stream_handler
_to_build = time.perf_counter() - start # usually 0.007 seconds, i.e., can be constructed in real-time runtime

# ADDED notice that we must run async here. this use of asyncio.run() very occasionally caused thread context hiccups
result = asyncio.run(agent.run(prompt))
_to_run = time.perf_counter() - start
logger.info(f"agent to_build={_to_build:.3f}s to_run={_to_run:.3f}s success=True")
logger.info(f"result={result.output}")

# END user constructed package functions for advancing transparency in PydanticAI stack

# RESULTS:
# NOTE: text_delta usually does not return one token at a time. this was in fact the first time that was observed.
# NOTE: I am adding a second run that also includes its failure on the first retry. In that line of logs (only the
# deeper request now enabled by our httpx async client, sigh) you can see the additional "Fix the errors and try again."
# line added as the retry prompt. This would be the fourth way that PydanticAI operates its Agents to reach structured
# data, although some may argue that such technical sophistication does very little to help naive LLMs correct mistakes. 
# It is left as an exercise to the reader to improve these systems and identify how robust workflows of the future work.
# RUN: 11:48AM January 19, 2025, etc.

# Connected to pydev debugger (build 253.29346.138)
# INFO:__main__:→ POST http://[REDACTED]/v1/chat/completions
# INFO:__main__:Body: {"messages": [{"role": "user", "content": "How many people live in the capital of Montana?"}], "model": "qwen2.5:3b", "stream": true, "stream_options": {"include_usage": true}, "tool_choice": "required", "tools": [{"type": "function", "function": {"name": "final_result", "description": "The final response which ends this conversation", "parameters": {"properties": {"city": {"type": "string"}, "state": {"type": "string"}, "population": {"type": "integer"}}, "required": ["city", "state", "population"], "title": "CityLocation", "type": "object"}, "strict": true}}]}
# INFO:httpx:HTTP Request: POST http://[REDACTED]/v1/chat/completions "HTTP/1.1 200 OK"
# INFO:__main__:← 200 http://[REDACTED]/v1/chat/completions
# INFO:__main__:Body: JSON decoding failed data: {"id":"chatcmpl-160","object":"chat.completion.chunk","created":1768840970,"model":"qwen2.5:3b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":"To"},"finish_reason":null}]}
# 
# data: {"id":"chatcmpl-160","object":"chat.completion.chunk","created":1768840970,"model":"qwen2.5:3b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":" find"},"finish_reason":null}]}
# 
# data: {"id":"chatcmpl-160","object":"chat.com...
#        INFO:__main__:event_type=request_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e total_messages=1
# INFO:__main__:event_type=user_prompt message_index=0 part_index=0 content=How many people live in the capital of Montana?...
# INFO:__main__:event_type=model_information model_name=qwen2.5:3b model_system=ollama
# INFO:__main__:event_type=model_information model_profile=OpenAIModelProfile(supports_tools=True, supports_json_schema_output=False, supports_json_object_output=False, supports_image_output=False, default_structured_output_mode='tool', prompted_output_template="\nAlways respond with a JSON object that's compatible with this schema:\n\n{schema}\n\nDon't include any text or Markdown fencing before or after.\n", native_output_requires_schema_in_instructions=False, json_schema_transformer=<class 'pydantic_ai._json_schema.InlineDefsJsonSchemaTransformer'>, thinking_tags=('<think>', '</think>'), ignore_streamed_leading_whitespace=True, supported_builtin_tools=frozenset(), openai_chat_thinking_field='reasoning', openai_chat_send_back_thinking_parts='tags', openai_supports_strict_tool_definition=True, openai_supports_sampling_settings=True, openai_unsupported_model_settings=(), openai_supports_tool_choice_required=True, openai_system_prompt_role=None, openai_chat_supports_web_search=False, openai_chat_audio_input_encoding='base64', openai_supports_encrypted_reasoning_content=False, openai_responses_requires_function_call_status_none=False)
# INFO:__main__:event_type=model_alterations prompted_output_template= Always respond with a JSON object that's compatible with this schema:  {schema}  Don't include any text or Markdown fencing before or after.
# INFO:__main__:event_type=usage_context run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e input_tokens=0 output_tokens=0
# INFO:__main__:event_type=part_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 part=TextPart(content='To')
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= find
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= out
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= how
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= many
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= people
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= live
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= in
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= of
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Montana
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= I
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= need
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= to
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= know
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= which
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= you
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content='re
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= referring
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= to
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=.
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= The
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= cities
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= vary
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= over
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= time
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= or
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= place
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= depending
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= on
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= specific
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= region
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content='s
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= structure
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=.
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Could
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= you
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= please
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= specify
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= metropolitan
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= area
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= or
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= its
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= current
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= city
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= within
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Montana
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= that
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= you
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= are
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= interested
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= in
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=?
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= For
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= instance
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= is
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= it
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Helena
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Bill
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=ings
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Great
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Falls
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Miss
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=ou
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=la
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Bo
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=z
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=eman
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Kal
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=isp
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=ell
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= or
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= any
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= other
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Montana
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= cities
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=?
# INFO:__main__:event_type=PartEndEvent run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e
# INFO:__main__:event_type=request_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e total_messages=2
# INFO:__main__:event_type=user_prompt message_index=0 part_index=0 content=How many people live in the capital of Montana?...
# INFO:__main__:event_type=model_information model_name=qwen2.5:3b model_system=ollama
# INFO:__main__:event_type=model_information model_profile=OpenAIModelProfile(supports_tools=True, supports_json_schema_output=False, supports_json_object_output=False, supports_image_output=False, default_structured_output_mode='tool', prompted_output_template="\nAlways respond with a JSON object that's compatible with this schema:\n\n{schema}\n\nDon't include any text or Markdown fencing before or after.\n", native_output_requires_schema_in_instructions=False, json_schema_transformer=<class 'pydantic_ai._json_schema.InlineDefsJsonSchemaTransformer'>, thinking_tags=('<think>', '</think>'), ignore_streamed_leading_whitespace=True, supported_builtin_tools=frozenset(), openai_chat_thinking_field='reasoning', openai_chat_send_back_thinking_parts='tags', openai_supports_strict_tool_definition=True, openai_supports_sampling_settings=True, openai_unsupported_model_settings=(), openai_supports_tool_choice_required=True, openai_system_prompt_role=None, openai_chat_supports_web_search=False, openai_chat_audio_input_encoding='base64', openai_supports_encrypted_reasoning_content=False, openai_responses_requires_function_call_status_none=False)
# INFO:__main__:event_type=model_alterations prompted_output_template= Always respond with a JSON object that's compatible with this schema:  {schema}  Don't include any text or Markdown fencing before or after.
# INFO:__main__:event_type=usage_context run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e input_tokens=177 output_tokens=92
# INFO:__main__:→ POST http://[REDACTED]/v1/chat/completions
# INFO:__main__:Body: {"messages": [{"role": "user", "content": "How many people live in the capital of Montana?"}, {"role": "assistant", "content": "To find out how many people live in the capital of Montana, I need to know which capital you're referring to. The capital cities vary over time or place depending on the specific region's structure. Could you please specify the metropolitan area or its current capital city within Montana that you are interested in? For instance, is it Helena, Billings, Great Falls, Missoula, Bozeman, Kalispell, or any other Montana cities?"}, {"role": "user", "content": "1 validation error:\n```json\n[\n  {\n    \"type\": \"json_invalid\",\n    \"loc\": [],\n    \"msg\": \"Invalid JSON: expected value at line 1 column 1\",\n    \"input\": \"To find out how many people live in the capital of Montana, I need to know which capital you're referring to. The capital cities vary over time or place depending on the specific region's structure. Could you please specify the metropolitan area or its current capital city within Montana that you are interested in? For instance, is it Helena, Billings, Great Falls, Missoula, Bozeman, Kalispell, or any other Montana cities?\"\n  }\n]\n```\n\nFix the errors and try again."}], "model": "qwen2.5:3b", "stream": true, "stream_options": {"include_usage": true}, "tool_choice": "required", "tools": [{"type": "function", "function": {"name": "final_result", "description": "The final response which ends this conversation", "parameters": {"properties": {"city": {"type": "string"}, "state": {"type": "string"}, "population": {"type": "integer"}}, "required": ["city", "state", "population"], "title": "CityLocation", "type": "object"}, "strict": true}}]}
# INFO:httpx:HTTP Request: POST http://[REDACTED]/v1/chat/completions "HTTP/1.1 200 OK"
# INFO:__main__:← 200 http://[REDACTED]/v1/chat/completions
# INFO:__main__:Body: JSON decoding failed data: {"id":"chatcmpl-467","object":"chat.completion.chunk","created":1768840971,"model":"qwen2.5:3b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":"It"},"finish_reason":null}]}
# 
# data: {"id":"chatcmpl-467","object":"chat.completion.chunk","created":1768840972,"model":"qwen2.5:3b","system_fingerprint":"fp_ollama","choices":[{"index":0,"delta":{"role":"assistant","content":" seems"},"finish_reason":null}]}
# 
# data: {"id":"chatcmpl-467","object":"chat.co...
# INFO:__main__:event_type=request_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e total_messages=3
# INFO:__main__:event_type=user_prompt message_index=0 part_index=0 content=How many people live in the capital of Montana?...
# INFO:__main__:event_type=model_information model_name=qwen2.5:3b model_system=ollama
# INFO:__main__:event_type=model_information model_profile=OpenAIModelProfile(supports_tools=True, supports_json_schema_output=False, supports_json_object_output=False, supports_image_output=False, default_structured_output_mode='tool', prompted_output_template="\nAlways respond with a JSON object that's compatible with this schema:\n\n{schema}\n\nDon't include any text or Markdown fencing before or after.\n", native_output_requires_schema_in_instructions=False, json_schema_transformer=<class 'pydantic_ai._json_schema.InlineDefsJsonSchemaTransformer'>, thinking_tags=('<think>', '</think>'), ignore_streamed_leading_whitespace=True, supported_builtin_tools=frozenset(), openai_chat_thinking_field='reasoning', openai_chat_send_back_thinking_parts='tags', openai_supports_strict_tool_definition=True, openai_supports_sampling_settings=True, openai_unsupported_model_settings=(), openai_supports_tool_choice_required=True, openai_system_prompt_role=None, openai_chat_supports_web_search=False, openai_chat_audio_input_encoding='base64', openai_supports_encrypted_reasoning_content=False, openai_responses_requires_function_call_status_none=False)
# INFO:__main__:event_type=model_alterations prompted_output_template= Always respond with a JSON object that's compatible with this schema:  {schema}  Don't include any text or Markdown fencing before or after.
# INFO:__main__:event_type=usage_context run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e input_tokens=177 output_tokens=92
# INFO:__main__:event_type=part_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 part=TextPart(content='It')
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= seems
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= there
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content='s
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= a
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= misunderstanding
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= with
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= structure
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= of
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= question
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= you
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= provided
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=.
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Let
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content='s
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= correct
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= this
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= by
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= directly
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= asking
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= about
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= population
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= in
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Helena
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= as
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= it
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= is
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= often
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= considered
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= city
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= for
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= statistical
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= purposes
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=.
# 
# 
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=I
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content='ll
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= proceed
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= to
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= query
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= how
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= many
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= people
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= live
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= in
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Helena
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= Montana
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=,
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= which
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= is
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= typically
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= recognized
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= as
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= the
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= capital
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content= city
# INFO:__main__:event_type=text_delta run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=0 content=.
# 
# INFO:__main__:event_type=PartEndEvent run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e
# INFO:__main__:event_type=part_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e index=1 part=ToolCallPart(tool_name='final_result', args='{"city":"Helena","population":49576,"state":"Montana"}', tool_call_id='call_uhwdsc4h')
# INFO:__main__:event_type=final_result run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e tool_name=final_result
# INFO:__main__:event_type=PartEndEvent run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e
# INFO:__main__:event_type=request_start run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e total_messages=4
# INFO:__main__:event_type=user_prompt message_index=0 part_index=0 content=How many people live in the capital of Montana?...
# INFO:__main__:event_type=model_information model_name=qwen2.5:3b model_system=ollama
# INFO:__main__:event_type=model_information model_profile=OpenAIModelProfile(supports_tools=True, supports_json_schema_output=False, supports_json_object_output=False, supports_image_output=False, default_structured_output_mode='tool', prompted_output_template="\nAlways respond with a JSON object that's compatible with this schema:\n\n{schema}\n\nDon't include any text or Markdown fencing before or after.\n", native_output_requires_schema_in_instructions=False, json_schema_transformer=<class 'pydantic_ai._json_schema.InlineDefsJsonSchemaTransformer'>, thinking_tags=('<think>', '</think>'), ignore_streamed_leading_whitespace=True, supported_builtin_tools=frozenset(), openai_chat_thinking_field='reasoning', openai_chat_send_back_thinking_parts='tags', openai_supports_strict_tool_definition=True, openai_supports_sampling_settings=True, openai_unsupported_model_settings=(), openai_supports_tool_choice_required=True, openai_system_prompt_role=None, openai_chat_supports_web_search=False, openai_chat_audio_input_encoding='base64', openai_supports_encrypted_reasoning_content=False, openai_responses_requires_function_call_status_none=False)
# INFO:__main__:event_type=model_alterations prompted_output_template= Always respond with a JSON object that's compatible with this schema:  {schema}  Don't include any text or Markdown fencing before or after.
# INFO:__main__:event_type=usage_context run_id=2767ba69-f0c5-4d7d-860e-e2b6fcbcb09e input_tokens=604 output_tokens=190
# INFO:__main__:agent to_build=0.004s to_run=3.677s success=True
# INFO:__main__:result=city='Helena' state='Montana' population=49576
# 
# Process finished with exit code 0
