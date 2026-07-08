from __future__ import annotations

import argparse
import json
import errno
import sys
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omx_control import OMXArm, create_lazy_rustypot_controller, load_joint_specs  # noqa: E402


FALLBACK_SERIAL_PORT = "/dev/cu.usbmodem11401"
DEFAULT_BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
DEFAULT_PLAYBACK_DELAY_SECONDS = 0.35
DEFAULT_PLAYBACK_STEP_DEGREES = 4.0
DEFAULT_PLAYBACK_STEP_SECONDS = 0.04
XL430_CONTROLLER_CLASS = "Xl430PyController"
XL330_CONTROLLER_CLASS = "Xl330PyController"
DEFAULT_CONTROLLER_CLASS_BY_JOINT = {
    "base": XL430_CONTROLLER_CLASS,
    "joint1": XL430_CONTROLLER_CLASS,
    "joint2": XL430_CONTROLLER_CLASS,
    "joint3": XL330_CONTROLLER_CLASS,
    "joint4": XL330_CONTROLLER_CLASS,
    "gripper": XL330_CONTROLLER_CLASS,
}


def available_serial_ports() -> list[str]:
    patterns = ("/dev/cu.usb*", "/dev/tty.usb*", "/dev/ttyUSB*", "/dev/ttyACM*")
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(str(path) for path in Path("/").glob(pattern.removeprefix("/")))
    return sorted(set(ports))


def default_serial_port() -> str:
    candidates = available_serial_ports()
    for candidate in candidates:
        if candidate.startswith("/dev/cu."):
            return candidate
    return candidates[0] if candidates else FALLBACK_SERIAL_PORT


@dataclass(slots=True)
class TeachPoint:
    label: str
    positions: dict[str, float]
    created_at: float


@dataclass(slots=True)
class RobotRuntime:
    arm: OMXArm
    serial_port: str
    baudrate: int
    timeout: float
    controller_class_by_joint: dict[str, str]
    teaching: bool = False
    playing: bool = False
    playback_loop: bool = False
    sequence: list[TeachPoint] = field(default_factory=list)
    stop_playback_event: threading.Event = field(default_factory=threading.Event)
    playback_thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def prepare_controller_for_joint(self, joint_name: str) -> None:
        active_controller = self.arm.controller_for_joint(joint_name)
        seen: set[int] = set()
        for controller in self.arm.controllers_by_joint_name.values():
            controller_id = id(controller)
            if controller_id in seen or controller is active_controller:
                continue
            seen.add(controller_id)
            close = getattr(controller, "close", None)
            if callable(close):
                close()

    def joint_payload(self) -> list[dict[str, Any]]:
        joints = []
        for joint in self.arm.joints.values():
            joints.append(
                {
                    "name": joint.name,
                    "motorId": joint.motor_id,
                    "minDegrees": joint.angle_range.start_degrees,
                    "maxDegrees": joint.angle_range.end_degrees,
                    "homeDegrees": joint.home_degrees,
                    "namedPositions": dict(joint.named_positions),
                    "controllerClass": self.controller_class_by_joint[joint.name],
                }
            )
        return joints

    def sequence_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "label": point.label,
                "positions": dict(point.positions),
                "created_at": point.created_at,
            }
            for point in self.sequence
        ]

    def clamp_joint_angle(self, joint_name: str, angle: float) -> float:
        joint = self.arm.joint(joint_name)
        minimum = min(joint.angle_range.start_degrees, joint.angle_range.end_degrees)
        maximum = max(joint.angle_range.start_degrees, joint.angle_range.end_degrees)
        return max(minimum, min(maximum, angle))

    def clamp_positions(self, positions: dict[str, float]) -> dict[str, float]:
        clamped: dict[str, float] = {}
        for joint_name, angle in positions.items():
            if joint_name not in self.arm.joints:
                continue
            clamped[joint_name] = self.clamp_joint_angle(joint_name, float(angle))
        return clamped

    def read_positions(self) -> dict[str, float | None]:
        positions: dict[str, float | None] = {}
        for joint_name in self.arm.joints:
            try:
                self.prepare_controller_for_joint(joint_name)
                positions[joint_name] = round(self.arm.read_joint_position(joint_name), 2)
            except Exception:
                positions[joint_name] = None
        return positions

    def configure_for_motion(self, joint_name: str) -> None:
        self.prepare_controller_for_joint(joint_name)
        self.arm.configure_joint_position_mode(joint_name)
        self.arm.set_joint_torque(joint_name, True)

    def release_all(self) -> None:
        for joint_name in self.arm.joints:
            self.prepare_controller_for_joint(joint_name)
            self.arm.set_joint_torque(joint_name, False)

    def enable_all(self) -> None:
        for joint_name in self.arm.joints:
            self.configure_for_motion(joint_name)

    def move_joint_positions(self, positions: dict[str, float]) -> None:
        clamped_positions = self.clamp_positions(positions)
        for joint_name, angle in clamped_positions.items():
            self.prepare_controller_for_joint(joint_name)
            self.arm.move_joint(joint_name, angle)

    def move_to_positions_smooth(
        self,
        start_positions: dict[str, float],
        target_positions: dict[str, float],
        *,
        max_step_degrees: float,
        step_seconds: float,
        stop_event: threading.Event | None = None,
    ) -> dict[str, float]:
        if max_step_degrees <= 0.0:
            raise ValueError("maxStepDegrees must be greater than 0")
        if step_seconds < 0.0:
            raise ValueError("stepSeconds cannot be negative")

        moving_joints = {
            joint_name: target
            for joint_name, target in target_positions.items()
            if joint_name in start_positions
        }
        if not moving_joints:
            return start_positions

        max_delta = max(abs(target - start_positions[joint_name]) for joint_name, target in moving_joints.items())
        step_count = max(1, int(max_delta / max_step_degrees) + 1)

        for step_index in range(1, step_count + 1):
            progress = step_index / step_count
            eased_progress = progress * progress * (3.0 - 2.0 * progress)
            next_positions = {
                joint_name: start_positions[joint_name] + (target - start_positions[joint_name]) * eased_progress
                for joint_name, target in moving_joints.items()
            }
            self.move_joint_positions(next_positions)
            if step_seconds > 0.0 and step_index < step_count:
                if stop_event is None:
                    time.sleep(step_seconds)
                elif stop_event.wait(step_seconds):
                    return {**start_positions, **next_positions}

        return {**start_positions, **target_positions}

    def start_playback(
        self,
        *,
        delay_seconds: float,
        max_step_degrees: float,
        step_seconds: float,
        loop: bool,
    ) -> None:
        if not self.sequence:
            raise ValueError("No taught positions to play")
        if self.playing:
            raise ValueError("Playback is already running")
        if delay_seconds < 0.0:
            raise ValueError("delaySeconds cannot be negative")
        if max_step_degrees <= 0.0:
            raise ValueError("maxStepDegrees must be greater than 0")
        if step_seconds < 0.0:
            raise ValueError("stepSeconds cannot be negative")

        sequence_snapshot = [
            TeachPoint(
                label=point.label,
                positions=self.clamp_positions(point.positions),
                created_at=point.created_at,
            )
            for point in self.sequence
        ]
        self.teaching = False
        self.playing = True
        self.playback_loop = loop
        self.stop_playback_event.clear()

        worker = threading.Thread(
            target=self._run_playback,
            args=(sequence_snapshot, delay_seconds, max_step_degrees, step_seconds, loop),
            daemon=True,
            name="omx-playback",
        )
        self.playback_thread = worker
        worker.start()

    def _run_playback(
        self,
        sequence_snapshot: list[TeachPoint],
        delay_seconds: float,
        max_step_degrees: float,
        step_seconds: float,
        loop: bool,
    ) -> None:
        try:
            with self.lock:
                self.enable_all()
                current_positions = {
                    name: value
                    for name, value in self.read_positions().items()
                    if value is not None
                }

            while not self.stop_playback_event.is_set():
                for point in sequence_snapshot:
                    if self.stop_playback_event.is_set():
                        break
                    with self.lock:
                        current_positions = self.move_to_positions_smooth(
                            current_positions,
                            point.positions,
                            max_step_degrees=max_step_degrees,
                            step_seconds=step_seconds,
                            stop_event=self.stop_playback_event,
                        )
                    if self.stop_playback_event.is_set():
                        break
                    if delay_seconds > 0.0 and self.stop_playback_event.wait(delay_seconds):
                        break
                if not loop:
                    break
        finally:
            with self.lock:
                self.playing = False
                self.playback_loop = False
                self.playback_thread = None
                self.stop_playback_event.clear()

    def stop_playback(self) -> bool:
        was_playing = self.playing
        self.playing = False
        self.playback_loop = False
        self.stop_playback_event.set()
        return was_playing

    def close(self) -> None:
        self.stop_playback()
        playback_thread = self.playback_thread
        if (
            playback_thread is not None
            and playback_thread.is_alive()
            and playback_thread is not threading.current_thread()
        ):
            playback_thread.join(timeout=1.0)

        seen: set[int] = set()
        for controller in self.arm.controllers_by_joint_name.values():
            controller_id = id(controller)
            if controller_id in seen:
                continue
            seen.add(controller_id)
            close = getattr(controller, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass


def build_runtime(args: argparse.Namespace) -> RobotRuntime:
    serial_path = Path(args.serial_port)
    if not serial_path.exists():
        candidates = available_serial_ports()
        candidate_text = ", ".join(candidates) if candidates else "none found"
        raise FileNotFoundError(
            f"Serial port {args.serial_port!r} does not exist. "
            f"Set OMX_SERIAL_PORT or pass --serial-port. Available USB-like ports: {candidate_text}"
        )

    joints = load_joint_specs(args.joint_config)
    joint_names = {joint.name for joint in joints}
    controller_class_by_joint = {
        joint_name: controller_class
        for joint_name, controller_class in DEFAULT_CONTROLLER_CLASS_BY_JOINT.items()
        if joint_name in joint_names
    }
    missing = sorted(joint_names - set(controller_class_by_joint))
    if missing:
        raise ValueError(f"No controller class configured for joint(s): {', '.join(missing)}")

    controllers_by_class = {
        controller_class: create_lazy_rustypot_controller(
            controller_class=controller_class,
            serial_port=args.serial_port,
            baudrate=args.baudrate,
            timeout=args.timeout,
        )
        for controller_class in sorted(set(controller_class_by_joint.values()))
    }
    controllers_by_joint = {
        joint_name: controllers_by_class[controller_class]
        for joint_name, controller_class in controller_class_by_joint.items()
    }
    arm = OMXArm.with_default_joint_controllers(controllers_by_joint, joints=joints)
    return RobotRuntime(
        arm=arm,
        serial_port=args.serial_port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        controller_class_by_joint=controller_class_by_joint,
    )


class RobotRequestHandler(BaseHTTPRequestHandler):
    runtime: RobotRuntime

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        return json.loads(body.decode("utf-8"))

    def _ok(self, payload: dict[str, Any] | None = None) -> None:
        self._send_json(HTTPStatus.OK, {"ok": True, **(payload or {})})

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def do_OPTIONS(self) -> None:
        self._send_json(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                self._ok(
                    {
                        "serialPort": self.runtime.serial_port,
                        "baudrate": self.runtime.baudrate,
                        "timeout": self.runtime.timeout,
                        "joints": self.runtime.joint_payload(),
                    }
                )
                return

            if path == "/api/state":
                with self.runtime.lock:
                    self._ok(
                        {
                            "teaching": self.runtime.teaching,
                            "playing": self.runtime.playing,
                            "playbackLoop": self.runtime.playback_loop,
                            "positions": self.runtime.read_positions(),
                            "sequence": self.runtime.sequence_payload(),
                        }
                    )
                return

            self._error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {path}")
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            with self.runtime.lock:
                if path == "/api/manual/move":
                    joint_name = str(payload["joint"])
                    angle = float(payload["angle"])
                    joint = self.runtime.arm.joint(joint_name)
                    controller_class = self.runtime.controller_class_by_joint[joint_name]
                    print(
                        f"manual move: {joint_name} id={joint.motor_id} "
                        f"controller={controller_class} target={angle:.2f} deg"
                    )
                    self.runtime.configure_for_motion(joint_name)
                    self.runtime.arm.move_joint(joint_name, angle)
                    self._ok({"positions": self.runtime.read_positions()})
                    return

                if path == "/api/torque":
                    enabled = bool(payload["enabled"])
                    joint_name = payload.get("joint")
                    if joint_name:
                        self.runtime.arm.set_joint_torque(str(joint_name), enabled)
                    elif enabled:
                        self.runtime.enable_all()
                    else:
                        self.runtime.release_all()
                    self._ok({"positions": self.runtime.read_positions()})
                    return

                if path == "/api/teaching/enter":
                    self.runtime.release_all()
                    self.runtime.teaching = True
                    self._ok({"teaching": True, "positions": self.runtime.read_positions()})
                    return

                if path == "/api/teaching/exit":
                    self.runtime.teaching = False
                    self.runtime.enable_all()
                    self._ok({"teaching": False, "positions": self.runtime.read_positions()})
                    return

                if path == "/api/teaching/capture":
                    if not self.runtime.teaching:
                        raise ValueError("Enter teaching mode before capturing a position")
                    label = str(payload.get("label") or f"Point {len(self.runtime.sequence) + 1}")
                    positions = self.runtime.clamp_positions({
                        name: value
                        for name, value in self.runtime.read_positions().items()
                        if value is not None
                    })
                    self.runtime.sequence.append(TeachPoint(label=label, positions=positions, created_at=time.time()))
                    self._ok({"sequence": self.runtime.sequence_payload()})
                    return

                if path == "/api/teaching/clear":
                    self.runtime.sequence.clear()
                    self._ok({"sequence": []})
                    return

                if path == "/api/teaching/delete":
                    index = int(payload["index"])
                    if index < 0 or index >= len(self.runtime.sequence):
                        raise ValueError(f"Index out of range: {index}")
                    del self.runtime.sequence[index]
                    self._ok({"sequence": self.runtime.sequence_payload()})
                    return

                if path == "/api/teaching/play":
                    delay_seconds = float(payload.get("delaySeconds", DEFAULT_PLAYBACK_DELAY_SECONDS))
                    max_step_degrees = float(payload.get("maxStepDegrees", DEFAULT_PLAYBACK_STEP_DEGREES))
                    step_seconds = float(payload.get("stepSeconds", DEFAULT_PLAYBACK_STEP_SECONDS))
                    loop = bool(payload.get("loop", False))
                    self.runtime.start_playback(
                        delay_seconds=delay_seconds,
                        max_step_degrees=max_step_degrees,
                        step_seconds=step_seconds,
                        loop=loop,
                    )
                    self._ok({"playing": self.runtime.playing, "playbackLoop": self.runtime.playback_loop})
                    return

                if path == "/api/teaching/stop":
                    stopped = self.runtime.stop_playback()
                    self._ok({"stopped": stopped, "playing": self.runtime.playing, "playbackLoop": self.runtime.playback_loop})
                    return

            self._error(HTTPStatus.NOT_FOUND, f"Unknown endpoint: {path}")
        except KeyError as exc:
            self._error(HTTPStatus.BAD_REQUEST, f"Missing required field: {exc.args[0]}")
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--serial-port", default=default_serial_port())
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--joint-config", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = build_runtime(args)
    RobotRequestHandler.runtime = runtime
    server: ThreadingHTTPServer | None = None
    try:
        server = ThreadingHTTPServer((args.host, args.port), RobotRequestHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"Robot API port {args.host}:{args.port} is already in use.", file=sys.stderr)
            print("Stop the existing server or choose another port with --port / OMX_API_PORT.", file=sys.stderr)
            runtime.close()
            return 2
        raise
    print(f"Robot API listening on http://{args.host}:{args.port}")
    print("Use Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping robot API")
    finally:
        if server is not None:
            server.server_close()
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
