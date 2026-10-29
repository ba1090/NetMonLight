"""Backup completo del server dal pannello e ripristino (Server › Backup e ripristino)."""
import json
import shutil
import sqlite3
import time

from conftest import netmon


def _wait(admin, tid):
    for _ in range(600):
        j = admin.get(f"/api/admin/transfer/job?id={tid}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("backup non finito")


def _upload(admin, data, tid):
    return admin.c.post(f"/api/admin/backup/upload?id={tid}&part=0&parts=1", content=data,
                        headers={**admin.headers, "Content-Type": "application/octet-stream"})


def _backup(admin, pw):
    r = admin.post("/api/admin/backup/export", {"password": admin.password, "file_password": pw})
    assert r.status_code == 200, r.text
    j = _wait(admin, r.json()["id"])
    assert j["state"] == "done", j
    d = admin.get(f"/api/admin/transfer/download?id={r.json()['id']}")
    assert d.status_code == 200
    return j["result"], d


def test_backup_needs_admin_password_and_long_file_password(admin):
    pw = "vetro-lampo-trenta-ginepro"
    assert admin.post("/api/admin/backup/export", {"password": "sbagliata", "file_password": pw}).status_code == 401
    assert admin.post("/api/admin/backup/export", {"password": admin.password, "file_password": "corta"}).status_code == 422


def test_backup_is_encrypted_and_complete(two_users, admin):
    a, pa, b, pb = two_users
    res, d = _backup(admin, "vetro-lampo-trenta-ginepro")
    assert res["users"] >= 2 and res["admins"] >= 1 and res["probes"] >= 2
    assert d.content.startswith(netmon.XFER_MAGIC)
    assert d.headers["content-disposition"].endswith('.netmon"') and "netmon-backup-" in d.headers["content-disposition"]
    for clear in (a.email.encode(), b"sonda A", b"manifest.json", b"SQLite format", b"PK\x03\x04"):
        assert clear not in d.content
    # nessun backup in chiaro resta sul server
    assert not list(netmon.TRANSFER_DIR.glob("backup-*.zip"))


def test_restore_rejects_wrong_password_and_other_files(admin):
    res, d = _backup(admin, "vetro-lampo-trenta-ginepro")
    tid = "bk" + "x" * 20
    assert _upload(admin, d.content, tid).status_code == 200
    r = admin.post("/api/admin/backup/open", {"id": tid, "file_password": "password-sbagliata"})
    assert r.status_code == 422
    # un file non cifrato non viene accettato
    assert _upload(admin, b"PK\x03\x04 non un backup", "bk" + "y" * 20).status_code == 422


def test_restore_prepares_files_and_restarts(two_users, admin, monkeypatch):
    a, pa, b, pb = two_users
    pw = "vetro-lampo-trenta-ginepro"
    res, d = _backup(admin, pw)
    tid = "bk" + "z" * 20
    assert _upload(admin, d.content, tid).status_code == 200
    r = admin.post("/api/admin/backup/open", {"id": tid, "file_password": pw})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["counts"] == {"users": res["users"], "admins": res["admins"], "probes": res["probes"]}
    assert p["version"] == netmon.VERSION and p["current"]["users"] >= 2
    # senza conferma o con la password sbagliata non succede nulla
    assert admin.post("/api/admin/backup/restore", {"id": tid, "password": admin.password}).status_code == 422
    assert admin.post("/api/admin/backup/restore", {"id": tid, "password": "x", "confirm": "RIPRISTINA"}).status_code == 401
    restarted = []
    monkeypatch.setattr(netmon, "restart_service", lambda: restarted.append(True))
    try:
        r = admin.post("/api/admin/backup/restore", {"id": tid, "password": admin.password, "confirm": "RIPRISTINA"})
        assert r.status_code == 200, r.text
        ready = netmon.RESTORE_DIR / "PRONTO"
        assert ready.is_file() and json.loads(ready.read_text())["version"] == netmon.VERSION
        with sqlite3.connect(netmon.RESTORE_DIR / "auth.db") as c:
            emails = {row[0] for row in c.execute("SELECT email FROM users")}
        assert a.email in emails and b.email in emails
        for _ in range(60):                    # il riavvio parte poco dopo la risposta
            if restarted:
                break
            time.sleep(0.05)
        assert restarted
    finally:
        shutil.rmtree(netmon.RESTORE_DIR, ignore_errors=True)    # qui non lo si applica: è il server delle prove


def test_restore_apply_swaps_data_at_startup(tmp_path, monkeypatch):
    data, staged = tmp_path / "data", tmp_path / "data" / "ripristino"
    staged.mkdir(parents=True)
    (data / "auth.db").write_text("vecchio")
    (data / "auth.db-wal").write_text("wal vecchio")
    (data / "state.json").write_text('{"vecchio": 1}')
    (staged / "auth.db").write_text("nuovo")
    (staged / "events.db").write_text("eventi nuovi")
    (staged / "PRONTO").write_text("{}")
    monkeypatch.setattr(netmon, "DATA_DIR", data)
    monkeypatch.setattr(netmon, "RESTORE_DIR", staged)
    netmon.restore_apply()
    assert (data / "auth.db").read_text() == "nuovo" and (data / "events.db").read_text() == "eventi nuovi"
    assert not (data / "auth.db-wal").exists() and not (data / "state.json").exists()
    old = list(data.glob("prima-del-ripristino-*"))
    assert len(old) == 1 and (old[0] / "auth.db").read_text() == "vecchio" and (old[0] / "state.json").exists()
    assert not staged.exists()
    netmon.restore_apply()                      # senza ripristino pronto non fa nulla
    assert (data / "auth.db").read_text() == "nuovo"


# ------------------------------------------------------------------ chiave di firma delle sonde
def _ed25519():
    import subprocess
    return subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519"], capture_output=True, check=True).stdout


def test_backup_carries_probe_key_and_restore_puts_it_back(two_users, admin, monkeypatch):
    """Il backup contiene la chiave di firma delle sonde (letta da netmon-chiave-sonde) e il ripristino
    la rimette: le sonde spostate sulla VM nuova accettano ancora gli aggiornamenti dal pannello."""
    key = _ed25519()
    calls = []

    def tool(cmd, data=None):
        calls.append((cmd, data))
        return (True, key) if cmd == "esporta" else (True, b"Chiave importata")
    monkeypatch.setattr(netmon, "probe_key_tool", tool)
    pw = "vetro-lampo-trenta-ginepro"
    res, d = _backup(admin, pw)
    fp = netmon.private_key_fingerprint(key)
    assert res["probe_key"] == fp and len(fp) == 19
    assert b"PRIVATE KEY" not in d.content                       # cifrata con il resto del file
    tid = "bk" + "k" * 20
    assert _upload(admin, d.content, tid).status_code == 200
    p = admin.post("/api/admin/backup/open", {"id": tid, "file_password": pw}).json()
    assert p["probe_key"] == fp
    monkeypatch.setattr(netmon, "restart_service", lambda: None)
    try:
        r = admin.post("/api/admin/backup/restore", {"id": tid, "password": admin.password, "confirm": "RIPRISTINA"})
        assert r.status_code == 200, r.text
        assert ("importa", key) in calls and fp in r.json()["probe_key"]
        assert not (netmon.RESTORE_DIR / netmon.PROBE_KEY_NAME).exists()    # nessuna copia lasciata sul disco
    finally:
        shutil.rmtree(netmon.RESTORE_DIR, ignore_errors=True)


def test_backup_without_probe_key_still_works(admin, monkeypatch):
    monkeypatch.setattr(netmon, "probe_key_tool", lambda cmd, data=None: (False, "non installato"))
    res, d = _backup(admin, "vetro-lampo-trenta-ginepro")
    assert res["probe_key"] == "" and res["users"] >= 1


def test_restore_refuses_damaged_probe_key(admin, tmp_path, monkeypatch):
    """Un backup con una «chiave» che non è una chiave privata non si ripristina."""
    import zipfile
    monkeypatch.setattr(netmon, "probe_key_tool", lambda cmd, data=None: (False, "no"))
    plain = tmp_path / "b.zip"
    netmon.backup_build(plain)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(plain) as zi, zipfile.ZipFile(bad, "w") as zo:
        for item in zi.infolist():
            zo.writestr(item.filename, zi.read(item.filename))
        zo.writestr(netmon.PROBE_KEY_NAME, b"#!/bin/sh\nrm -rf /\n")
    enc = tmp_path / "bad.netmon"
    netmon.xfer_encrypt(bad, enc, "vetro-lampo-trenta-ginepro")
    tid = "bk" + "d" * 20
    assert _upload(admin, enc.read_bytes(), tid).status_code == 200
    r = admin.post("/api/admin/backup/open", {"id": tid, "file_password": "vetro-lampo-trenta-ginepro"})
    assert r.status_code == 422 and "chiave delle sonde" in r.json()["detail"]
