import io

import docx
from pypdf import PdfWriter

from app.extensions import db
from app.models import Document


def _upload(client, h, content: bytes, name: str, url="/api/documents", **form):
    return client.post(url, data={"file": (io.BytesIO(content), name), **form}, headers=h,
                       content_type="multipart/form-data")


def _docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_upload_txt_is_processed_by_the_worker(client, as_role):
    h = as_role("analyst")
    resp = _upload(client, h, "Requisitos: solvencia técnica y ENS nivel medio".encode(), "pliego.txt",
                   doc_type="requirements")
    assert resp.status_code == 201, resp.json
    doc_id = resp.json["id"]
    # En los tests Celery ejecuta la tarea en línea (task_always_eager)
    status = client.get(f"/api/documents/{doc_id}/status", headers=h).json
    assert status["processing_status"] == "processed"
    detail = client.get(f"/api/documents/{doc_id}", headers=h).json
    assert "ENS nivel medio" in detail["text_preview"]
    assert len(detail["file_hash"]) == 64 and detail["doc_type"] == "requirements"
    download = client.get(f"/api/documents/{doc_id}/download", headers=h)
    assert download.status_code == 200 and b"solvencia" in download.data


def test_docx_and_pdf_extraction(client, as_role):
    h = as_role("analyst")
    resp = _upload(client, h, _docx_bytes("Servicio de mantenimiento evolutivo"), "memoria.docx")
    detail = client.get(f"/api/documents/{resp.json['id']}", headers=h).json
    assert detail["processing_status"] == "processed"
    assert "mantenimiento evolutivo" in detail["text_preview"]

    writer, buffer = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=200, height=200)
    writer.write(buffer)
    resp = _upload(client, h, buffer.getvalue(), "escaneado.pdf")
    detail = client.get(f"/api/documents/{resp.json['id']}", headers=h).json
    assert detail["processing_status"] == "processed"
    assert "escaneado" in detail["processing_error"]


def test_rejects_wrong_type_spoofed_content_and_big_files(client, as_role):
    h = as_role("analyst")
    assert _upload(client, h, b"MZ\x90\x00", "virus.exe").status_code == 422
    resp = _upload(client, h, b"esto no es un pdf", "falso.pdf")
    assert resp.status_code == 422 and "extensión" in resp.json["error"]
    assert _upload(client, h, b"", "vacio.txt").status_code == 422
    big = b"a" * (2 * 1024 * 1024 + 10)  # el máximo en tests es 2 MB
    assert _upload(client, h, big, "grande.txt").status_code == 422
    assert db.session.scalar(db.select(db.func.count()).select_from(Document)) == 0


def test_duplicates_and_versions(client, as_role):
    h = as_role("analyst")
    first = _upload(client, h, b"version 1", "oferta.txt").json
    dup = _upload(client, h, b"version 1", "copia.txt")
    assert dup.status_code == 409 and dup.json["details"]["existing_document_id"] == first["id"]

    v2 = _upload(client, h, b"version 2", "oferta.txt", url=f"/api/documents/{first['id']}/versions")
    assert v2.status_code == 201
    assert v2.json["version_number"] == 2 and len(v2.json["versions"]) == 2
    old = client.get(f"/api/documents/{first['id']}", headers=h).json
    assert old["is_current_version"] is False
    listing = client.get("/api/documents", headers=h).json
    assert [d["id"] for d in listing["items"]] == [v2.json["id"]]
    # Borrar desde la versión actual borra todas
    manager = as_role("manager")
    assert client.delete(f"/api/documents/{first['id']}", headers=manager).status_code == 422
    assert client.delete(f"/api/documents/{v2.json['id']}", headers=manager).status_code == 204
    assert client.get(f"/api/documents/{first['id']}", headers=h).status_code == 404


def test_only_uploader_or_manager_can_modify(client, as_role):
    owner, other, manager = as_role("analyst", "a@example.com"), as_role("analyst", "b@example.com"), \
        as_role("manager")
    doc = _upload(client, owner, b"contenido", "a.txt").json
    url = f"/api/documents/{doc['id']}"
    assert client.patch(url, json={"version": doc["version"], "title": "x"}, headers=other).status_code == 403
    resp = client.patch(url, json={"version": doc["version"], "title": "Pliego"}, headers=manager)
    assert resp.status_code == 200 and resp.json["title"] == "Pliego"
    assert client.delete(url, headers=owner).status_code == 403  # el analista no tiene delete
    assert client.delete(url, headers=manager).status_code == 204


def test_filename_cannot_escape_storage(client, as_role, app):
    h = as_role("analyst")
    resp = _upload(client, h, b"hola", "../../../etc/passwd.txt")
    assert resp.status_code == 201
    stored = db.session.get(Document, resp.json["id"])
    assert ".." not in stored.storage_path and stored.original_filename == "etc_passwd.txt"
