from __future__ import annotations

from dataclasses import dataclass
from math import isclose, tau


def normalize_degrees(angle_degrees: float) -> float:
    return angle_degrees % 360.0


def degrees_to_radians(angle_degrees: float) -> float:
    return angle_degrees * tau / 360.0


def radians_to_degrees(angle_radians: float) -> float:
    return angle_radians * 360.0 / tau


@dataclass(frozen=True, slots=True)
class AngleRange:
    start_degrees: float
    end_degrees: float

    @property
    def is_full_circle(self) -> bool:
        normalized_start = normalize_degrees(self.start_degrees)
        normalized_end = normalize_degrees(self.end_degrees)
        return not isclose(self.start_degrees, self.end_degrees) and isclose(
            normalized_start, normalized_end
        )

    def contains(self, angle_degrees: float) -> bool:
        if self.is_full_circle:
            return True

        start = normalize_degrees(self.start_degrees)
        end = normalize_degrees(self.end_degrees)
        angle = normalize_degrees(angle_degrees)

        if isclose(start, end):
            return isclose(angle, start)

        if start <= end:
            return start <= angle <= end

        return angle >= start or angle <= end


@dataclass(frozen=True, slots=True)
class JointSpec:
    name: str
    motor_id: int
    angle_range: AngleRange
    home_degrees: float

    def validate(self, angle_degrees: float) -> None:
        if not self.angle_range.contains(angle_degrees):
            raise ValueError(
                f"{self.name} cannot move to {angle_degrees} degrees; allowed range is "
                f"{self.angle_range.start_degrees} to {self.angle_range.end_degrees} degrees"
            )

    def validate_home(self) -> None:
        self.validate(self.home_degrees)
