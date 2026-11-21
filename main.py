"""Запуск: python main.py. Для автоматической проверки: --headless --seconds 900."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Учебный стенд теплового регулирования на Pygame")
    parser.add_argument("--headless", action="store_true", help="расчёт и снимок без окна")
    parser.add_argument("--seconds", type=float, default=900, help="длительность расчёта без окна, с модели")
    parser.add_argument("--screenshot", type=Path, help="сохранить PNG кадра (в режиме --headless)")
    parser.add_argument("--mode", choices=("manual", "relay", "p", "pid", "student"), default="relay")
    args = parser.parse_args()
    if args.seconds < 0 or not math.isfinite(args.seconds):
        parser.error("--seconds должен быть конечным неотрицательным числом")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    try:
        from app import LabApp
        import pygame
    except ModuleNotFoundError as exc:
        if exc.name == "pygame":
            parser.exit(1, "Установите Pygame: python -m pip install -r requirements.txt\n")
        raise
    app = LabApp(size=(1440, 960) if args.headless else None)
    app.sim.set_mode(args.mode)
    if args.headless:
        app.sim.advance(args.seconds)
        app.draw()
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(app.canvas, str(args.screenshot))
        print(f"t={app.sim.time:.2f} s; T={app.sim.temperature:.2f} C; "
              f"peak={app.sim.peak_temperature:.2f} C; PE={app.sim.polymer_mass:.3f} kg")
        pygame.quit()
    else:
        app.run()


if __name__ == "__main__":
    main()
