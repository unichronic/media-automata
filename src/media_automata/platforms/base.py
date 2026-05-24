from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from media_automata.config import Settings
from media_automata.schemas import ErrorCode, PlatformResult, PlatformTaskPayload
from media_automata.storage import LocalStorage


@dataclass
class WorkerContext:
    settings: Settings
    storage: LocalStorage
    profile_path: Path
    artifact_root: Path

    def asset_paths(self, asset_ids: list[str], asset_lookup: dict[str, str]) -> list[str]:
        paths: list[str] = []
        for asset_id in asset_ids:
            uri = asset_lookup.get(asset_id)
            if uri:
                paths.append(str(self.storage.resolve(uri)))
        return paths


class PlatformWorker(ABC):
    @abstractmethod
    async def publish_post(
        self,
        payload: PlatformTaskPayload,
        context: WorkerContext,
        asset_lookup: dict[str, str],
    ) -> PlatformResult:
        raise NotImplementedError


class BrowserDependencyError(RuntimeError):
    pass


def dependency_error_result(payload: PlatformTaskPayload, error: Exception) -> PlatformResult:
    return PlatformResult(
        platform=payload.platform,
        status="failed",
        message=str(error),
        error_code=ErrorCode.INTERNAL_ERROR,
    )
