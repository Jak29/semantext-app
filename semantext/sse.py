"""Server-sent events, read from bytes in whatever pieces they arrive (PROXY-DESIGN r4, T14).

The reader survives what an upstream may send: CRLF, CR or LF line ends, comment lines (`:`), `id:` and `retry:`,
`data` over several lines (joined with a newline), a UTF-8 character split across two pieces, a long line. It yields
(event name, data text) once per blank line that ends an event with data. The decision about an event is the
assembler's, never this reader's: the same bytes in any chunking give the same events (KP9).

Caps (D14): one line, and one event's data, at most MAX_LINE characters; past it the reader raises TooBig and the turn
is refused.
"""
from __future__ import annotations

import codecs

MAX_LINE = 16 * 1024 * 1024


class TooBig(ValueError):
    """A line or an event over MAX_LINE."""


class Reader:
    def __init__(self):
        self._decode = codecs.getincrementaldecoder("utf-8")("strict")
        self._buf = ""
        self._event = ""
        self._data: list[str] = []
        self._size = 0
        self._cr = False   # the last piece ended with CR: a following LF belongs to it

    def feed(self, piece: bytes) -> list[tuple[str, str]]:
        """Events completed by this piece, in order. Bytes that are not UTF-8 raise UnicodeDecodeError."""
        text = self._decode.decode(piece)
        if self._cr and text.startswith("\n"):
            text = text[1:]
        self._cr = text.endswith("\r")
        self._buf += text
        out = []
        while True:
            i = min((j for j in (self._buf.find("\r"), self._buf.find("\n")) if j >= 0), default=-1)
            if i < 0:
                if len(self._buf) > MAX_LINE:
                    raise TooBig(f"a line over {MAX_LINE} characters")
                return out
            line = self._buf[:i]
            step = 2 if self._buf[i:i + 2] == "\r\n" else 1
            self._buf = self._buf[i + step:]
            ev = self._line(line)
            if ev is not None:
                out.append(ev)

    def _line(self, line: str):
        if line == "":
            if not self._data:
                self._event = ""
                return None
            ev = (self._event or "message", "\n".join(self._data))
            self._event, self._data, self._size = "", [], 0
            return ev
        if line.startswith(":"):
            return None                                   # a comment
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "event":
            self._event = value
        elif name == "data":
            self._size += len(value) + 1
            if self._size > MAX_LINE:
                raise TooBig(f"an event over {MAX_LINE} characters")
            self._data.append(value)
        return None                                       # id:, retry: and unknown fields are ignored (the SSE rule)

    def end(self) -> bool:
        """True when the bytes ended cleanly, between events. A cut mid-event or mid-character is False."""
        try:
            self._decode.decode(b"", final=True)
        except UnicodeDecodeError:
            return False
        return self._buf == "" and not self._data
