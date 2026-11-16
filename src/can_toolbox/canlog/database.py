"""DBC databases assigned to bus channels, as in a CANoe configuration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from can_toolbox.canlog.decode import MessageCodec, message_key

ALL_CHANNELS = 0


@dataclass(frozen=True)
class DbcAssignment:
    path: Path
    # Bus channel numbered from 1; ALL_CHANNELS applies the DBC to every channel.
    channel: int = ALL_CHANNELS


@dataclass(frozen=True)
class SignalValue:
    name: str
    physical: float | int | None
    raw: int | float | None
    unit: str
    label: str | None


@dataclass
class LogDatabase:
    """Resolve a frame (message key, channel) to its DBC message.

    A DBC assigned to the frame's channel wins over one assigned to all
    channels; within the same scope the earlier assignment wins, like the
    database order in a CANoe configuration.
    """

    assignments: tuple[DbcAssignment, ...] = ()
    errors: tuple[str, ...] = ()
    # (channel scope, {message key: cantools message}, path) in lookup order.
    _scoped: list[tuple[int, dict[int, Any], Path]] = field(default_factory=list, repr=False)
    _codecs: dict[tuple[int, int], MessageCodec | None] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, assignments: Sequence[DbcAssignment]) -> LogDatabase:
        import cantools

        scoped: list[tuple[int, dict[int, Any], Path]] = []
        errors: list[str] = []
        for assignment in assignments:
            try:
                database = cantools.database.load_file(str(assignment.path), strict=False)
            except Exception as exc:  # cantools raises many parser-specific types
                errors.append(f"{assignment.path.name}: {exc}")
                continue
            by_key: dict[int, Any] = {}
            for message in database.messages:
                by_key.setdefault(message_key(message.frame_id, message.is_extended_frame), message)
            scoped.append((assignment.channel, by_key, assignment.path))
        # Channel-specific databases are searched first.
        scoped.sort(key=lambda item: item[0] == ALL_CHANNELS)
        return cls(assignments=tuple(assignments), errors=tuple(errors), _scoped=scoped)

    def __bool__(self) -> bool:
        return bool(self._scoped)

    def codec(self, key: int, channel: int) -> MessageCodec | None:
        cache_key = (key, channel)
        if cache_key not in self._codecs:
            self._codecs[cache_key] = self._find(key, channel)
        return self._codecs[cache_key]

    def _find(self, key: int, channel: int) -> MessageCodec | None:
        for scope, by_key, _ in self._scoped:
            if scope in (ALL_CHANNELS, channel) and key in by_key:
                return MessageCodec(by_key[key])
        return None

    def message_name(self, key: int, channel: int) -> str:
        codec = self.codec(key, channel)
        return codec.name if codec is not None else ""

    def messages(self) -> Iterable[tuple[int, Any]]:
        """Every (channel scope, cantools message) pair, in lookup order."""
        for scope, by_key, _ in self._scoped:
            for message in by_key.values():
                yield scope, message


def decode_frame(codec: MessageCodec, data: bytes) -> list[SignalValue]:
    """Decode one frame for display: physical value, raw value and value-table label.

    A frame cantools cannot decode returns no signals rather than raising.
    """
    message = codec.message
    try:
        raw = message.decode(data, decode_choices=False, scaling=False, allow_truncated=True)
        physical = message.decode(data, decode_choices=False, scaling=True, allow_truncated=True)
    except Exception:
        return []
    values = []
    for signal in message.signals:
        if signal.name not in physical:
            continue
        raw_value = raw.get(signal.name)
        choices = signal.conversion.choices or {}
        label = choices.get(raw_value)
        values.append(
            SignalValue(
                name=signal.name,
                physical=physical[signal.name],
                raw=raw_value,
                unit=signal.unit or "",
                label=str(label) if label is not None else None,
            )
        )
    return values


__all__ = ["ALL_CHANNELS", "DbcAssignment", "LogDatabase", "SignalValue", "decode_frame", "message_key"]
