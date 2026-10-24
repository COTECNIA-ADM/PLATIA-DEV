"""Almacenamiento de ficheros subidos (Capítulo 9, paso 1 del análisis documental).

- Solo extensiones permitidas y con firma (magic bytes) coherente: un .pdf tiene
  que empezar por %PDF, un .docx tiene que ser un ZIP.
- El fichero se guarda con un nombre aleatorio en una ruta por año/mes; el nombre
  original solo se conserva como dato, nunca se usa para construir rutas.
- SHA-256 calculado mientras se escribe, para detectar duplicados.
"""
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..errors import ValidationError
from ..models import utcnow

ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0"  # .doc/.xls antiguos
ALLOWED = {
    "pdf": ("application/pdf", (b"%PDF",)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", (ZIP_MAGIC,)),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (ZIP_MAGIC,)),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", (ZIP_MAGIC,)),
    "odt": ("application/vnd.oasis.opendocument.text", (ZIP_MAGIC,)),
    "doc": ("application/msword", (OLE_MAGIC,)),
    "rtf": ("application/rtf", (b"{\\rtf",)),
    "txt": ("text/plain", ()),
    "md": ("text/markdown", ()),
    "csv": ("text/csv", ()),
}
CHUNK = 1024 * 1024


@dataclass
class StoredFile:
    storage_path: str  # relativa a DOCUMENT_STORAGE_PATH
    original_filename: str
    extension: str
    mime_type: str
    sha256: str
    size: int


def storage_root() -> Path:
    root = Path(current_app.config["DOCUMENT_STORAGE_PATH"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def absolute_path(storage_path: str) -> Path:
    """Ruta absoluta comprobando que no se sale del directorio de almacenamiento."""
    root = storage_root().resolve()
    path = (root / storage_path).resolve()
    if root not in path.parents:
        raise ValidationError("Ruta de almacenamiento no válida.")
    return path


def save_upload(upload: FileStorage | None, subdir: str = "documents") -> StoredFile:
    if upload is None or not upload.filename:
        raise ValidationError("Falta el fichero (campo 'file').")
    original = secure_filename(upload.filename) or "documento"
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if extension not in ALLOWED:
        raise ValidationError(
            f"Tipo de fichero no admitido. Permitidos: {', '.join(sorted(ALLOWED))}."
        )
    mime_type, signatures = ALLOWED[extension]
    max_bytes = current_app.config["DOCUMENT_MAX_MB"] * 1024 * 1024

    now = utcnow()
    relative = Path(subdir) / f"{now:%Y}" / f"{now:%m}" / f"{uuid.uuid4().hex}.{extension}"
    target = storage_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with open(tmp, "wb") as fh:
            while chunk := upload.stream.read(CHUNK):
                if not head:
                    head = chunk[:8]
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(
                        f"El fichero supera el máximo de {current_app.config['DOCUMENT_MAX_MB']} MB."
                    )
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise ValidationError("El fichero está vacío.")
        if signatures and not any(head.startswith(sig) for sig in signatures):
            raise ValidationError("El contenido del fichero no corresponde a su extensión.")
        if not signatures and b"\x00" in head:
            raise ValidationError("El fichero de texto contiene datos binarios.")
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return StoredFile(storage_path=relative.as_posix(), original_filename=original[:255],
                      extension=extension, mime_type=mime_type, sha256=digest.hexdigest(), size=size)


def delete_file(storage_path: str | None) -> None:
    if storage_path:
        absolute_path(storage_path).unlink(missing_ok=True)


def save_bytes(content: bytes, filename: str, subdir: str) -> StoredFile:
    """Guarda un fichero generado por la plataforma con las mismas comprobaciones."""
    import io

    return save_upload(FileStorage(io.BytesIO(content), filename=filename), subdir=subdir)
