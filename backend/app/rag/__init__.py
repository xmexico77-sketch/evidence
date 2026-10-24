"""RAG 层：检索增强问答与抗幻觉校验。"""
from .answerer import AnswerResult, Evidence, GroundedAnswerer, validate_markers

__all__ = ["AnswerResult", "Evidence", "GroundedAnswerer", "validate_markers"]
