"""Задание студенту: изменяйте ТОЛЬКО функцию regulator и нажимайте F5.

В интерфейсе выберите «Студент» (клавиша 5).
Возвращаемое значение — доля мощности 0.0 ... 1.0, а не ватты и не проценты.
Регулятор видит только датчик температуры; температуру нагревателя он не знает.
"""


def regulator(temperature: float, dt: float, target: float, state: dict) -> float:
    """Вычислить команду для источника мощности.

    temperature: показание датчика, °C (с небольшой инерцией).
    dt: время между вызовами, в секундах МОДЕЛИ; всегда 0.25 с.
    target: заданная температура, 100 °C.
    state: память между вызовами. Очищается при R, F5 и смене режима.

    Не используйте time.time(), sleep() и цикл while: один вызов — один расчёт.
    Выход за диапазон ограничивается. Исключение/NaN отключает мощность до
    исправления кода и F5 или переключения режима. Бочка продолжает остывать.

    Начальный пример — ПИД. Попробуйте выставить ki = kd = 0 для П-регулятора
    или увеличить ki до 0.01 и посмотреть, как изменятся колебания.
    """
    kp, ki, kd = 0.05, 0.0001, 1.2
    error = target - temperature

    # П реагирует на текущую ошибку. Д тормозит нагрев при росте температуры.
    proportional = kp * error
    previous = state.get("previous_temperature", temperature)
    derivative = -kd * (temperature - previous) / dt
    state["previous_temperature"] = temperature

    # И накапливает ошибку. При насыщении принимаем новый интеграл только
    # если ошибка помогает вернуть команду в рабочий диапазон.
    integral = state.get("integral", 0.0)
    candidate = integral + error * dt
    trial = proportional + ki * candidate + derivative
    pushes_above = trial > 1.0 and error > 0.0
    pushes_below = trial < 0.0 and error < 0.0
    if not (pushes_above or pushes_below):
        integral = candidate
    state["integral"] = integral

    power = proportional + ki * integral + derivative
    return max(0.0, min(1.0, power))
