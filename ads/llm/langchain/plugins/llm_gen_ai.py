#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import logging
from typing import Any, Dict, List, Optional

from langchain.callbacks.manager import CallbackManagerForLLMRun
from ads.llm.langchain.plugins.base import StrEnum, BaseLLM, GenerativeAiClientModel


logger = logging.getLogger(__name__)


# Move to constant.py
class Task(StrEnum):
    TEXT_GENERATION = "text_generation"
    SUMMARY_TEXT = "summary_text"


class LengthParamOptions:
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"
    AUTO = "AUTO"


class FormatParamOptions:
    PARAGRAPH = "PARAGRAPH"
    BULLETS = "BULLETS"
    AUTO = "AUTO"


class ExtractivenessParamOptions:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    AUTO = "AUTO"


class OCIGenerativeAIModelOptions:
    COHERE_COMMAND = "cohere.command"
    COHERE_COMMAND_LIGHT = "cohere.command-light"


class GenerativeAI(GenerativeAiClientModel, BaseLLM):
    """GenerativeAI Service.

    To use, you should have the ``oci`` python package installed.

    Example
    -------

    .. code-block:: python

        from ads.llm import GenerativeAI

        gen_ai = GenerativeAI(compartment_id="ocid1.compartment.oc1..<ocid>")

    """

    task: Task = Task.TEXT_GENERATION
    """Indicates the task."""

    model: Optional[str] = OCIGenerativeAIModelOptions.COHERE_COMMAND
    """Model name to use."""

    frequency_penalty: float = None
    """Penalizes repeated tokens according to frequency. Between 0 and 1."""

    presence_penalty: float = None
    """Penalizes repeated tokens. Between 0 and 1."""

    truncate: Optional[str] = None
    """Specify how the client handles inputs longer than the maximum token."""

    length: str = LengthParamOptions.AUTO
    """Indicates the approximate length of the summary. """

    format: str = FormatParamOptions.PARAGRAPH
    """Indicates the style in which the summary will be delivered - in a free form paragraph or in bullet points."""

    extractiveness: str = ExtractivenessParamOptions.AUTO
    """Controls how close to the original text the summary is. High extractiveness summaries will lean towards reusing sentences verbatim, while low extractiveness summaries will tend to paraphrase more."""

    additional_command: str = ""
    """A free-form instruction for modifying how the summaries get generated. """

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Get the identifying parameters."""
        return {
            **{
                "model": self.model,
                "task": self.task,
                "client_kwargs": self.client_kwargs,
                "endpoint_kwargs": self.endpoint_kwargs,
            },
            **self._default_params,
        }

    @property
    def _llm_type(self) -> str:
        """Return type of llm."""
        return "GenerativeAI"

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling OCIGenerativeAI API."""
        from oci.generative_ai.models import OnDemandServingMode

        return (
            {
                "serving_mode": OnDemandServingMode(model_id=self.model),
                "compartment_id": self.compartment_id,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "top_k": self.k,
                "top_p": self.p,
                "frequency_penalty": self.frequency_penalty,
                "presence_penalty": self.presence_penalty,
                "truncate": self.truncate,
            }
            if self.task == Task.TEXT_GENERATION
            else {
                "serving_mode": OnDemandServingMode(model_id=self.model),
                "compartment_id": self.compartment_id,
                "temperature": self.temperature,
                "length": self.length,
                "format": self.format,
                "extractiveness": self.extractiveness,
                "additional_command": self.additional_command,
            }
        )

    def _invocation_params(self, stop: Optional[List[str]], **kwargs: Any) -> dict:
        params = self._default_params
        if self.task == Task.SUMMARY_TEXT:
            return {**params}

        if self.stop is not None and stop is not None:
            raise ValueError("`stop` found in both the input and default params.")
        elif self.stop is not None:
            params["stop_sequences"] = self.stop
        else:
            params["stop_sequences"] = stop
        return {**params, **kwargs}

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ):
        """Call out to GenerativeAI's generate endpoint.

        Parameters
        ----------
        prompt: The prompt to pass into the model.
        stop: Optional list of stop words to use when generating.

        Returns
        -------
        The string generated by the model.

        Example
        -------

            .. code-block:: python

                response = gen_ai("Tell me a joke.")
        """

        params = self._invocation_params(stop, **kwargs)

        try:
            response = (
                self.completion_with_retry(prompts=[prompt], **params)
                if self.task == Task.TEXT_GENERATION
                else self.completion_with_retry(input=prompt, **params)
            )
        except Exception:
            logger.error(
                "Error occur when invoking oci service api."
                "DEBUG INTO: task=%s, params=%s, prompt=%s",
                self.task,
                params,
                prompt,
            )
            raise

        return self._process_response(response, params.get("num_generations", 1))

    def _process_response(self, response: Any, num_generations: int = 1) -> str:
        if self.task == Task.SUMMARY_TEXT:
            return response.data.summary

        return (
            response.data.generated_texts[0][0].text
            if num_generations == 1
            else [gen.text for gen in response.data.generated_texts[0]]
        )

    def completion_with_retry(self, **kwargs: Any) -> Any:
        # TODO: Add retry logic for OCI
        from oci.generative_ai.models import GenerateTextDetails, SummarizeTextDetails

        if self.task == Task.TEXT_GENERATION:
            return self.client.generate_text(
                GenerateTextDetails(**kwargs), **self.endpoint_kwargs
            )
        else:
            return self.client.summarize_text(
                SummarizeTextDetails(**kwargs), **self.endpoint_kwargs
            )

    def batch_completion(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        num_generations: int = 1,
        **kwargs: Any,
    ) -> List[str]:
        """Generates multiple completion for the given prompt.

        Parameters
        ----------
        prompt (str):
            The prompt to pass into the model.
        stop: (List[str], optional):
            Optional list of stop words to use when generating. Defaults to None.
        num_generations (int, optional):
            Number of completions aims to get. Defaults to 1.

        Raises
        ------
        NotImplementedError
            Raise when invoking batch_completion under summarization task.

        Returns
        -------
        List[str]
            List of multiple completions.

        Example
        -------

            .. code-block:: python

                responses = gen_ai.batch_completion("Tell me a joke.", num_generations=5)

        """
        if self.task == Task.SUMMARY_TEXT:
            raise NotImplementedError(
                f"task={Task.SUMMARY_TEXT} does not support batch_completion. "
            )

        return self._call(
            prompt=prompt,
            stop=stop,
            run_manager=run_manager,
            num_generations=num_generations,
            **kwargs,
        )
