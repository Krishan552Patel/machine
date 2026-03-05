# ---------------------------------------------------------------------------
# gantry.py  —  CoreXY kinematics + coordinated gantry movement
# ---------------------------------------------------------------------------
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from motor import StepperMotor, TrapezoidalProfile, ProfileResult
import config

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MoveRecord:
    """Log entry produced by every gantry move."""
    move_type: str                          # "XY", "Z_DOWN", "Z_UP", "HOME"
    start_pos: tuple[float, float, float]   # (x, y, z) mm at move start
    end_pos: tuple[float, float, float]     # (x, y, z) mm at move end
    feedrate_mm_s: float
    distance_mm: float
    duration_s: float                       # simulated duration
    timestamp_s: float                      # sim clock at move start


# ---------------------------------------------------------------------------
# CoreXY kinematics  (stateless — all methods are static)
# ---------------------------------------------------------------------------

class CoreXYKinematics:
    """
    CoreXY belt geometry:
        motor_a drives both belts in the same direction  ->  Y movement
        motor_b drives both belts in opposite directions ->  X movement

    Standard CoreXY transform:
        delta_a = dx + dy
        delta_b = dx - dy

    Inverse:
        dx = (delta_a + delta_b) / 2
        dy = (delta_a - delta_b) / 2
    """

    @staticmethod
    def xy_to_motors(dx: float, dy: float) -> tuple[float, float]:
        """Convert an XY displacement (mm) to motor A and B displacements (mm)."""
        delta_a = dx + dy
        delta_b = dx - dy
        return delta_a, delta_b

    @staticmethod
    def motors_to_xy(delta_a: float, delta_b: float) -> tuple[float, float]:
        """Convert motor A/B displacements (mm) back to XY displacement (mm)."""
        dx = (delta_a + delta_b) / 2.0
        dy = (delta_a - delta_b) / 2.0
        return dx, dy


# ---------------------------------------------------------------------------
# Gantry  (owns all three motors + kinematics)
# ---------------------------------------------------------------------------

class Gantry:
    """
    High-level gantry controller.

    Tracks logical (X, Y, Z) position and translates move_xy / move_z
    commands into stepper steps via CoreXY kinematics and a trapezoidal
    velocity profile.
    """

    def __init__(
        self,
        motor_a: StepperMotor,
        motor_b: StepperMotor,
        motor_z: StepperMotor,
        kinematics: CoreXYKinematics | None = None,
    ) -> None:
        self.motor_a = motor_a
        self.motor_b = motor_b
        self.motor_z = motor_z
        self.kin = kinematics or CoreXYKinematics()

        # Logical position in mm
        self._x: float = 0.0
        self._y: float = 0.0
        self._z: float = 0.0

        # Simulation clock (accumulated simulated seconds)
        self._sim_time: float = 0.0

        # Full history of all moves
        self._move_history: list[MoveRecord] = []

    # ------------------------------------------------------------------
    # High-level commands
    # ------------------------------------------------------------------

    def home(self) -> MoveRecord:
        """Reset all axes to the origin."""
        start = self._pos()
        self.motor_a.reset()
        self.motor_b.reset()
        self.motor_z.reset()
        self._x = 0.0
        self._y = 0.0
        self._z = 0.0
        rec = MoveRecord(
            move_type="HOME",
            start_pos=start,
            end_pos=self._pos(),
            feedrate_mm_s=0.0,
            distance_mm=0.0,
            duration_s=0.0,
            timestamp_s=self._sim_time,
        )
        self._move_history.append(rec)
        self._print_move(rec)
        return rec

    def move_xy(
        self,
        target_x: float,
        target_y: float,
        feedrate: float | None = None,
    ) -> MoveRecord:
        """
        Move the head to (target_x, target_y) in machine mm.
        Both A and B motors step simultaneously (CoreXY).
        """
        feedrate = feedrate or config.MAX_FEEDRATE_MM_S
        feedrate = min(feedrate, config.MAX_FEEDRATE_MM_S)

        dx = target_x - self._x
        dy = target_y - self._y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        start = self._pos()
        timestamp = self._sim_time

        if distance < 1e-6:
            rec = MoveRecord("XY", start, start, feedrate, 0.0, 0.0, timestamp)
            self._move_history.append(rec)
            return rec

        profile = TrapezoidalProfile.compute(distance, feedrate, config.ACCELERATION_MM_S2)
        self._interpolate_xy(dx, dy, distance, profile)

        self._x = target_x
        self._y = target_y
        duration = profile.total_time_s
        self._advance_time(duration)

        rec = MoveRecord(
            move_type="XY",
            start_pos=start,
            end_pos=self._pos(),
            feedrate_mm_s=feedrate,
            distance_mm=distance,
            duration_s=duration,
            timestamp_s=timestamp,
        )
        self._move_history.append(rec)
        return rec

    def move_z(
        self,
        target_z: float,
        speed: float | None = None,
    ) -> MoveRecord:
        """Move Z axis to target_z (mm). Positive = down toward cards."""
        speed = speed or config.Z_SPEED_MM_S
        dz = target_z - self._z
        distance = abs(dz)
        direction = 1 if dz >= 0 else -1

        start = self._pos()
        timestamp = self._sim_time

        if distance < 1e-6:
            rec = MoveRecord("Z", start, start, speed, 0.0, 0.0, timestamp)
            self._move_history.append(rec)
            return rec

        profile = TrapezoidalProfile.compute(distance, speed, config.Z_ACCELERATION_MM_S2)
        self._interpolate_z(direction, distance, profile)

        self._z = target_z
        duration = profile.total_time_s
        self._advance_time(duration)

        move_type = "Z_DOWN" if direction > 0 else "Z_UP"
        rec = MoveRecord(
            move_type=move_type,
            start_pos=start,
            end_pos=self._pos(),
            feedrate_mm_s=speed,
            distance_mm=distance,
            duration_s=duration,
            timestamp_s=timestamp,
        )
        self._move_history.append(rec)
        return rec

    # ------------------------------------------------------------------
    # Interpolation (steps motors along the profile)
    # ------------------------------------------------------------------

    def _interpolate_xy(
        self,
        dx: float,
        dy: float,
        distance: float,
        profile: ProfileResult,
    ) -> None:
        """Step motors A and B in sync along the CoreXY kinematic path."""
        delta_a, delta_b = self.kin.xy_to_motors(dx, dy)

        # Ratio of each motor's total travel to XY distance
        ratio_a = delta_a / distance if distance > 0 else 0.0
        ratio_b = delta_b / distance if distance > 0 else 0.0

        dir_a = 1 if delta_a >= 0 else -1
        dir_b = 1 if delta_b >= 0 else -1

        step = config.INTERPOLATION_STEP_MM
        traveled = 0.0
        steps_issued_a = 0
        steps_issued_b = 0

        while traveled < distance:
            chunk = min(step, distance - traveled)
            traveled += chunk

            speed = TrapezoidalProfile.speed_at_distance(profile, traveled)
            self.motor_a.set_speed(speed * abs(ratio_a))
            self.motor_b.set_speed(speed * abs(ratio_b))

            new_steps_a = self.motor_a.mm_to_steps(abs(delta_a) * (traveled / distance))
            new_steps_b = self.motor_b.mm_to_steps(abs(delta_b) * (traveled / distance))

            steps_a_now = new_steps_a - steps_issued_a
            steps_b_now = new_steps_b - steps_issued_b

            if steps_a_now > 0:
                self.motor_a.step(dir_a, steps_a_now)
                steps_issued_a += steps_a_now
            if steps_b_now > 0:
                self.motor_b.step(dir_b, steps_b_now)
                steps_issued_b += steps_b_now

        # Flush any remaining fractional steps
        total_a = self.motor_a.mm_to_steps(abs(delta_a))
        total_b = self.motor_b.mm_to_steps(abs(delta_b))
        if total_a > steps_issued_a:
            self.motor_a.step(dir_a, total_a - steps_issued_a)
        if total_b > steps_issued_b:
            self.motor_b.step(dir_b, total_b - steps_issued_b)

        self.motor_a.set_speed(0.0)
        self.motor_b.set_speed(0.0)

    def _interpolate_z(
        self,
        direction: int,
        distance: float,
        profile: ProfileResult,
    ) -> None:
        """Step Z motor along its profile."""
        step = config.INTERPOLATION_STEP_MM
        traveled = 0.0
        steps_issued = 0

        while traveled < distance:
            chunk = min(step, distance - traveled)
            traveled += chunk

            speed = TrapezoidalProfile.speed_at_distance(profile, traveled)
            self.motor_z.set_speed(speed)

            new_steps = self.motor_z.mm_to_steps(traveled)
            steps_now = new_steps - steps_issued
            if steps_now > 0:
                self.motor_z.step(direction, steps_now)
                steps_issued += steps_now

        total = self.motor_z.mm_to_steps(distance)
        if total > steps_issued:
            self.motor_z.step(direction, total - steps_issued)

        self.motor_z.set_speed(0.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pos(self) -> tuple[float, float, float]:
        return (self._x, self._y, self._z)

    def _advance_time(self, duration_s: float) -> None:
        self._sim_time += duration_s
        if config.SIMULATION_TIME_SCALE > 0:
            time.sleep(duration_s * config.SIMULATION_TIME_SCALE)

    def _print_move(self, rec: MoveRecord) -> None:
        if rec.move_type == "HOME":
            print(f"[t={self._sim_time:>7.3f}s] HOME  -> (0.0, 0.0, 0.0)mm")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_position(self) -> tuple[float, float, float]:
        return self._pos()

    def get_simulated_time(self) -> float:
        return self._sim_time

    def get_move_history(self) -> list[MoveRecord]:
        return list(self._move_history)

    def get_total_distance(self) -> float:
        return sum(r.distance_mm for r in self._move_history)

    def get_motor_states(self) -> dict:
        return {
            "A": self.motor_a.get_state(),
            "B": self.motor_b.get_state(),
            "Z": self.motor_z.get_state(),
        }

    def __repr__(self) -> str:
        x, y, z = self._pos()
        return f"Gantry(x={x:.1f}, y={y:.1f}, z={z:.1f}, t={self._sim_time:.3f}s)"
