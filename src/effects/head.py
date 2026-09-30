# Developed by ::> Gehan Fernando
"""A simple model of your head: how each ear hears a sound from a given direction.

Three cues make a sound seem to sit somewhere around you:

- Time: sound reaches the near ear first, up to about 0.66 ms earlier
  (Woodworth's formula). This matters most below about 1.2 kHz.
- Level: your head shadows the far ear, a little for low notes and more and
  more as the pitch rises (Brown and Duda's spherical-head model).
- Colour: from behind, your outer ear dulls the top end; from above, a band
  around 7 kHz gets brighter (Blauert's directional bands).

The movement is carried by gains that change 200 times a second. FFmpeg
applies them to fixed delay taps and frequency bands, so there are never
any clicks, comb filters or time-varying filters.
"""

import math

from .motion import Position

# Head radius (m) and the speed of sound (m/s) used by Woodworth's formula
HEAD_RADIUS = 0.0875
SPEED_OF_SOUND = 343.0
MAX_ITD_SECONDS = HEAD_RADIUS / SPEED_OF_SOUND * (math.pi / 2.0 + 1.0)

# Eight taps per ear cover the widest ear gap; 16 gains is a layout FFmpeg knows
DELAY_TAPS = 8

# Crossover points: timing below the first, presence, "height" band, then air
BAND_SPLITS_HZ = (1200, 5000, 10000)

# The bands above the timing band, each with its own gain per ear
HIGH_BANDS = ("presence", "height", "air")

# Head-shadow strength per band (1 = the full model); low notes bend round the head
_LOW_SHADOW = 0.25
_PRESENCE_SHADOW = 0.5
_AIR_SHADOW = 0.8
# Dulling from behind and the overhead brightening, in dB at full strength
_REAR_PRESENCE_DB = -2.0
_REAR_AIR_DB = -6.0
_HEIGHT_BOOST_DB = 6.0

# Brown-Duda head shadow, divided by its value straight ahead so the front is 0 dB
_FRONT_SHADOW = 1.05 + 0.95 * math.cos(1.2 * math.pi / 2.0)


def tap_spacing_samples(sample_rate: int) -> int:
    """Samples between neighbouring delay taps, so all taps cover the largest ITD."""
    return max(1, round(MAX_ITD_SECONDS * sample_rate / (DELAY_TAPS - 1)))


def widest_itd(sample_rate: int) -> float:
    """The largest ear gap the delay taps really give at this rate, in seconds."""
    return tap_spacing_samples(sample_rate) * (DELAY_TAPS - 1) / sample_rate


def _db(value: float) -> float:
    """dB to a plain gain factor."""
    return 10.0 ** (value / 20.0)


def head_shadow(cos_to_ear: float) -> float:
    """High-frequency gain at one ear; cos_to_ear is 1 facing it, -1 opposite."""
    angle = math.acos(max(-1.0, min(1.0, cos_to_ear)))
    return (1.05 + 0.95 * math.cos(1.2 * angle)) / _FRONT_SHADOW


def _shadow_pair(left: float, right: float, strength: float) -> tuple[float, float]:
    """Both ears' gains for one band, scaled so the total power never changes."""
    gain_left, gain_right = left**strength, right**strength
    power = math.sqrt((gain_left**2 + gain_right**2) / 2.0)
    return gain_left / power, gain_right / power


def _taps(delay_in_taps: float) -> list[float]:
    """Split one delay between the two nearest taps (a smooth fractional delay)."""
    return [max(0.0, 1.0 - abs(delay_in_taps - tap)) for tap in range(DELAY_TAPS)]


def binaural_gains(  # pylint: disable=too-many-locals
    position: Position,
) -> tuple[list[float], list[float]]:
    """Gains for the 3D engine: (left taps + right taps, left bands + right bands)."""
    amount = position.intensity
    # Sounds overhead are less to one side, so height softens the side cues a bit
    spread = amount * (1.0 - 0.5 * position.height)
    lateral = math.sin(position.azimuth)
    rear = max(0.0, -math.cos(position.azimuth)) * amount

    # Woodworth ITD as a share of the largest; positive = the left ear hears it later
    itd = spread * (math.asin(lateral) + lateral) / (math.pi / 2.0 + 1.0)
    delay_left = max(0.0, itd) * (DELAY_TAPS - 1)
    delay_right = max(0.0, -itd) * (DELAY_TAPS - 1)

    shadow_left, shadow_right = head_shadow(-lateral), head_shadow(lateral)
    low_level = _shadow_pair(shadow_left, shadow_right, _LOW_SHADOW * spread)
    presence = _shadow_pair(shadow_left, shadow_right, _PRESENCE_SHADOW * spread)
    air = _shadow_pair(shadow_left, shadow_right, _AIR_SHADOW * spread)
    rear_presence = _db(_REAR_PRESENCE_DB * rear)
    rear_air = _db(_REAR_AIR_DB * rear)
    height_boost = _db(_HEIGHT_BOOST_DB * position.height * amount)

    low = [gain * low_level[0] for gain in _taps(delay_left)] + [
        gain * low_level[1] for gain in _taps(delay_right)
    ]
    high: list[float] = []
    for ear in (0, 1):
        high.append(presence[ear] * rear_presence)
        # The height band sits between presence and air, so it shares their shadow
        high.append(math.sqrt(presence[ear] * air[ear]) * rear_presence * height_boost)
        high.append(air[ear] * rear_air)
    return low, high


def pan_gains(position: Position) -> list[float]:
    """Constant-power left/right gains for the plain panning engine."""
    pan = position.intensity * math.sin(position.azimuth)
    angle = (pan + 1.0) * math.pi / 4.0
    # sqrt(2) keeps the middle at full volume, like the untouched song
    return [math.cos(angle) * math.sqrt(2.0), math.sin(angle) * math.sqrt(2.0)]
