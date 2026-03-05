# ---------------------------------------------------------------------------
# motor.py  —  NEMA stepper motor simulation + trapezoidal velocity profile
# ---------------------------------------------------------------------------
from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class ProfileResult:
    """Output of TrapezoidalProfile.compute()."""
    distance_mm: float
    peak_speed_mm_s: float      # may be < feedrate on short (triangular) moves
    accel_distance_mm: float
    cruise_distance_mm: float
    decel_distance_mm: float
    accel_time_s: float
    cruise_time_s: float
    decel_time_s: float

    @property
    def total_time_s(self) -> float:
        return self.accel_time_s + self.cruise_time_s + self.decel_time_s


class TrapezoidalProfile:
    """
    Stateless trapezoidal velocity profile calculator.

    Converts a distance + feedrate + acceleration into a time-distance
    profile that can be queried at any distance position to get
    the instantaneous speed.
    """

    @staticmethod
    def compute(
        distance_mm: float,
        feedrate_mm_s: float,
        accel_mm_s2: float,
    ) -> ProfileResult:
        if distance_mm <= 0:
            return ProfileResult(0, 0, 0, 0, 0, 0, 0, 0)

        # Distance required to ramp up to full feedrate and back down
        accel_dist = (feedrate_mm_s ** 2) / (2.0 * accel_mm_s2)
        full_ramp_dist = 2.0 * accel_dist  # accel + decel

        if full_ramp_dist <= distance_mm:
            # Trapezoidal profile — reaches full feedrate
            peak = feedrate_mm_s
            cruise_dist = distance_mm - full_ramp_dist
            t_accel = peak / accel_mm_s2
            t_cruise = cruise_dist / peak
            t_decel = t_accel
        else:
            # Triangular profile — too short to reach full feedrate
            # v_peak = sqrt(a * d)
            peak = math.sqrt(accel_mm_s2 * distance_mm)
            accel_dist = distance_mm / 2.0
            cruise_dist = 0.0
            t_accel = peak / accel_mm_s2
            t_cruise = 0.0
            t_decel = t_accel

        return ProfileResult(
            distance_mm=distance_mm,
            peak_speed_mm_s=peak,
            accel_distance_mm=accel_dist,
            cruise_distance_mm=cruise_dist,
            decel_distance_mm=accel_dist,
            accel_time_s=t_accel,
            cruise_time_s=t_cruise,
            decel_time_s=t_decel,
        )

    @staticmethod
    def speed_at_distance(profile: ProfileResult, d: float) -> float:
        """Return instantaneous speed (mm/s) at distance d into the move."""
        if profile.distance_mm <= 0 or d <= 0:
            return 0.0
        if d >= profile.distance_mm:
            return 0.0

        a = profile.accel_distance_mm
        c = profile.cruise_distance_mm

        if d <= a:
            # Accelerating: v = sqrt(2 * a_mm_s2 * d)
            # Derive a_mm_s2 from peak speed and accel distance
            if a > 0:
                a_mm_s2 = (profile.peak_speed_mm_s ** 2) / (2.0 * a)
            else:
                a_mm_s2 = 0.0
            return math.sqrt(max(0.0, 2.0 * a_mm_s2 * d))
        elif d <= a + c:
            # Cruising
            return profile.peak_speed_mm_s
        else:
            # Decelerating
            d_into_decel = d - (a + c)
            decel_total = profile.decel_distance_mm
            if decel_total > 0:
                a_mm_s2 = (profile.peak_speed_mm_s ** 2) / (2.0 * decel_total)
            else:
                a_mm_s2 = 0.0
            remaining = decel_total - d_into_decel
            return math.sqrt(max(0.0, 2.0 * a_mm_s2 * remaining))


class StepperMotor:
    """
    Simulates a single NEMA stepper motor axis.

    Tracks accumulated steps and derives position in mm.
    Does not handle timing — the caller (Gantry) controls when steps happen.
    """

    def __init__(
        self,
        name: str,
        steps_per_mm: float,
        microsteps: int = 16,
        max_feedrate_mm_s: float = 150.0,
        acceleration_mm_s2: float = 500.0,
    ) -> None:
        self.name = name
        self.steps_per_mm = steps_per_mm
        self.microsteps = microsteps
        self.max_feedrate_mm_s = max_feedrate_mm_s
        self.acceleration_mm_s2 = acceleration_mm_s2

        self._step_count: int = 0
        self._current_speed_mm_s: float = 0.0
        self._direction: int = 1  # +1 or -1

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def step(self, direction: int, count: int = 1) -> None:
        """Advance motor by `count` steps in `direction` (+1 or -1)."""
        direction = 1 if direction >= 0 else -1
        self._direction = direction
        self._step_count += direction * count

    def set_speed(self, speed_mm_s: float) -> None:
        """Update instantaneous speed, clamped to max feedrate."""
        self._current_speed_mm_s = min(abs(speed_mm_s), self.max_feedrate_mm_s)

    def reset(self) -> None:
        """Zero position (used on homing)."""
        self._step_count = 0
        self._current_speed_mm_s = 0.0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_position_mm(self) -> float:
        return self._step_count / self.steps_per_mm

    def get_step_count(self) -> int:
        return self._step_count

    def mm_to_steps(self, mm: float) -> int:
        return round(mm * self.steps_per_mm)

    def steps_to_mm(self, steps: int) -> float:
        return steps / self.steps_per_mm

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "step_count": self._step_count,
            "position_mm": self.get_position_mm(),
            "current_speed_mm_s": self._current_speed_mm_s,
            "direction": self._direction,
        }

    def __repr__(self) -> str:
        return (
            f"StepperMotor({self.name!r}, pos={self.get_position_mm():.2f}mm, "
            f"steps={self._step_count})"
        )
