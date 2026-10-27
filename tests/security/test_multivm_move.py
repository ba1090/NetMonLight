"""Spostamento di un utente tra due VM dal pannello del gateway: il file che passa per l'orchestratore
è cifrato con una password casuale interna, e alla fine l'utente vive sulla VM di arrivo."""
import json
import secrets
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conftest import admin_login_full, netmon  # noqa: E402
from live import PASSWORD, LiveServer  # noqa: E402


@pytest.fixture(scope="module")
def cluster():
    keys = {"vm1": secrets.token_urlsafe(24), "vm2": secrets.token_urlsafe(24)}
    vms = {n: LiveServer(env={"VM_ID": n, "GATEWAY_SECRET": keys[n], "TRUSTED_PROXIES": "127.0.0.1"}) for n in keys}
    orch = LiveServer(env={"ROLE": "orchestratore", "GATEWAY_SECRET": secrets.token_urlsafe(24)})
    (orch.data / "vms.json").write_text(json.dumps({"vms": {n: {"url": v.base, "key": keys[n],
                                                                "public": f"https://{n}.example.test"}
                                                            for n, v in vms.items()}, "tokens": {}}))
    started = []
    try:
        for s in (*vms.values(), orch):
            s.start()
            started.append(s)
        yield {"orch": orch, "vms": vms}
    finally:
        for s in started:
            s.stop()


def test_move_user_between_vms(cluster):
    vm1, vm2, orch = cluster["vms"]["vm1"], cluster["vms"]["vm2"], cluster["orch"]
    db1 = vm1.authdb()
    email = f"sposta-{secrets.token_hex(3)}@example.test"
    r = httpx.post(vm1.base + "/api/auth/register", json={"token": db1.create_invite("prova", email=email),
                                                           "email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    cookie = r.cookies.get("netmon_session")
    with db1._conn() as c:
        uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    db1.set_limits(uid, 5, 5, 50, "personalizzato")
    r = httpx.post(vm1.base + "/api/probes/new", json={"name": "s"}, cookies={"netmon_session": cookie})
    key, token = r.json()["key"], r.json()["token"]
    assert httpx.post(vm1.base + "/api/report", json={"probe": key, "devices": {"d": True}},
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200

    login, temp = f"admin-{secrets.token_hex(3)}@example.test", "Provvisoria-" + secrets.token_hex(6)
    orch.authdb().create_admin(login, temp, "Admin di prova")
    with httpx.Client(base_url=orch.base, timeout=60) as client:
        adm, _ = admin_login_full(client, login, temp)
        r = adm.post("/api/admin/move", {"id": uid, "vm": "vm1", "to": "vm2", "password": adm.password})
        assert r.status_code == 200, r.text
        tid, j = r.json()["id"], {}
        for _ in range(600):
            j = adm.get(f"/api/admin/transfer/job?id={tid}").json()
            if j["state"] != "running":
                break
            time.sleep(0.2)
        assert j["state"] == "done", j
    assert vm2.authdb().user_exists(email)
    assert not db1.user_exists(email)
    # nessun file in chiaro rimasto sulle VM o sull'orchestratore
    for s in (vm1, vm2, orch):
        left = [p.name for p in (s.data / "upload" / "trasferimenti").glob("**/*") if p.is_file()]
        assert not [n for n in left if n.endswith(".zip") or n == "zip"], left
