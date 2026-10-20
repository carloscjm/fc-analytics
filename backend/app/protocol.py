"""Formato das mensagens binárias entre frontend e backend.

Cada frame chega como um único pacote binário:

    bytes 0-3   uint32 little-endian  id do frame (sequencial no navegador)
    bytes 4-11  float64 little-endian momento da captura (performance.now() do navegador, em ms)
    bytes 12-   imagem JPEG (até 1280x720)

O backend devolve o id e o momento da captura junto com as detecções,
para o navegador medir o atraso de ponta a ponta no próprio relógio.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = struct.Struct("<Id")
HEADER_SIZE = HEADER.size  # 12 bytes


class FrameFormatError(ValueError):
    pass


@dataclass(frozen=True)
class FramePacket:
    frame_id: int
    capture_ts: float
    jpeg: bytes


def parse_frame(data: bytes) -> FramePacket:
    if len(data) <= HEADER_SIZE:
        raise FrameFormatError("pacote menor que o cabeçalho")
    frame_id, capture_ts = HEADER.unpack_from(data, 0)
    jpeg = data[HEADER_SIZE:]
    if jpeg[:2] != b"\xff\xd8":
        raise FrameFormatError("conteúdo não é JPEG")
    return FramePacket(frame_id=frame_id, capture_ts=capture_ts, jpeg=jpeg)


def build_frame(frame_id: int, capture_ts: float, jpeg: bytes) -> bytes:
    """Monta um pacote no mesmo formato do navegador (usado em testes e scripts)."""
    return HEADER.pack(frame_id, capture_ts) + jpeg
