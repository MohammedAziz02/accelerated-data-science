import importlib
import importlib.util
import logging
import os
import sys
from copy import deepcopy
from typing import Any, List, Optional
from langchain.llms.base import LLM
from langchain.schema.runnable import (
    Runnable,
    RunnableConfig,
    RunnableSequence,
)
from . import guardrails
from .guardrails.base import GuardrailIO, Guardrail, RunInfo


logger = logging.getLogger(__name__)
BLOCKED_MESSAGE = "custom_msg"
SPEC_CLASS = "class"
SPEC_PATH = "path"
SPEC_SPEC = "spec"


class GuardrailSequence(RunnableSequence):
    """Represents a sequence of guardrails and other LangChain (non-guardrail) components."""

    first: Optional[Runnable] = None
    last: Optional[Runnable] = None

    @property
    def steps(self) -> List[Runnable[Any, Any]]:
        if self.first:
            chain = [self.first] + self.middle
        else:
            return []
        if self.last:
            chain += [self.last]
        return chain

    @classmethod
    def from_sequence(cls, sequence: RunnableSequence):
        return cls(first=sequence.first, middle=sequence.middle, last=sequence.last)

    def __or__(self, other) -> "GuardrailSequence":
        if not self.first:
            return GuardrailSequence(first=other)
        if not self.last:
            return GuardrailSequence(first=self.first, last=other)
        return self.from_sequence(super().__or__(other))

    def __ror__(self, other) -> "GuardrailSequence":
        return self.from_sequence(super().__ror__(other))

    def invoke(self, input: Any, config: RunnableConfig = None) -> GuardrailIO:
        """Invokes the guardrail.

        In LangChain interface, invoke() is designed for calling the chain with a single input,
        while batch() is designed for calling the chain with a list of inputs.
        https://python.langchain.com/docs/expression_language/interface

        """
        return self.run(input)

    def _invoke_llm(self, llm, texts, num_generations, **kwargs):
        if num_generations > 1:
            if len(texts) > 1:
                raise NotImplementedError(
                    "Batch completion with more than 1 prompt is not supported."
                )
            # TODO: invoke in parallel
            # TODO: let llm generate n completions.
            output = [llm.invoke(texts[0], **kwargs) for _ in range(num_generations)]
        else:
            output = llm.batch(texts, **kwargs)
        return output

    def run(self, input: Any, num_generations=1, **kwargs) -> GuardrailIO:
        obj = GuardrailIO(data=[input])

        for i, step in enumerate(self.steps):
            if not isinstance(step, Guardrail):
                # Invoke the step as a LangChain component
                spec = {}
                with RunInfo(name=step.__class__.__name__, input=obj.data) as info:
                    if isinstance(step, LLM):
                        output = self._invoke_llm(
                            step, obj.data, num_generations, **kwargs
                        )
                        spec.update(kwargs)
                        spec["num_generations"] = num_generations
                    else:
                        output = step.batch(obj.data)
                    info.output = output
                    info.parameters = {
                        "class": step.__class__.__name__,
                        "path": step.__module__,
                        "spec": spec,
                    }
                obj.info.append(info)
                obj.data = output
            else:
                obj = step.invoke(obj)
            if not obj.data:
                default_msg = f"Blocked by {step.__class__.__name__}"
                msg = getattr(step, BLOCKED_MESSAGE, default_msg)
                if msg is None:
                    msg = default_msg
                obj.data = [msg]
                return obj
        return obj

    def save(self):
        BUILT_IN = "ads.opctl.operator.lowcode.responsible_ai.guardrails"
        chain_spec = []
        for step in self.steps:
            if step.__module__.startswith(BUILT_IN):
                class_name = step.__class__.__name__
                path = getattr(step, "path", None)
            else:
                class_name = step.__class__.__name__
                path = step.__module__
            logger.debug("class: %s | path: %s", class_name, path)
            chain_spec.append(
                {SPEC_CLASS: class_name, SPEC_PATH: path, SPEC_SPEC: step.dict()}
            )
        return chain_spec

    def __str__(self) -> str:
        return "\n".join([str(step.__class__) for step in self.steps])

    @staticmethod
    def _load_class_from_file(file_path, class_name):
        module_name = file_path
        module_spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return getattr(module, class_name)

    @staticmethod
    def _load_class_from_module(module_name, class_name):
        component_module = importlib.import_module(module_name)
        return getattr(component_module, class_name)

    @staticmethod
    def load_component(config):
        spec = deepcopy(config.get(SPEC_SPEC, {}))
        spec: dict
        class_name = config[SPEC_CLASS]
        # Load the guardrail
        if hasattr(guardrails, class_name):
            # Built-in guardrail, including custom huggingface guardrail
            component_class = getattr(guardrails, class_name)
            # Copy the path into spec if it is not already there
            if SPEC_PATH in config and SPEC_PATH not in spec:
                spec[SPEC_PATH] = config[SPEC_PATH]
        elif SPEC_PATH in config:
            # Custom component
            path = config[SPEC_PATH]
            if os.path.exists(path):
                component_class = GuardrailSequence._load_class_from_file(
                    path, class_name
                )
            else:
                component_class = GuardrailSequence._load_class_from_module(
                    path, class_name
                )
        elif "." in class_name:
            # LangChain component
            module_name, class_name = class_name.rsplit(".", 1)
            component_class = GuardrailSequence._load_class_from_module(
                module_name, class_name
            )
        else:
            raise ValueError(f"Invalid Guardrail: {class_name}")
        return component_class(**spec)

    @classmethod
    def load(cls, chain_spec):
        chain = cls()
        for config in chain_spec:
            guardrail = cls.load_component(config)
            # Chain the guardrail
            chain |= guardrail
        return chain
