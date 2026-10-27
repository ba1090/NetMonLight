"""Trasferimento di un utente: il file esportato è cifrato con la password scelta da chi esporta."""
import time

from conftest import netmon


def _wait(admin, tid):
    for _ in range(300):
        j = admin.get(f"/api/admin/transfer/job?id={tid}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("trasferimento non finito")


def _upload(admin, data, tid="t" * 20):
    r = admin.c.post(f"/api/admin/transfer/upload?id={tid}&part=0&parts=1", content=data,
                     headers={**admin.headers, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    return r.json()


def test_export_is_encrypted_and_opens_only_with_its_password(make_user, admin):
    u = make_user()
    p = u.new_probe("sonda segreta")
    assert p.report().status_code == 200
    pw = "vetro-lampo-trenta-ginepro"
    # password del file troppo corta: rifiutata
    r = admin.post("/api/admin/transfer/export", {"id": u.id, "password": admin.password, "file_password": "corta"})
    assert r.status_code == 422
    r = admin.post("/api/admin/transfer/export", {"id": u.id, "password": admin.password, "file_password": pw})
    assert r.status_code == 200, r.text
    assert _wait(admin, r.json()["id"])["state"] == "done"
    d = admin.get(f"/api/admin/transfer/download?id={r.json()['id']}")
    assert d.status_code == 200 and d.content.startswith(netmon.XFER_MAGIC)
    assert d.headers["content-disposition"].endswith('.netmon"')
    # dentro non si legge nulla: né l'email, né il nome della sonda, né la struttura dello zip
    for clear in (u.email.encode(), b"sonda segreta", b"manifest.json", b"account.json", b"PK\x03\x04"):
        assert clear not in d.content
    # nessuno zip in chiaro resta sul server
    assert not list(netmon.TRANSFER_DIR.glob("export-*.zip"))

    up = _upload(admin, d.content, "a" * 20)
    assert up == {"ok": True, "encrypted": True}
    bad = admin.post("/api/admin/transfer/open", {"id": "a" * 20, "file_password": "password-sbagliata"})
    assert bad.status_code == 422 and bad.json()["detail"] == netmon.XFER_BAD
    ok = admin.post("/api/admin/transfer/open", {"id": "a" * 20, "file_password": pw})   # si riprova senza ricaricare
    assert ok.status_code == 200, ok.text
    pv = ok.json()["preview"]
    assert pv["email"] == u.email and pv["exists"] and pv["probes"] == ["sonda segreta"]


def test_modified_file_is_refused(make_user, admin):
    u = make_user()
    assert u.new_probe().report().status_code == 200
    r = admin.post("/api/admin/transfer/export", {"id": u.id, "password": admin.password, "file_password": "x" * 16})
    _wait(admin, r.json()["id"])
    data = bytearray(admin.get(f"/api/admin/transfer/download?id={r.json()['id']}").content)
    data[len(data) // 2] ^= 1
    _upload(admin, bytes(data), "b" * 20)
    r = admin.post("/api/admin/transfer/open", {"id": "b" * 20, "file_password": "x" * 16})
    assert r.status_code == 422 and r.json()["detail"] == netmon.XFER_BAD


def test_old_plain_zip_still_imports(make_user, admin, tmp_path):
    u = make_user()
    p = u.new_probe()
    assert p.report().status_code == 200
    zp = tmp_path / "vecchio.zip"
    netmon.transfer_export(u.id, {}, str(zp))
    up = _upload(admin, zp.read_bytes(), "c" * 20)
    assert up["plain"] is True and up["preview"]["email"] == u.email
