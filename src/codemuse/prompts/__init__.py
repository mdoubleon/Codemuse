"""预留系统提示词和提示模板的包入口。"""
"""Public prompt-template loading API."""

from codemuse.prompts.loader import BUILTIN_PROMPTS_DIR, load_prompt, load_prompt_templates, prompt_search_paths

__all__ = ["BUILTIN_PROMPTS_DIR", "load_prompt", "load_prompt_templates", "prompt_search_paths"]
