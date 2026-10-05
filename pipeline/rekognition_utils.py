"""Utilidades compartidas para llamadas a AWS Rekognition.

Nace de un caso real: un poster de 16.4MB (1027933) hizo fallar
title_boxes_rekognition.py con "image too large" — Rekognition rechaza
cualquier imagen sobre 5MB via el modo Bytes (S3Object no tiene ese limite,
pero Bytes si). Al menos 5 scripts de este pipeline leen posters con
path.read_bytes() y se los pasan crudo a Rekognition, así que todos tienen
el mismo riesgo latente sobre el corpus completo (posters muy pesados son
raros pero existen). Import esta funcion en vez de repetir el fix cinco veces.
"""
from __future__ import annotations

import io
from pathlib import Path

REKOGNITION_MAX_BYTES = 5_000_000


def load_image_bytes_for_rekognition(path: Path, max_bytes: int = REKOGNITION_MAX_BYTES) -> bytes:
    """Lee una imagen local y la devuelve lista para Image={"Bytes": ...}.

    Si ya esta bajo el limite, devuelve los bytes crudos sin re-codificar
    (evita perdida de calidad innecesaria en el caso comun). Si excede el
    limite, la re-comprime: primero baja la calidad JPEG, y si eso no alcanza,
    reduce la resolucion — iterando hasta quedar bajo max_bytes.
    """
    data = path.read_bytes()
    if len(data) <= max_bytes:
        return data

    from PIL import Image

    img = Image.open(path).convert("RGB")
    quality = 90
    scale = 1.0
    while True:
        if scale < 1.0:
            w, h = img.size
            work = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        else:
            work = img
        buf = io.BytesIO()
        work.save(buf, format="JPEG", quality=quality)
        size = buf.tell()
        if size <= max_bytes:
            return buf.getvalue()
        if quality > 40:
            quality -= 10
        elif scale > 0.3:
            scale *= 0.85
        else:
            # last resort: whatever we have, even if still (barely) over —
            # better than a hard failure, and by this point we're deep into
            # diminishing returns on further compression
            return buf.getvalue()
