# Prove automatiche di netmon

Prove di sicurezza, di isolamento tra account, di salvataggio dei dati e di carico. Girano su un
server vero con i dati in una cartella temporanea: non toccano nessuna installazione e non inviano
email, Telegram o ntfy.

```bash
pip install -r server/requirements.txt pytest hypothesis httpx playwright==1.56.0
python -m pytest -q                 # tutte le prove veloci (circa 3 minuti)
python -m pytest -q -m stress       # prove di carico (decine di minuti; STRESS_SECONDS=… per allungarle)
python tests/stress/stress.py sustained --seconds 7200 --out /tmp/netmon-stress   # prova di ore, con riepilogo
```

| Cartella | Cosa controlla |
|---|---|
| `security/test_access_control.py` | ogni rotta senza credenziali viene rifiutata (elenco generato dalle rotte: una rotta nuova senza controllo fa fallire la prova); sessioni utente e amministratore separate; MFA obbligatoria; logout e cambio password chiudono le sessioni |
| `security/test_isolation.py` | l'utente B non legge né cambia nulla dell'utente A (storico, eventi, sonde, export, backup, token), su ogni API che accetta una sonda; eliminazione dell'account |
| `security/test_input_validation.py` | report ostili delle sonde (NaN, testi al posto dei numeri, caratteri di controllo, campi enormi), SQL injection nella ricerca degli eventi, limiti di corpo e frequenza; fuzzing con hypothesis (`FUZZ_EXAMPLES=…`) |
| `security/test_storage.py` | password scrypt con sale, sessioni/token/codici solo come impronte, cancellazione sicura, permessi dei file (UMask del servizio), niente segreti nei registri, cookie e intestazioni di sicurezza, forza bruta |
| `security/test_xss_browser.py` | Chromium headless: testi avvelenati in ogni campo che arriva dalla rete (nomi, SSID, mesh, ospiti, servizi trovati) non vengono mai eseguiti, né nella pagina utente né nel pannello |
| `security/test_probe.py` | sonda: niente opzioni o comandi nel ping, configurazione dal server ricontrollata, scansione solo della rete di casa, server e sonda d'accordo sugli indirizzi; pagina locale (password, DNS rebinding, CSRF, forza bruta) |
| `security/test_ssrf.py` | gli indirizzi ntfy scelti dagli utenti non portano il server sulla rete interna |
| `security/test_resources.py` | ogni richiesta chiude le sue connessioni al database |
| `test_managed.py` | sonda gestita da un altro sistema (`NETMON_MANAGED_BY`): dice dove fare riavvio, aggiornamenti e reti Wi-Fi invece di consigliare sudo; il server non le manda comandi (pagina, programmati, automatici) e la segna nel pannello |
| `scenarios/test_usecases.py` | dall'account con 0 sonde a quello con 50 sonde, 1000 dispositivi e 10 FRITZ!Box; piani basso/medio/alto |
| `stress/` | carico realistico e prolungato, raffiche di accessi, corpi enormi, ritorno in massa delle sonde, storico di 30 giorni |
