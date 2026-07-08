from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any


def create_rustypot_controller(
    controller_class: str,
    serial_port: str,
    baudrate: int,
    timeout: float,
):
    module = import_module("rustypot")
    controller_type = getattr(module, controller_class)
    return controller_type(serial_port=serial_port, baudrate=baudrate, timeout=timeout)


@dataclass(slots=True)
class LazyRustypotController:
    controller_class: str
    serial_port: str
    baudrate: int
    timeout: float
    _controller: Any = field(default=None, init=False, repr=False)

    def _get_controller(self):
        if self._controller is None:
            self._controller = create_rustypot_controller(
                controller_class=self.controller_class,
                serial_port=self.serial_port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
        return self._controller

    def ping(self, motor_id: int):
        return self._get_controller().ping(motor_id)

    def write_torque_enable(self, motor_id: int, value: bool | int):
        return self._get_controller().write_torque_enable(motor_id, value)

    def write_operating_mode(self, motor_id: int, value: int):
        return self._get_controller().write_operating_mode(motor_id, value)

    def write_goal_position(self, motor_id: int, angle_radians: float):
        return self._get_controller().write_goal_position(motor_id, angle_radians)

    def write_raw_goal_position(self, motor_id: int, value: int):
        return self._get_controller().write_raw_goal_position(motor_id, value)

    def read_present_position(self, motor_id: int) -> float:
        return self._get_controller().read_present_position(motor_id)

    def read_raw_present_position(self, motor_id: int) -> float:
        return self._get_controller().read_raw_present_position(motor_id)


def create_lazy_rustypot_controller(
    controller_class: str,
    serial_port: str,
    baudrate: int,
    timeout: float,
) -> LazyRustypotController:
    return LazyRustypotController(
        controller_class=controller_class,
        serial_port=serial_port,
        baudrate=baudrate,
        timeout=timeout,
    )
