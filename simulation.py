"""Учебная тепловая модель. Не зависит от Pygame и реального времени."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Controller = Callable[[float, float, float, dict], float]
MODES = ("manual", "relay", "p", "pid", "student")
FIXED_DT = 0.05
CONTROL_DT = 0.25
SAMPLE_DT = 0.5
REACTION_LOW = 90.0
REACTION_HIGH = 110.0


@dataclass
class Parameters:
    ambient: float = 20.0                  # °C
    target: float = 100.0                  # °C
    supply_kw: float = 18.0                # максимальная мощность источника
    reactor_capacity: float = 42_000.0     # Дж/°C
    heater_capacity: float = 9_000.0       # Дж/°C; запас тепла в нагревателе
    coupling: float = 180.0                # Вт/°C, нагреватель -> бочка
    reactor_loss: float = 32.0             # Вт/°C, бочка -> среда
    heater_loss: float = 8.0               # Вт/°C, нагреватель -> среда
    sensor_tau: float = 2.0                # с, инерция датчика
    initial_mass: float = 100.0            # кг этилена, условная загрузка
    max_rate: float = 0.08                 # кг/с при 100 °C
    kp: float = 0.05                       # доля мощности / °C
    ki: float = 0.0001                     # доля мощности / (°C * с)
    kd: float = 1.2                        # доля мощности * с / °C


@dataclass(frozen=True)
class Sample:
    time: float
    temperature: float
    heater_temperature: float
    sensor_temperature: float
    rate: float
    polymer_mass: float
    duty: float
    power_kw: float
    target: float
    cooling: bool
    mode: str


def temperature_factor(temperature: float) -> float:
    """Максимум при 100 °C; синтез разрешён от 90 до 110 °C включительно."""
    if not REACTION_LOW <= temperature <= REACTION_HIGH:
        return 0.0
    return math.exp(-0.5 * ((temperature - 100.0) / 5.0) ** 2)


def load_student_controller(path: Path) -> Controller:
    """Читаем исходник заново: F5 работает даже при быстрых сохранениях файла."""
    namespace = {"__file__": str(path), "__name__": "student_controller"}
    exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), namespace)
    controller = namespace.get("regulator")
    if not callable(controller):
        raise ValueError("В controller.py нужна функция regulator(temperature, dt, target, state)")
    return controller


class Simulation:
    def __init__(self, parameters: Parameters | None = None,
                 student_controller: Controller | None = None):
        self.parameters = parameters or Parameters()
        self.student_controller = student_controller
        self.mode = "relay"
        self.manual_duty = 0.45
        self.cooling = False
        self.reset()

    def reset(self) -> None:
        """Новая загрузка; настройки и выбранный режим сохраняются."""
        self.time = 0.0
        self.temperature = self.parameters.ambient
        self.heater_temperature = self.parameters.ambient
        self.sensor_temperature = self.parameters.ambient
        self.polymer_mass = 0.0
        self.duty = 0.0
        self.peak_temperature = self.parameters.ambient
        self.time_in_band = 0.0
        self.cooling = False
        self.control_state: dict = {}
        self.controller_error = ""
        self._control_steps = 0
        self._sample_steps = 0
        self._steps = 0
        self._accumulator = 0.0
        self.history: list[Sample] = []
        self.record()

    @property
    def remaining_mass(self) -> float:
        return max(0.0, self.parameters.initial_mass - self.polymer_mass)

    @property
    def rate(self) -> float:
        if self.remaining_mass <= 1e-10:
            return 0.0
        return self.parameters.max_rate * temperature_factor(self.temperature)

    @property
    def overshoot(self) -> float:
        return max(0.0, self.peak_temperature - self.parameters.target)

    @property
    def power_kw(self) -> float:
        return self.duty * self.parameters.supply_kw

    def clear_controller(self) -> None:
        self.control_state.clear()
        self.controller_error = ""
        self.duty = 0.0
        self._control_steps = 0

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Неизвестный режим: {mode}")
        self.mode = mode
        self.clear_controller()

    def reload_controller(self, path: Path) -> None:
        # При ошибке загрузки прежняя функция остаётся на месте.
        controller = load_student_controller(path)
        self.student_controller = controller
        self.clear_controller()

    def control(self) -> None:
        if self.controller_error:
            self.duty = 0.0
            return
        p = self.parameters
        error = p.target - self.sensor_temperature
        try:
            if self.mode == "manual":
                output = self.manual_duty
            elif self.mode == "relay":
                if self.sensor_temperature <= REACTION_LOW:
                    output = 1.0
                elif self.sensor_temperature >= REACTION_HIGH:
                    output = 0.0
                else:
                    output = self.duty
            elif self.mode == "p":
                output = p.kp * error
            elif self.mode == "pid":
                previous = self.control_state.get("previous", self.sensor_temperature)
                derivative = -(self.sensor_temperature - previous) / CONTROL_DT
                self.control_state["previous"] = self.sensor_temperature
                integral = self.control_state.get("integral", 0.0)
                candidate = integral + error * CONTROL_DT
                raw = p.kp * error + p.ki * candidate + p.kd * derivative
                # Условное интегрирование: не накапливаем ошибку при насыщении,
                # если она ещё сильнее уводит выход за физические пределы.
                if 0.0 <= raw <= 1.0 or (raw > 1.0 and error < 0.0) or (raw < 0.0 and error > 0.0):
                    integral = candidate
                self.control_state["integral"] = integral
                output = p.kp * error + p.ki * integral + p.kd * derivative
            else:
                if self.student_controller is None:
                    raise RuntimeError("Функция regulator не загружена. Нажмите F5.")
                output = self.student_controller(
                    self.sensor_temperature, CONTROL_DT, p.target, self.control_state
                )
            output = float(output)
            if not math.isfinite(output):
                raise ValueError("regulator вернул NaN или бесконечность")
            self.duty = max(0.0, min(1.0, output))
        except Exception as exc:
            self.controller_error = f"{type(exc).__name__}: {exc}"
            self.duty = 0.0

    def step(self) -> None:
        """Один шаг 0.05 с; регулятор вызывается каждые 0.25 с модели."""
        if self._control_steps == 0:
            self.control()
        self._control_steps = (self._control_steps + 1) % round(CONTROL_DT / FIXED_DT)
        p = self.parameters
        exchange = p.coupling * (self.heater_temperature - self.temperature)
        loss = p.reactor_loss * (3.0 if self.cooling else 1.0)
        reactor_flow = exchange - loss * (self.temperature - p.ambient)
        heater_flow = self.power_kw * 1000.0 - exchange - p.heater_loss * (self.heater_temperature - p.ambient)
        # Обе производные считаются из одного состояния: передача тепла
        # между узлами сохраняет энергию.
        self.temperature += FIXED_DT * reactor_flow / p.reactor_capacity
        self.heater_temperature += FIXED_DT * heater_flow / p.heater_capacity
        sensor_alpha = -math.expm1(-FIXED_DT / p.sensor_tau) if p.sensor_tau > 0.0 else 1.0
        self.sensor_temperature += sensor_alpha * (self.temperature - self.sensor_temperature)
        self.polymer_mass = min(p.initial_mass, self.polymer_mass + self.rate * FIXED_DT)
        self.peak_temperature = max(self.peak_temperature, self.temperature)
        if REACTION_LOW <= self.temperature <= REACTION_HIGH:
            self.time_in_band += FIXED_DT
        self._steps += 1
        self.time = self._steps * FIXED_DT
        self._sample_steps += 1
        if self._sample_steps >= round(SAMPLE_DT / FIXED_DT):
            self._sample_steps = 0
            self.record()

    def advance(self, seconds: float) -> None:
        """Кадры любой длины дают одинаковую последовательность шагов модели."""
        if not math.isfinite(seconds) or seconds < 0.0:
            raise ValueError("Время должно быть конечным и неотрицательным")
        self._accumulator += seconds
        count = int((self._accumulator + 1e-10) / FIXED_DT)
        for _ in range(count):
            self.step()
        self._accumulator = max(0.0, self._accumulator - count * FIXED_DT)

    def snapshot(self) -> Sample:
        return Sample(self.time, self.temperature, self.heater_temperature,
                      self.sensor_temperature, self.rate, self.polymer_mass,
                      self.duty, self.power_kw, self.parameters.target,
                      self.cooling, self.mode)

    def record(self) -> None:
        self.history.append(self.snapshot())

    def export_csv(self, path: Path) -> None:
        """Полный опыт, а не только видимое окно графика. Единицы — в заголовке."""
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.history if self.history[-1].time == self.time else [*self.history, self.snapshot()]
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(("time_s", "reactor_C", "heater_C", "sensor_C", "rate_kg_s",
                             "polymer_kg", "duty_0_1", "power_kW", "target_C", "cooling", "mode"))
            for row in rows:
                writer.writerow((f"{row.time:.2f}", f"{row.temperature:.5f}",
                                 f"{row.heater_temperature:.5f}", f"{row.sensor_temperature:.5f}",
                                 f"{row.rate:.6f}", f"{row.polymer_mass:.6f}",
                                 f"{row.duty:.5f}", f"{row.power_kw:.5f}",
                                 row.target, int(row.cooling), row.mode))
