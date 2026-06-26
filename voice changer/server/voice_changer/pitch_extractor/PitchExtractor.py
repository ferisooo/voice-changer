from typing import Protocol
import torch


class PitchExtractor(Protocol):
    type: str

    def extract(
        self,
        audio: torch.Tensor,
        sr: int,
        window: int,
    ) -> torch.Tensor:
        ...

    def set_threshold(self, value: float):
        # Voiced/unvoiced confidence cutoff. Only meaningful for detectors that
        # expose one (RMVPE); a no-op elsewhere.
        ...

    def getPitchExtractorInfo(self):
        return {
            "pitchExtractorType": self.type,
        }
