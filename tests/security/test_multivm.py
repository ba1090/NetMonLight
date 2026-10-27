"""Più VM dietro il gateway: gateway + orchestratore + vm1 + vm2, ognuno nel suo processo.

Un utente o una sonda di una VM non deve poter leggere o scrivere su un'altra VM cambiando il nome
della VM scritto in testa al token o al cookie, e nessuno da fuori deve poter usare le intestazioni
interne (X-Netmon-Gateway, X-Netmon-Admin…) che il gateway e l'orchestratore usano tra loro.
"""
import json
import secrets
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from live import PASSWORD, ROOT, LiveServer  # noqa: E402


@pytest.fixture(scope="module")
def cluster():
    keys = {"vm1": secrets.token_urlsafe(24), "vm2": secrets.token_urlsafe(24)}
    orch_secret = secrets.token_urlsafe(24)
    vms = {name: LiveServer(env={"VM_ID": name, "GATEWAY_SECRET": keys[name], "TRUSTED_PROXIES": "127.0.0.1"})
           for name in keys}
    orch = LiveServer(env={"ROLE": "orchestratore", "GATEWAY_SECRET": orch_secret})
    (orch.data / "vms.json").write_text(json.dumps({"vms": {n: {"url": v.base, "key": keys[n], "public": ""}
                                                            for n, v in vms.items()}, "tokens": {}}))
    gw = LiveServer(app="gateway:app", cwd=ROOT / "gateway", health="/gateway/health",
                    env={"ORCHESTRATOR": orch.base, "GATEWAY_SECRET": orch_secret, "DEFAULT_VM": "vm1"})
    started = []
    try:
        for s in (*vms.values(), orch, gw):
            s.start()
            started.append(s)
        # un account con una sonda su ciascuna VM, creato attraverso il gateway come farebbe l'utente
        users = {}
        for name, vm in vms.items():
            db = vm.authdb()
            email = f"{name}-{secrets.token_hex(3)}@example.test"
            code = db.create_invite("prova", email=email)
            # il codice non porta il nome della VM (creato da qui): si registra direttamente sulla VM
            r = httpx.post(vm.base + "/api/auth/register", json={"token": code, "email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            cookie = r.cookies.get("netmon_session")
            assert cookie.startswith(name + ".")
            with db._conn() as c:
                uid = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
            db.set_limits(uid, 5, 5, 50, "personalizzato")
            r = httpx.post(gw.base + "/api/probes/new", json={"name": "s"}, cookies={"netmon_session": cookie})
            assert r.status_code == 200, r.text
            key, token = r.json()["key"], r.json()["token"]
            assert token.startswith(f"sonda_{name}.")
            r = httpx.post(gw.base + "/api/report", json={"probe": key, "devices": {"d": True}},
                           headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text
            users[name] = {"email": email, "cookie": cookie, "key": key, "token": token}
        yield {"gw": gw, "orch": orch, "vms": vms, "keys": keys, "orch_secret": orch_secret, "users": users}
    finally:
        for s in started:
            s.stop()


def test_gateway_routes_to_right_vm(cluster):
    gw, u = cluster["gw"], cluster["users"]
    for name in ("vm1", "vm2"):
        r = httpx.get(gw.base + "/api/status", cookies={"netmon_session": u[name]["cookie"]})
        assert r.status_code == 200
        assert [p["name"] for p in r.json()["probes"]] == [u[name]["key"]]
        assert r.json()["server"]["name"] == name


def test_probe_token_relabelled_to_other_vm_refused(cluster):
    gw, u = cluster["gw"], cluster["users"]
    forged = "sonda_vm2." + u["vm1"]["token"].split(".", 1)[1]
    r = httpx.post(gw.base + "/api/report", json={"probe": u["vm1"]["key"], "devices": {"x": True}},
                   headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_session_relabelled_to_other_vm_refused(cluster):
    gw, u = cluster["gw"], cluster["users"]
    forged = "vm2." + u["vm1"]["cookie"].split(".", 1)[1]
    r = httpx.get(gw.base + "/api/status", cookies={"netmon_session": forged})
    assert r.status_code == 401


def test_cross_vm_probe_key_not_reachable(cluster):
    gw, u = cluster["gw"], cluster["users"]
    r = httpx.get(gw.base + f"/api/history?probe={u['vm2']['key']}&device=d",
                  cookies={"netmon_session": u["vm1"]["cookie"]})
    assert r.status_code == 404


def test_internal_routes_not_exposed_by_gateway(cluster):
    gw, keys = cluster["gw"], cluster["keys"]
    for path in ("/internal/vms", "/internal/status", "/internal/has-user?email=a@b.it", "//internal/vms",
                 "/%69nternal/vms"):
        for h in ({}, {"X-Netmon-Gateway": cluster["orch_secret"]}, {"X-Netmon-Gateway": keys["vm1"]}):
            r = httpx.get(gw.base + path, headers=h)
            assert r.status_code in (404, 503) or (r.status_code < 300 and "vms" not in r.text), (path, r.status_code)
            assert cluster["orch_secret"] not in r.text and keys["vm1"] not in r.text


def test_client_cannot_pose_as_orchestrator(cluster):
    """Intestazioni interne aggiunte dal client: il gateway le toglie, la VM non ci crede."""
    gw, keys, u = cluster["gw"], cluster["keys"], cluster["users"]
    h = {"X-Netmon-Gateway": keys["vm1"], "X-Netmon-Admin": "finto@example.test", "X-Netmon-Pw-Checked": "1",
         "Authorization": f"Bearer {u['vm1']['token']}"}
    # attraverso il gateway, verso una rotta di amministrazione della VM (instradata con il token della sonda)
    r = httpx.post(gw.base + "/api/admin/users/block", json={"id": 1, "password": "x"}, headers=h)
    assert r.status_code in (401, 403, 404, 422)
    r = httpx.get(gw.base + "/api/admin/overview", headers=h)
    assert r.status_code in (401, 403)


def test_vm_rejects_wrong_gateway_key_even_from_trusted_ip(cluster):
    """Sulla VM, l'azione inoltrata dall'orchestratore vale solo con la chiave giusta."""
    vm1, keys = cluster["vms"]["vm1"], cluster["keys"]
    for key in ("", "sbagliata", keys["vm2"], cluster["orch_secret"]):
        r = httpx.get(vm1.base + "/api/admin/overview",
                      headers={"X-Netmon-Gateway": key, "X-Netmon-Admin": "finto@example.test"})
        assert r.status_code == 401, key
    # con la chiave giusta (l'orchestratore vero) la VM risponde: controllo che la prova abbia senso
    r = httpx.get(vm1.base + "/api/admin/overview",
                  headers={"X-Netmon-Gateway": keys["vm1"], "X-Netmon-Admin": "orch@example.test"})
    assert r.status_code == 200


def test_orchestrator_has_no_users(cluster):
    orch = cluster["orch"]
    r = httpx.post(orch.base + "/api/auth/register", json={"token": orch.api_token, "email": "x@example.test",
                                                            "password": PASSWORD})
    assert r.status_code == 404


def test_vm_notice_requires_vm_key(cluster):
    orch, keys = cluster["orch"], cluster["keys"]
    body = {"vm": "vm1", "key": "sbagliata", "title": "[ALERT] finto", "kind": "sicurezza"}
    assert httpx.post(orch.base + "/api/vm/notice", json=body).status_code == 404
    body["key"] = keys["vm2"]
    assert httpx.post(orch.base + "/api/vm/notice", json=body).status_code == 404


def test_access_page_rate_limited(cluster):
    gw = cluster["gw"]
    codes = [httpx.post(gw.base + "/gateway/accedi", json={"email": f"x{i}@example.test"},
                        headers={"X-Forwarded-For": "198.51.100.9"}).status_code for i in range(25)]
    assert 429 in codes
