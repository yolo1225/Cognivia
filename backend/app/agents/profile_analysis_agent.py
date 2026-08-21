"""Standalone V3 boundary for deterministic learner-profile analysis."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.agents.contracts import AnalyzeProfileInput, AnalyzeProfileOutput
from app.agents.profile_analysis_config import ProfileAnalysisConfig
from app.agents.prompt_registry import get_prompt
from app.services.profile_analysis_service import ProfileAnalysisError, analyze_profile


PROFILE_ANALYSIS_AGENT_NAME = "profile_analysis_agent_v3"
SYSTEM_PROMPT = get_prompt("profile")


class ProfileAnalysisAgent:
    """Isolated V3 Agent boundary; it deliberately does not inherit legacy BaseAgent."""

    name = PROFILE_ANALYSIS_AGENT_NAME
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        config: ProfileAnalysisConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger(__name__)

    def execute(self, request: AnalyzeProfileInput) -> AnalyzeProfileOutput:
        """Validate one V3 request, run the pure algorithm, and emit safe observability."""
        if not isinstance(request, AnalyzeProfileInput):
            self._logger.warning(
                "profile_analysis_rejected error_code=invalid_analyze_profile_input_type"
            )
            raise ProfileAnalysisError("invalid_analyze_profile_input_type")

        try:
            validated_request = AnalyzeProfileInput.model_validate(
                request.model_dump(mode="python")
            )
        except ValidationError as exc:
            self._log_failure(request, "invalid_analyze_profile_input")
            raise ProfileAnalysisError("invalid_analyze_profile_input") from exc

        try:
            raw_output = analyze_profile(validated_request, config=self._config)
            output = AnalyzeProfileOutput.model_validate(raw_output.model_dump(mode="python"))
        except ProfileAnalysisError as exc:
            self._log_failure(validated_request, str(exc))
            raise
        except ValidationError as exc:
            self._log_failure(validated_request, "invalid_analyze_profile_output")
            raise ProfileAnalysisError("invalid_analyze_profile_output") from exc
        except Exception as exc:
            self._log_failure(validated_request, "profile_analysis_execution_failed")
            raise ProfileAnalysisError("profile_analysis_execution_failed") from exc

        self._logger.info(
            "profile_analysis_completed task_id=%s profile_id=%s profile_version=%s "
            "profile_update_required=%s changed_dimensions=%s evidence_count=%s confidence=%s",
            output.task_id,
            output.profile.profile_id,
            output.profile.profile_version,
            output.profile_update_required,
            output.changed_dimensions,
            len(output.evidence_refs),
            output.confidence,
        )
        return output

    def _log_failure(self, request: AnalyzeProfileInput, error_code: str) -> None:
        self._logger.warning(
            "profile_analysis_failed task_id=%s profile_id=%s error_code=%s",
            request.task_id,
            request.current_profile.profile_id,
            error_code,
        )
