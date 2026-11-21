"""Интерфейс лабораторного стенда на Pygame."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Callable

import pygame

from simulation import MODES, Simulation


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1440, 960
BG = (12, 19, 31)
PANEL = (21, 31, 47)
RAISED = (30, 43, 62)
BORDER = (49, 65, 86)
TEXT = (236, 243, 251)
MUTED = (160, 177, 199)
TEAL = (111, 228, 198)
ORANGE = (255, 182, 107)
BLUE = (130, 184, 255)
RED = (255, 128, 143)
GRID = (37, 51, 70)
MODE_LABELS = ("Ручной", "Реле", "П", "ПИД", "Студент")
SPEEDS = (1, 4, 16, 64)


class Button:
    def __init__(self, rect, label: str, action: Callable, *, active=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action
        self.active = active or (lambda: False)

    def draw(self, app):
        selected = self.active()
        hovered = self.rect.collidepoint(app.mouse)
        fill = (38, 75, 73) if selected else RAISED if hovered else PANEL
        pygame.draw.rect(app.canvas, fill, self.rect, border_radius=9)
        pygame.draw.rect(app.canvas, TEAL if selected else BORDER, self.rect, 1, border_radius=9)
        app.text(self.label, self.rect.center, 16, TEAL if selected else TEXT, center=True)
        if app.focus is self:
            pygame.draw.rect(app.canvas, TEXT, self.rect.inflate(6, 6), 2, border_radius=11)


class Slider:
    def __init__(self, rect, label, getter, setter, low, high, step, formatter, *, enabled=None):
        self.rect = pygame.Rect(rect)
        self.label, self.getter, self.setter = label, getter, setter
        self.low, self.high, self.step, self.formatter = low, high, step, formatter
        self.enabled = enabled or (lambda: True)

    @property
    def track(self):
        return pygame.Rect(self.rect.x, self.rect.y + 32, self.rect.w, 6)

    def adjust(self, steps):
        if self.enabled():
            value = self.getter() + steps * self.step
            self.setter(round(max(self.low, min(self.high, value)), 7))

    def set_from_mouse(self, x):
        if self.enabled():
            fraction = max(0.0, min(1.0, (x - self.rect.x) / self.rect.w))
            value = self.low + fraction * (self.high - self.low)
            value = self.low + round((value - self.low) / self.step) * self.step
            self.setter(round(max(self.low, min(self.high, value)), 7))

    def draw(self, app):
        enabled = self.enabled()
        color = TEAL if enabled else MUTED
        app.text(self.label, (self.rect.x, self.rect.y), 16, TEXT if enabled else MUTED)
        app.text(self.formatter(self.getter()), (self.rect.right, self.rect.y), 16, color, right=True)
        pygame.draw.rect(app.canvas, BORDER, self.track, border_radius=3)
        fraction = (self.getter() - self.low) / (self.high - self.low)
        x = self.rect.x + int(fraction * self.rect.w)
        if x > self.rect.x:
            pygame.draw.rect(app.canvas, color, (self.rect.x, self.track.y, x - self.rect.x, 6), border_radius=3)
        pygame.draw.circle(app.canvas, color, (x, self.track.centery), 7)
        pygame.draw.circle(app.canvas, PANEL, (x, self.track.centery), 3)
        if app.focus is self:
            pygame.draw.rect(app.canvas, TEXT, self.rect.inflate(12, 8), 2, border_radius=8)


class LabApp:
    def __init__(self, size=None):
        pygame.init()
        pygame.display.set_caption("Полимерная лаборатория — инерция и регулирование")
        if size is None:
            desktop_width, desktop_height = pygame.display.get_desktop_sizes()[0]
            scale = min(1360 / WIDTH, (desktop_width - 64) / WIDTH, (desktop_height - 100) / HEIGHT)
            size = (max(720, round(WIDTH * scale)), max(480, round(HEIGHT * scale)))
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.fonts = {}
        self.sim = Simulation()
        self.paused = False
        self.running = True
        self.speed_index = 2
        self.window_seconds = 600
        self.help_visible = False
        self.toast = ""
        self.toast_until = 0
        self.focus = None
        self.dragging = None
        self.mouse = (-1, -1)
        self.widgets = []
        self.reload_student(initial=True)
        self.create_widgets()

    def text(self, value, position, size=18, color=TEXT, *, bold=False, center=False, right=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = pygame.font.SysFont(["segoeui", "dejavusans", "arial"], size, bold=bold)
        surface = self.fonts[key].render(str(value), True, color)
        rect = surface.get_rect()
        if center:
            rect.center = position
        elif right:
            rect.topright = position
        else:
            rect.topleft = position
        self.canvas.blit(surface, rect)
        return rect

    def fit_text(self, value, position, width, size=16, color=MUTED):
        """Сообщения из пользовательского кода не выходят за границы карточки."""
        value = str(value).replace("\n", " ")
        font = self.fonts.get((size, False))
        if font is None:
            self.text("", (0, 0), size)
            font = self.fonts[(size, False)]
        if font.size(value)[0] > width:
            while value and font.size(value + "…")[0] > width:
                value = value[:-1]
            value += "…"
        self.text(value, position, size, color)

    def panel(self, rect):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.canvas, PANEL, rect, border_radius=14)
        pygame.draw.rect(self.canvas, BORDER, rect, 1, border_radius=14)

    def notify(self, message):
        self.toast = message
        self.toast_until = pygame.time.get_ticks() + 6500

    def toggle_pause(self):
        self.paused = not self.paused

    def reset(self):
        self.sim.reset()
        self.notify("Новая загрузка. Температуры и статистика сброшены; настройки сохранены.")

    def change_speed(self, delta):
        self.speed_index = max(0, min(len(SPEEDS) - 1, self.speed_index + delta))

    def toggle_help(self):
        self.help_visible = not self.help_visible

    def toggle_cooling(self):
        self.sim.cooling = not self.sim.cooling

    def change_window(self):
        values = (120, 300, 600, 1200)
        self.window_seconds = values[(values.index(self.window_seconds) + 1) % len(values)]

    def reload_student(self, initial=False):
        try:
            self.sim.reload_controller(ROOT / "controller.py")
            if not initial:
                self.notify("controller.py перечитан; память регулятора очищена. Режим «Студент»: клавиша 5.")
        except Exception as exc:
            self.notify(f"Ошибка загрузки: {exc}")

    def export(self):
        path = ROOT / "exports" / f"experiment_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
        try:
            self.sim.export_csv(path)
            self.notify(f"Сохранён exports/{path.name}")
        except OSError as exc:
            self.notify(f"Не удалось сохранить CSV: {exc}")

    def create_widgets(self):
        def button(rect, label, action, **kwargs):
            widget = Button(rect, label, action, **kwargs)
            self.widgets.append(widget)
            return widget

        self.pause_button = button((24, 90, 128, 42), "Пауза", self.toggle_pause, active=lambda: self.paused)
        button((164, 90, 114, 42), "Сброс  R", self.reset)
        button((290, 90, 128, 42), "Экспорт  E", self.export)
        button((430, 90, 162, 42), "Код заново  F5", self.reload_student)
        button((604, 90, 130, 42), "Справка  F1", self.toggle_help)
        button((956, 90, 44, 42), "−", lambda: self.change_speed(-1))
        button((1100, 90, 44, 42), "+", lambda: self.change_speed(1))
        self.window_button = button((1160, 90, 256, 42), "Графики: 10 мин", self.change_window)
        for index, (mode, label) in enumerate(zip(MODES, MODE_LABELS)):
            button((44 + index * 69, 609, 63, 36), label,
                   lambda mode=mode: self.sim.set_mode(mode), active=lambda mode=mode: self.sim.mode == mode)

        def setting(rect, label, name, low, high, step, formatter, **kwargs):
            slider = Slider(rect, label, lambda: getattr(self.sim.parameters, name),
                            lambda value: setattr(self.sim.parameters, name, value),
                            low, high, step, formatter, **kwargs)
            self.widgets.append(slider)
            return slider

        setting((44, 675, 336, 44), "Источник мощности", "supply_kw", 4, 30, 0.5, lambda x: f"{x:.1f} кВт")
        self.widgets.append(Slider((44, 735, 336, 44), "Команда вручную", lambda: self.sim.manual_duty,
                                   lambda value: setattr(self.sim, "manual_duty", value),
                                   0, 1, 0.01, lambda x: f"{x:.0%}", enabled=lambda: self.sim.mode == "manual"))
        setting((44, 845, 300, 44), "Теплоёмкость нагревателя", "heater_capacity", 2000, 20000, 500,
                lambda x: f"{x / 1000:.1f} кДж/°C")
        button((372, 846, 214, 42), "Обдув  C: выключен", self.toggle_cooling, active=lambda: self.sim.cooling)
        self.cooling_button = self.widgets[-1]
        setting((626, 845, 228, 44), "Kp", "kp", 0, 0.12, 0.001, lambda x: f"{x:.3f}")
        setting((886, 845, 228, 44), "Ki", "ki", 0, 0.002, 0.00001, lambda x: f"{x:.5f}")
        setting((1146, 845, 248, 44), "Kd", "kd", 0, 8, 0.1, lambda x: f"{x:.1f}")

    def logical_position(self, position):
        width, height = self.screen.get_size()
        scale = min(width / WIDTH, height / HEIGHT)
        return ((position[0] - (width - WIDTH * scale) / 2) / scale,
                (position[1] - (height - HEIGHT * scale) / 2) / scale)

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode((max(960, event.w), max(640, event.h)), pygame.RESIZABLE)
        if event.type == pygame.MOUSEMOTION:
            self.mouse = self.logical_position(event.pos)
        if self.help_visible:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_F1):
                self.toggle_help()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if pygame.Rect(1120, 172, 80, 40).collidepoint(self.logical_position(event.pos)):
                    self.toggle_help()
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                index = self.widgets.index(self.focus) if self.focus in self.widgets else -1
                direction = -1 if event.mod & pygame.KMOD_SHIFT else 1
                self.focus = self.widgets[(index + direction) % len(self.widgets)]
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and isinstance(self.focus, Button):
                self.focus.action()
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT) and isinstance(self.focus, Slider):
                self.focus.adjust(-1 if event.key == pygame.K_LEFT else 1)
            elif event.key == pygame.K_SPACE:
                if isinstance(self.focus, Button):
                    self.focus.action()
                else:
                    self.toggle_pause()
            elif event.key == pygame.K_r:
                self.reset()
            elif event.key == pygame.K_e:
                self.export()
            elif event.key == pygame.K_c:
                self.toggle_cooling()
            elif event.key == pygame.K_F5:
                self.reload_student()
            elif event.key == pygame.K_F1:
                self.toggle_help()
            elif pygame.K_1 <= event.key <= pygame.K_5:
                self.sim.set_mode(MODES[event.key - pygame.K_1])
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self.change_speed(1)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.change_speed(-1)
            elif event.key in (pygame.K_UP, pygame.K_DOWN):
                self.sim.manual_duty = max(0.0, min(1.0, self.sim.manual_duty + (0.01 if event.key == pygame.K_UP else -0.01)))
            elif event.key == pygame.K_ESCAPE:
                self.running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.mouse = self.logical_position(event.pos)
            self.focus = None
            for widget in self.widgets:
                if widget.rect.collidepoint(self.mouse):
                    self.focus = widget
                    if isinstance(widget, Button):
                        widget.action()
                    elif widget.enabled():
                        self.dragging = widget
                        widget.set_from_mouse(self.mouse[0])
                    break
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = None
        elif event.type == pygame.MOUSEMOTION and self.dragging is not None:
            self.dragging.set_from_mouse(self.mouse[0])
        elif event.type == pygame.MOUSEWHEEL:
            for widget in self.widgets:
                if isinstance(widget, Slider) and widget.rect.collidepoint(self.mouse):
                    widget.adjust(event.y)
                    break

    def draw_header(self):
        self.text("ПОЛИМЕРНАЯ ЛАБОРАТОРИЯ", (24, 17), 30, bold=True)
        self.text("Этилен → полиэтилен  /  исследование тепловой инерции", (25, 57), 17, MUTED)
        status = "ПАУЗА" if self.paused or self.help_visible else "ЭКСПЕРИМЕНТ ИДЁТ"
        color = ORANGE if self.paused or self.help_visible else TEAL
        pygame.draw.circle(self.canvas, color, (1147, 33), 5)
        self.text(status, (1164, 21), 16, color)
        minutes, seconds = divmod(int(self.sim.time), 60)
        self.text(f"Модельное время  {minutes:02d}:{seconds:02d}", (1415, 53), 17, MUTED, right=True)
        self.text("Скорость", (852, 100), 17, MUTED)
        self.text(f"×{SPEEDS[self.speed_index]}", (1050, 111), 22, TEAL, bold=True, center=True)
        self.pause_button.label = "Продолжить" if self.paused else "Пауза"
        self.cooling_button.label = f"Обдув  C: {'включён' if self.sim.cooling else 'выключен'}"
        self.window_button.label = f"Окно графиков: {self.window_seconds // 60} мин"

    def draw_metrics(self):
        sim = self.sim
        metrics = (
            ("ТЕМПЕРАТУРА БОЧКИ", f"{sim.temperature:.1f}", "°C", TEAL, f"Датчик: {sim.sensor_temperature:.1f} °C"),
            ("ТЕМПЕРАТУРА НАГРЕВАТЕЛЯ", f"{sim.heater_temperature:.1f}", "°C", ORANGE, f"На входе: {sim.power_kw:.1f} кВт  /  {sim.duty:.0%}"),
            ("СКОРОСТЬ СИНТЕЗА", f"{sim.rate * 60:.2f}", "кг/мин", BLUE, f"Максимум: {sim.parameters.max_rate * 60:.2f} кг/мин"),
            ("ПЕРЕРЕГУЛИРОВАНИЕ", f"+{sim.overshoot:.1f}", "°C", RED if sim.overshoot > 0.5 else TEXT,
             f"Пик: {sim.peak_temperature:.1f} °C  /  цель: 100 °C"),
        )
        for index, (label, value, unit, color, detail) in enumerate(metrics):
            x = 24 + index * 352
            self.panel((x, 150, 336, 86))
            self.text(label, (x + 16, 161), 13, MUTED)
            number = self.text(value, (x + 16, 181), 30, color, bold=True)
            self.text(unit, (number.right + 9, 194), 16, MUTED)
            self.text(detail, (x + 16, 216), 12, MUTED)

    def draw_plant(self):
        self.panel((24, 252, 376, 292))
        self.text("01  /  ТЕПЛОВАЯ МОДЕЛЬ", (44, 269), 14, MUTED, bold=True)
        sim = self.sim
        barrel = pygame.Rect(62, 324, 154, 140)
        pygame.draw.rect(self.canvas, RAISED, barrel)
        pygame.draw.ellipse(self.canvas, RAISED, (62, 442, 154, 43))
        fraction = sim.polymer_mass / sim.parameters.initial_mass
        fill_height = round(134 * fraction)
        if fill_height > 0:
            pygame.draw.rect(self.canvas, (37, 83, 94), (64, 464 - fill_height, 150, fill_height))
            pygame.draw.ellipse(self.canvas, (43, 104, 111), (64, 453 - fill_height, 150, 23))
            pygame.draw.ellipse(self.canvas, (37, 83, 94), (64, 444, 150, 39))
        for yy in (341, 434):
            pygame.draw.arc(self.canvas, BORDER, (62, yy, 154, 33), math.pi, 2 * math.pi, 3)
        pygame.draw.line(self.canvas, MUTED, (62, 325), (62, 461), 2)
        pygame.draw.line(self.canvas, MUTED, (216, 325), (216, 461), 2)
        pygame.draw.arc(self.canvas, MUTED, (62, 442, 154, 43), math.pi, 2 * math.pi, 2)
        pygame.draw.ellipse(self.canvas, (42, 59, 80), (62, 303, 154, 43))
        pygame.draw.ellipse(self.canvas, MUTED, (62, 303, 154, 43), 2)
        self.text("C₂H₄", (139, 368), 27, TEXT, bold=True, center=True)
        self.text("→  (C₂H₄)n", (139, 403), 18, TEAL, center=True)
        # Нагреватель остаётся горячим при нулевой команде.
        heat = max(0.0, min(1.0, (sim.heater_temperature - 20) / 130))
        coil_color = tuple(round(BORDER[i] + heat * (ORANGE[i] - BORDER[i])) for i in range(3))
        coil = [(63 + i * 15, 498 + (-6 if i % 2 else 6)) for i in range(11)]
        pygame.draw.lines(self.canvas, coil_color, False, coil, 5)
        self.text("Нагреватель", (139, 515), 13, ORANGE, center=True)
        self.text("ЗАГРУЗКА", (240, 311), 12, MUTED)
        self.text("100 кг", (240, 332), 25, bold=True)
        self.text("ПОЛИЭТИЛЕН", (240, 378), 12, MUTED)
        self.text(f"{sim.polymer_mass:.2f} кг", (240, 400), 24, BLUE, bold=True)
        self.text(f"{fraction:.1%} загрузки", (240, 432), 14, MUTED)
        pygame.draw.rect(self.canvas, BORDER, (240, 465, 136, 6), border_radius=3)
        if fraction > 0:
            pygame.draw.rect(self.canvas, BLUE, (240, 465, max(2, int(136 * fraction)), 6), border_radius=3)
        status = "Сырьё израсходовано" if sim.remaining_mass <= 1e-10 else "Синтез идёт" if sim.rate > 0 else "Вне зоны синтеза"
        self.text(status, (240, 487), 13, BLUE if sim.rate > 0 else MUTED)

    def draw_controls(self):
        self.panel((24, 560, 376, 224))
        self.text("02  /  РЕГУЛЯТОР", (44, 576), 14, MUTED, bold=True)
        descriptions = {
            "manual": "Мощность задаётся нижним ползунком.",
            "relay": "100% ниже 100 °C; иначе 0%.",
            "p": "u = Kp × ошибка температуры.",
            "pid": "ПИД с защитой от накопления интеграла.",
            "student": "Ваш код: controller.py → regulator().",
        }
        self.fit_text(descriptions[self.sim.mode], (44, 652), 338, 13)
        self.panel((24, 800, 1392, 112))
        self.text("03  /  ОБЪЕКТ И ВОЗМУЩЕНИЯ", (44, 815), 14, MUTED, bold=True)
        self.text("КОЭФФИЦИЕНТЫ П / ПИД    ·    применяются сразу", (626, 815), 14, MUTED, bold=True)

    def dashed_line(self, color, start, end, dash=7):
        distance = math.dist(start, end)
        if distance == 0:
            return
        dx, dy = (end[0] - start[0]) / distance, (end[1] - start[1]) / distance
        for offset in range(0, int(distance), dash * 2):
            finish = min(offset + dash, distance)
            pygame.draw.line(self.canvas, color, (start[0] + dx * offset, start[1] + dy * offset),
                             (start[0] + dx * finish, start[1] + dy * finish), 1)

    def visible_history(self):
        start = max(0.0, self.sim.time - self.window_seconds)
        # Не перебираем многократно весь опыт при прокрутке длинной записи.
        first = max(0, int(start / 0.5) - 1)
        return self.sim.history[first:] + [self.sim.snapshot()]

    def draw_chart(self, rect, kind, history):
        self.panel(rect)
        x, y, width, height = rect
        is_temperature = kind == "temperature"
        self.text("ТЕМПЕРАТУРА, °C" if is_temperature else "СКОРОСТЬ СИНТЕЗА ПОЛИЭТИЛЕНА, кг/мин",
                  (x + 20, y + 15), 15, TEXT, bold=True)
        self.text("Время, мин", (x + width - 24, y + 15), 14, MUTED, right=True)
        plot = pygame.Rect(x + 64, y + 68, width - 90, height - 106)
        t_max = max(float(self.window_seconds), self.sim.time)
        t_min = t_max - self.window_seconds
        if is_temperature:
            maximum = max(120.0, max(max(s.temperature, s.heater_temperature) for s in history) * 1.10)
            v_max = math.ceil(maximum / 20) * 20
            legend = ((TEAL, "Бочка"), (ORANGE, "Нагреватель"), (MUTED, "Датчик"), (BLUE, "Цель 100 °C"))
        else:
            v_max = self.sim.parameters.max_rate * 60 * 1.15
            legend = ((BLUE, "Выход, кг/мин"), (TEAL, "Максимум при 100 °C"))
        legend_x = x + 22
        for color, label in legend:
            pygame.draw.line(self.canvas, color, (legend_x, y + 49), (legend_x + 19, y + 49), 2)
            label_rect = self.text(label, (legend_x + 26, y + 39), 14, color)
            legend_x = label_rect.right + 24

        def point(t, value):
            return (plot.x + (t - t_min) / self.window_seconds * plot.w,
                    plot.bottom - 1 - value / v_max * (plot.h - 1))

        if is_temperature:
            zone_top = point(0, 110)[1]
            zone_bottom = point(0, 90)[1]
            pygame.draw.rect(self.canvas, (24, 53, 55), (plot.x, zone_top, plot.w, zone_bottom - zone_top))
        for index in range(5):
            value = v_max * index / 4
            yy = point(0, value)[1]
            pygame.draw.line(self.canvas, GRID, (plot.left, yy), (plot.right, yy))
            label = f"{value:.0f}" if is_temperature else f"{value:.1f}"
            self.text(label, (plot.left - 10, yy - 9), 13, MUTED, right=True)
        for index in range(6):
            t = t_min + self.window_seconds * index / 5
            xx = point(t, 0)[0]
            pygame.draw.line(self.canvas, GRID, (xx, plot.top), (xx, plot.bottom))
            self.text(f"{t / 60:.1f}", (xx, plot.bottom + 17), 13, MUTED, center=True)
        previous_clip = self.canvas.get_clip()
        self.canvas.set_clip(plot)
        if is_temperature:
            self.text("90–110 °C", (plot.right - 100, point(0, 110)[1] + 3), 12, TEAL)
            for attribute, color, line_width in (("heater_temperature", ORANGE, 2),
                                                  ("sensor_temperature", MUTED, 1),
                                                  ("temperature", TEAL, 2)):
                points = [point(s.time, getattr(s, attribute)) for s in history]
                if len(points) >= 2:
                    pygame.draw.lines(self.canvas, color, False, points, line_width)
        else:
            points = [point(s.time, s.rate * 60) for s in history]
            if len(points) >= 2:
                pygame.draw.polygon(self.canvas, (27, 48, 74),
                                    [(points[0][0], plot.bottom), *points, (points[-1][0], plot.bottom)])
                pygame.draw.lines(self.canvas, BLUE, False, points, 2)
        self.dashed_line(BLUE if is_temperature else TEAL,
                         point(t_min, 100 if is_temperature else self.sim.parameters.max_rate * 60),
                         point(t_max, 100 if is_temperature else self.sim.parameters.max_rate * 60))
        self.canvas.set_clip(previous_clip)
        if plot.collidepoint(self.mouse) and not self.help_visible:
            desired_time = t_min + (self.mouse[0] - plot.x) / plot.w * self.window_seconds
            if history[0].time <= desired_time <= self.sim.time:
                sample = min(history, key=lambda s: abs(s.time - desired_time))
                xx = point(sample.time, 0)[0]
                self.dashed_line(MUTED, (xx, plot.top), (xx, plot.bottom), 4)
                detail = (f"{sample.time:.1f} с  ·  бочка {sample.temperature:.1f} °C  ·  нагреватель {sample.heater_temperature:.1f} °C"
                          if is_temperature else f"{sample.time:.1f} с  ·  {sample.rate * 60:.3f} кг/мин  ·  выход {sample.polymer_mass:.2f} кг")
                tooltip = pygame.Rect(plot.x + 8, plot.y + 5, min(650, plot.w - 16), 30)
                pygame.draw.rect(self.canvas, BG, tooltip, border_radius=6)
                self.text(detail, (tooltip.x + 8, tooltip.y + 4), 14, TEXT)

    def draw_footer(self):
        if self.sim.controller_error:
            self.fit_text(f"Код регулятора: {self.sim.controller_error}  |  Мощность 0%. Исправьте код и нажмите F5.",
                          (25, 928), 1390, 15, RED)
        elif self.toast and pygame.time.get_ticks() < self.toast_until:
            self.fit_text(self.toast, (25, 928), 1390, 15, TEAL)
        else:
            self.text("1–5: режим   ·   Пробел: пауза   ·   R: новый опыт   ·   F5: загрузить код   ·   Tab / стрелки: управление",
                      (25, 928), 14, MUTED)
            self.text("Учебная модель  /  F1", (1415, 928), 14, MUTED, right=True)

    def draw_help(self):
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 185))
        self.canvas.blit(shade, (0, 0))
        self.panel((220, 152, 1000, 650))
        self.text("КАК ПРОВЕСТИ ЭКСПЕРИМЕНТ", (252, 179), 26, bold=True)
        pygame.draw.rect(self.canvas, RAISED, (1120, 172, 80, 40), border_radius=8)
        self.text("Esc", (1160, 192), 17, center=True)
        lines = [
            ("Начните с реле", "Режим 2 → дождитесь 100 °C. Мощность уже нулевая, а температура ещё растёт."),
            ("Исследуйте инерцию", "Увеличьте теплоёмкость нагревателя, нажмите R и сравните пик температуры."),
            ("Сравните управление", "Режим 3: П-регулятор. Режим 4: ПИД. Меняйте Kp, Ki, Kd и начинайте новый опыт."),
            ("Проверьте возмущение", "Около 100 °C нажмите C: обдув увеличивает потери тепла бочки в три раза."),
            ("Напишите свой регулятор", "Откройте controller.py, измените regulator(temperature, dt, target, state)."),
            ("Примените код", "Сохраните файл, нажмите F5 и выберите режим 5. Выход функции: число от 0 до 1."),
        ]
        for index, (title, detail) in enumerate(lines):
            yy = 245 + index * 67
            self.text(f"0{index + 1}", (252, yy), 20, TEAL, bold=True)
            self.text(title, (297, yy), 19, TEXT, bold=True)
            self.text(detail, (297, yy + 27), 15, MUTED)
        self.text("В графиках: 90–110 °C — зона синтеза; пунктир — цель; наведите мышь для значений.",
                  (252, 662), 16, MUTED)
        self.text("E — полный опыт в CSV. + / − — скорость. Ползунки: мышь, колесо или Tab и ← / →.",
                  (252, 692), 16, MUTED)
        self.text("Модель условная: без давления, катализатора, фазовых переходов и тепла реакции.",
                  (252, 738), 15, ORANGE)
        self.text("Во время справки модель приостановлена. Подробности и формулы — в README.md.",
                  (252, 768), 15, MUTED)

    def draw(self):
        self.canvas.fill(BG)
        self.draw_header()
        self.draw_metrics()
        self.draw_plant()
        self.draw_controls()
        history = self.visible_history()
        self.draw_chart((416, 252, 1000, 286), "temperature", history)
        self.draw_chart((416, 554, 1000, 230), "rate", history)
        for widget in self.widgets:
            widget.draw(self)
        self.draw_footer()
        if self.help_visible:
            self.draw_help()
        width, height = self.screen.get_size()
        scale = min(width / WIDTH, height / HEIGHT)
        target_size = (round(WIDTH * scale), round(HEIGHT * scale))
        scaled = pygame.transform.smoothscale(self.canvas, target_size)
        self.screen.fill(BG)
        self.screen.blit(scaled, ((width - target_size[0]) // 2, (height - target_size[1]) // 2))
        pygame.display.flip()

    def run(self):
        while self.running:
            elapsed = min(self.clock.tick(60) / 1000.0, 0.1)
            for event in pygame.event.get():
                self.handle_event(event)
            if not self.paused and not self.help_visible:
                self.sim.advance(elapsed * SPEEDS[self.speed_index])
            self.draw()
        pygame.quit()
