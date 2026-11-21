"""Проверяем физический смысл модели и контракт студенческого регулятора."""

import csv
import math
import tempfile
import unittest
from pathlib import Path

from simulation import CONTROL_DT, FIXED_DT, Parameters, Simulation, load_student_controller, temperature_factor


class KineticsTests(unittest.TestCase):
    def test_window_peak_and_symmetry(self):
        self.assertEqual(temperature_factor(100), 1)
        for temperature in (20, 89, 111, 200):
            self.assertEqual(temperature_factor(temperature), 0)
        for temperature in (90, 110):
            self.assertGreater(temperature_factor(temperature), 0)
        values = [temperature_factor(100 + distance) for distance in range(11)]
        self.assertEqual(values, sorted(values, reverse=True))
        for distance in range(11):
            self.assertEqual(temperature_factor(100 - distance), temperature_factor(100 + distance))

    def test_mass_conserved_and_synthesis_stops_when_empty(self):
        sim = Simulation(Parameters(initial_mass=0.001))
        sim.temperature = sim.heater_temperature = sim.sensor_temperature = 100
        sim.advance(1)
        self.assertEqual(sim.polymer_mass, 0.001)
        self.assertEqual(sim.remaining_mass, 0)
        self.assertEqual(sim.rate, 0)
        self.assertEqual(sim.polymer_mass + sim.remaining_mass, sim.parameters.initial_mass)

    def test_no_synthesis_outside_temperature_window(self):
        sim = Simulation()
        sim.set_mode("manual")
        sim.manual_duty = 0
        sim.temperature = sim.heater_temperature = 120
        sim.advance(1)
        self.assertEqual(sim.polymer_mass, 0)


class ThermalTests(unittest.TestCase):
    def test_internal_heat_exchange_conserves_energy(self):
        p = Parameters(reactor_loss=0, heater_loss=0)
        sim = Simulation(p)
        sim.set_mode("manual")
        sim.manual_duty = 0
        sim.temperature, sim.heater_temperature = 80, 180
        energy_before = p.reactor_capacity * sim.temperature + p.heater_capacity * sim.heater_temperature
        sim.advance(60)
        energy_after = p.reactor_capacity * sim.temperature + p.heater_capacity * sim.heater_temperature
        self.assertAlmostEqual(energy_before, energy_after, places=6)

    def test_barrel_keeps_heating_after_power_is_cut(self):
        sim = Simulation()
        sim.set_mode("manual")
        sim.manual_duty = 0
        sim.temperature, sim.heater_temperature = 95, 160
        sim.advance(10)
        self.assertEqual(sim.power_kw, 0)
        self.assertGreater(sim.temperature, 95)
        self.assertLess(sim.heater_temperature, 160)

    def test_ambient_is_an_equilibrium_without_power(self):
        sim = Simulation()
        sim.set_mode("manual")
        sim.manual_duty = 0
        sim.advance(100)
        self.assertEqual(sim.temperature, sim.parameters.ambient)
        self.assertEqual(sim.heater_temperature, sim.parameters.ambient)

    def test_energy_from_source_and_losses_balance_one_step(self):
        sim = Simulation()
        sim.set_mode("manual")
        sim.manual_duty = 0.4
        sim.temperature, sim.heater_temperature = 80, 150
        p = sim.parameters
        before = p.reactor_capacity * sim.temperature + p.heater_capacity * sim.heater_temperature
        expected = FIXED_DT * (0.4 * p.supply_kw * 1000 - p.reactor_loss * 60 - p.heater_loss * 130)
        sim.step()
        after = p.reactor_capacity * sim.temperature + p.heater_capacity * sim.heater_temperature
        self.assertAlmostEqual(after - before, expected, places=6)

    def test_fixed_steps_do_not_depend_on_frame_rate(self):
        a, b = Simulation(), Simulation()
        a.advance(60)
        for _ in range(3600):
            b.advance(1 / 60)
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(a.history, b.history)

    def test_pid_reduces_overshoot_and_rejects_cooling_disturbance(self):
        relay, pid = Simulation(), Simulation()
        pid.set_mode("pid")
        relay.advance(1200)
        pid.advance(1200)
        self.assertGreater(relay.overshoot, 5)
        self.assertLess(pid.overshoot, 1)
        self.assertLess(abs(pid.temperature - 100), 0.2)
        previous_power = pid.power_kw
        pid.cooling = True
        pid.advance(1800)
        self.assertLess(abs(pid.temperature - 100), 0.5)
        self.assertGreater(pid.power_kw, previous_power)

    def test_sensor_has_lag(self):
        sim = Simulation()
        sim.set_mode("manual")
        sim.temperature = sim.heater_temperature = 100
        sim.step()
        self.assertGreater(sim.sensor_temperature, 20)
        self.assertLess(sim.sensor_temperature, sim.temperature)


class ControllerTests(unittest.TestCase):
    def test_callback_interval_and_state(self):
        observations = []

        def regulator(temperature, dt, target, state):
            state["calls"] = state.get("calls", 0) + 1
            observations.append((dt, target, state["calls"]))
            return 0.5

        sim = Simulation(student_controller=regulator)
        sim.set_mode("student")
        sim.advance(10)
        self.assertEqual(len(observations), 40)
        self.assertTrue(all(row[:2] == (CONTROL_DT, 100) for row in observations))
        self.assertEqual(observations[-1][2], 40)
        self.assertEqual(sim.duty, 0.5)
        sim.reset()
        self.assertEqual(sim.control_state, {})

    def test_outputs_are_limited_to_supply_range(self):
        for returned, expected in ((-5, 0), (0.7, 0.7), (500, 1)):
            sim = Simulation(student_controller=lambda *args: returned)
            sim.set_mode("student")
            sim.step()
            self.assertEqual(sim.duty, expected)
            self.assertEqual(sim.power_kw, expected * sim.parameters.supply_kw)

    def test_bad_code_switches_off_power_but_thermal_model_continues(self):
        def broken(*args):
            raise RuntimeError("ошибка студента")

        for controller in (broken, lambda *args: math.nan, lambda *args: math.inf, lambda *args: None):
            with self.subTest(controller=controller):
                sim = Simulation(student_controller=controller)
                sim.set_mode("student")
                sim.heater_temperature = 170
                sim.advance(5)
                self.assertTrue(sim.controller_error)
                self.assertEqual(sim.power_kw, 0)
                self.assertGreater(sim.temperature, 20)

    def test_reload_reads_new_source_and_keeps_old_function_on_syntax_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller.py"
            path.write_text("def regulator(*args): return 0.2", encoding="utf-8")
            sim = Simulation(student_controller=load_student_controller(path))
            sim.set_mode("student")
            sim.step()
            self.assertEqual(sim.duty, 0.2)
            path.write_text("def regulator(*args): return 0.8", encoding="utf-8")
            sim.reload_controller(path)
            sim.step()
            self.assertEqual(sim.duty, 0.8)
            path.write_text("def regulator(", encoding="utf-8")
            with self.assertRaises(SyntaxError):
                sim.reload_controller(path)
            self.assertEqual(sim.student_controller(0, 1, 100, {}), 0.8)

    def test_csv_contains_full_run_and_unsampled_final_state(self):
        sim = Simulation()
        sim.advance(1.25)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.csv"
            sim.export_csv(path)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            self.assertEqual(len(rows), 4)
            self.assertEqual(float(rows[0]["time_s"]), 0)
            self.assertEqual(float(rows[-1]["time_s"]), 1.25)
            self.assertAlmostEqual(float(rows[-1]["reactor_C"]), sim.temperature, places=5)


if __name__ == "__main__":
    unittest.main()
