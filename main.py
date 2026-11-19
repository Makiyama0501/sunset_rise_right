from machine import Pin
from neopixel import NeoPixel
import time
import math

# ================================
# 基本設定
# ================================
NUM = 60

west = NeoPixel(Pin(0), NUM)
east = NeoPixel(Pin(1), NUM)

btnA = Pin(2, Pin.IN, Pin.PULL_UP)
btnB = Pin(3, Pin.IN, Pin.PULL_UP)
btnC = Pin(4, Pin.IN, Pin.PULL_UP)
btnD = Pin(5, Pin.IN, Pin.PULL_UP)

led = Pin("LED", Pin.OUT)

BLACK = (0, 0, 0)
DEBOUNCE_MS = 15
POLL_MS = 5
LONG_PRESS_MS = 3000


def boot_blink():
    for _ in range(6):
        led.toggle()
        time.sleep(0.5)


# 朝焼け・夕焼けの色設定
sunrise_west = [
    (0, 0, 0),
    (0, 0, 0),
    (0, 0, 32),
    (64, 73, 139),
    (85, 109, 171),
    (116, 203, 244)
]

sunrise_east = [
    (0, 0, 1),
    (0, 0, 20),
    (63, 58, 139),
    (240, 90, 60),
    (250, 110, 70),
    (255, 150, 80)
]

sunset_west = [
    (255, 80, 30),
    (255, 50, 40),
    (255, 30, 60),
    (10, 30, 130),
    (0, 0, 64),
    (0, 0, 0)
]

sunset_east = [
    (10, 30, 130),
    (5, 20, 110),
    (0, 10, 90),
    (0, 0, 64),
    (0, 0, 0),
    (0, 0, 0)
]


class Buttons:
    def __init__(self):
        self.pins = (btnA, btnB, btnC, btnD)
        self.modes = ("sunset", "sunrise", "fixed", "off")
        self.raw = [pin.value() for pin in self.pins]
        self.stable = self.raw[:]
        self.changed_at = [time.ticks_ms()] * len(self.pins)
        self.chord_started = None
        self.chord_used = False

    def read(self, now):
        request = None
        # 同じ周期で複数の押下が確定した場合は、従来どおりDを優先する。
        for i, pin in enumerate(self.pins):
            value = pin.value()
            if value != self.raw[i]:
                self.raw[i] = value
                self.changed_at[i] = now
            elif (value != self.stable[i]
                  and time.ticks_diff(now, self.changed_at[i]) >= DEBOUNCE_MS):
                self.stable[i] = value
                if value == 0:
                    request = self.modes[i]

        if all(self.stable):
            self.chord_used = False

        # 長押しを判定している間も照明の更新は続ける。
        if not self.chord_used and not any(self.stable):
            if self.chord_started is None:
                self.chord_started = now
            elif time.ticks_diff(now, self.chord_started) >= LONG_PRESS_MS:
                self.chord_used = True
                self.chord_started = None
                return "special"
            return None

        self.chord_started = None
        return request


def fill_pair(west_color, east_color):
    west.fill(west_color)
    east.fill(east_color)
    west.write()
    east.write()


def fade_out(duration_ms):
    starts = [[strip[i] for i in range(NUM)] for strip in (west, east)]
    steps = 20
    for step in range(1, steps):
        yield duration_ms * step // steps - duration_ms * (step - 1) // steps
        remaining = steps - step
        for strip, start in zip((west, east), starts):
            for i, (r, g, b) in enumerate(start):
                strip[i] = (r * remaining // steps,
                            g * remaining // steps,
                            b * remaining // steps)
            strip.write()

    yield duration_ms - duration_ms * (steps - 1) // steps
    fill_pair(BLACK, BLACK)


def sky_color(start_color, end_color, t, is_sunrise):
    channels = []
    for start, end in zip(start_color, end_color):
        darkness = max(0, (64 - max(start, end)) / 64)
        gamma = 1 + darkness ** 6 * 8 if is_sunrise else 1 + darkness
        channels.append(int(start + (end - start) * t ** gamma))
    return tuple(channels)


def sky_sequence(west_seq, east_seq, section_times, is_sunrise):
    steps = 50
    for i, duration_ms in enumerate(section_times):
        for step in range(steps):
            t = step / steps
            fill_pair(
                sky_color(west_seq[i], west_seq[i + 1], t, is_sunrise),
                sky_color(east_seq[i], east_seq[i + 1], t, is_sunrise),
            )
            yield duration_ms // steps


def sunset():
    yield from sky_sequence(sunset_west, sunset_east, (6000,) * 5, False)
    yield from fade_out(100)


def sunrise():
    for offset, delay_ms in zip((0, 12, 25, 38, 52), (700, 400, 300, 200, 0)):
        for i in range(offset, offset + 5):
            east[i] = (0, 0, 1)
        east.write()
        yield delay_ms

    yield from sky_sequence(
        sunrise_west, sunrise_east, (8500, 6500, 5000, 5000, 5000), True
    )
    fill_pair(sunrise_west[-1], sunrise_east[-1])


# 特殊照明の色設定
colors = [
    (180, 0, 30),
    (255, 50, 100),
    (128, 0, 128),
    (200, 0, 50)
]

def interpolate_color(start, end, t, gamma=1.0):
    t_gamma = t ** gamma
    r = int(start[0] + (end[0] - start[0]) * t_gamma)
    g = int(start[1] + (end[1] - start[1]) * t_gamma)
    b = int(start[2] + (end[2] - start[2]) * t_gamma)
    return (r, g, b)

def get_gamma_for_segment(start, end):
    avg_val = (sum(start) + sum(end)) / 6
    gamma = 1.0 + max(0, (64 - avg_val) / 64)
    return gamma

def love_hotel_lighting():
    steps = 200
    while True:
        for i, start_color in enumerate(colors):
            end_color = colors[(i + 1) % len(colors)]
            gamma = get_gamma_for_segment(start_color, end_color)
            for step in range(steps):
                t_step = step / steps
                phase = time.ticks_ms() / 4000
                for j in range(NUM):
                    position = j / (NUM - 1)
                    t_eff = t_step * (1 - position) + position
                    offset = math.sin(j / NUM * math.pi * 2 + phase) * 0.05
                    color = interpolate_color(
                        start_color, end_color, min(max(t_eff + offset, 0), 1), gamma
                    )
                    west[j] = color
                    east[j] = color
                west.write()
                east.write()
                yield 75


def start_mode(request, previous_mode):
    if request == "sunset":
        return sunset()
    if request == "sunrise":
        return sunrise()
    if request == "fixed":
        fill_pair(sunset_west[0], sunset_east[0])
        return None
    if request == "special":
        return love_hotel_lighting()
    return fade_out(500 if previous_mode == "special" else 1000)


def main():
    print("Ready...")
    boot_blink()
    time.sleep_ms(100)
    fill_pair(BLACK, BLACK)
    buttons = Buttons()
    mode = "off"
    frames = None
    frame_due = time.ticks_ms()

    while True:
        now = time.ticks_ms()
        request = buttons.read(now)
        if request is not None:
            print(request)
            frames = start_mode(request, mode)
            mode = request
            frame_due = now

        if frames is not None and time.ticks_diff(now, frame_due) >= 0:
            try:
                delay_ms = next(frames)
            except StopIteration:
                frames = None
            else:
                frame_due = time.ticks_add(time.ticks_ms(), delay_ms)

        time.sleep_ms(POLL_MS)


if __name__ == "__main__":
    main()

