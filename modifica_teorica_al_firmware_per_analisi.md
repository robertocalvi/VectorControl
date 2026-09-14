# Modifica Teorica al Firmware — Piano per Analisi

> **Documento di ANALISI TEORICA** — nessuna operazione descritta qui è stata eseguita.
> Robot: Anki Vector 1st gen "Vector R1D2" — seriale `00401c2e` — IP `192.168.1.30` — firmware attuale `2.0.1.6086ep` (build Escape Pod firmata, bootloader BLOCCATO).
> Obiettivo finale: eliminare il problema del deep sleep ("robot irraggiungibile sul caricatore") mediante unlock del bootloader, installazione di WireOS e configurazione "dormi ma resta raggiungibile", con fallback di wake via SSH integrato in VectorControl.
> Data: 2026-09-14 — Autore analisi: sessione di pianificazione VectorControl.

---

## 1. Stato attuale e perché serve intervenire sul firmware

### 1.1 Il problema

Sul caricatore Vector entra rapidamente in deep sleep. Sintomi osservati (documentati in `HANDOFF.md`):

- la porta debug `8889` diventa irraggiungibile → `FakeButtonPress` non arriva al robot;
- `request_control()` blocca indefinitamente;
- l'unico workaround attuale è il burst ripetuto di `FakeButtonPress` (`wake_manager.py:75-107`, fino a 7 tentativi × 5 burst), che è cieco e non garantito: se fallisce serve un riavvio fisico.

### 1.2 La vera causa (dalla documentazione del firmware)

Dalla documentazione tecnica del firmware Victor (randym32, "Power management behaviors"):

- Il ciclo del sonno è gestito dal behavior **SleepCycle**, definito in un file JSON del behavior tree:
  `behaviors/victorBehaviorTree/highLevelDelegates/sleeping/sleepCycle.json`
- Gli stati di sonno sono tre: `HeldInPalmSleep`, `LightSleep`, `DeepSleep`. In teoria TUTTI sono risvegliabili da "SDK interaction".
- **Il vero colpevole dell'irraggiungibilità non è il sonno ma il *power save mode***: uno stato inferiore in cui il firmware spegne la camera e riduce CPU/Wi-Fi. È questo throttling che fa morire la porta 8889 e blocca il canale gRPC.

Conclusione: il fix corretto NON è "mai dormire" (il sonno protegge schermo, temperatura e batteria) ma **"dormire restando raggiungibile"** — impedire che il power save spenga la rete, e avere comunque una via di wake garantita (SSH) se il gateway dorme.

### 1.3 Perché serve l'unlock

Con il firmware attuale (`ep`, firmato, bootloader bloccato) NESSUNA delle modifiche necessarie è possibile: niente SSH, niente accesso al filesystem, niente console vars persistenti. Il bootloader (`ABOOT`) accetta solo OTA firmate. L'unlock sostituisce ABOOT/recovery/recoveryfs con versioni che accettano firmware di sviluppo → da lì si installa WireOS (firmware open source mantenuto dalla community, con SSH root).

---

## 2. Architettura della soluzione

```
FASE 0          FASE 1        FASE 2         FASE 3            FASE 4              FASE 5
Backup    →     Unlock   →    WireOS    →    Re-auth      →    Fix deep sleep  →   Integrazione
& baseline      bootloader    + SSH          Wire-Pod          (config-level)      VectorControl
                                                                                   + regressione
```

Ogni fase termina con un **gate di verifica**: la fase successiva non parte se il gate non passa. Decisioni già prese in sede di pianificazione:

| Decisione | Scelta |
|---|---|
| Profondità fix deep sleep | **Config-level + fallback SSH** (niente ricompilazione di wire-os-victor) |
| FakeButtonPress attuale | Mantenuto come primo tentativo; SSH diventa il fallback garantito |
| Variante firmware | WireOS ultima dev OTA (`http://ota.pvic.xyz/vic/latest/dev.ota`) |
| Verifica finale | Re-run completo di `tools/stress_test.py` (dettaglio in §9) |

---

## 3. FASE 0 — Backup e baseline (prima di toccare qualsiasi cosa)

Asset da raccogliere e salvare in una cartella di backup datata (es. `~/AnkiVector/backup-pre-unlock-YYYYMMDD/`):

1. `~/.anki_vector/sdk_config.ini` — contiene GUID `v9S2PN3+9RcUJ6fdtCt7kA==`, cert, target. **Dopo la re-auth il GUID cambierà**: questo file è la fotografia dello stato pre-operazione.
2. `~/Library/Application Support/wire-pod/wire-pod-conf.json` — configurazione Wire-Pod.
3. Output attuale di `GET /api/status` (firmware, batteria) e `GET /api/wirepod` — baseline documentale.
4. Versione firmware attuale annotata: `2.0.1.6086ep`.
5. Screenshot/copia della pagina Bot Settings di Wire-Pod (`http://192.168.1.3:8080`).
6. Git: repo VectorControl committato e pushato (nessuna modifica pendente).

**Gate FASE 0:** tutti i 6 asset esistono nella cartella di backup.

---

## 4. FASE 1 — Unlock del bootloader (Unlock-Prod.ota)

### 4.1 Procedura (verificata su unlock-prod.froggitti.net e ankibots.wiki/Unlocking_Vector)

1. **Carica completa** del robot. Robot **SUL CARICATORE per l'INTERO processo**.
2. Blocco fisico (libro/peso) davanti al robot perché non possa scendere dal caricatore.
3. Recovery mode: tieni premuto il pulsante posteriore ~15 secondi finché le 2 luci posteriori diventano **blu scuro** (il display mostrerà `anki.com/v` o simile).
4. Da **Chrome** (serve Web Bluetooth — non Safari): `https://websetup.froggitti.net`.
5. Seleziona lo stack **Utility**.
6. "PAIR WITH VECTOR" (doppio click sul pulsante del robot se non si connette; lascia "auto flow setup" attivo).
7. Connetti il robot al Wi-Fi (rete 2.4 GHz stabile).
8. Seleziona **`Unlock-Prod.ota`** e avvia.
9. Attendi il riavvio: **~7 minuti**. Al boot il robot esegue `ankiinit.sh` che riscrive le partizioni `aboot`, `recovery`, `recoveryfs`.

### 4.2 Rischio critico e mitigazioni

⚠️ **La finestra dei ~7 minuti di flash è l'UNICO momento con rischio di brick permanente**: viene riscritto il software di recovery stesso, quindi un'interruzione (batteria, robot che scende dal caricatore, crash di rete durante il download) può lasciare il robot non avviabile.

| Mitigazione | Dettaglio |
|---|---|
| Carica al 100% | Prima di iniziare |
| Sul caricatore sempre | + blocco fisico davanti |
| Wi-Fi 2.4 GHz stabile | Router vicino; niente download paralleli pesanti in casa |
| Wire-Pod NON richiesto | L'unlock passa da froggitti, non da Wire-Pod; nessuna interferenza |
| Dry-run preventivo | Familiarizzare con recovery mode ed entrata/uscita PRIMA del giorno dell'operazione |
| Nessuna fretta | Non toccare il robot finché non mostra di nuovo una schermata di setup |

Nota di contesto (manuale OSKR di DDL): le OTA normali POST-unlock sono sicure — in caso di errore il robot ricade sulla recovery. Il pericolo esiste solo mentre si riscrive la recovery stessa, cioè in questa fase.

### 4.3 Reversibilità

**L'unlock è permanente** (ABOOT sostituito). Non è un problema funzionale: il robot continua a funzionare normalmente; da sbloccato può installare sia firmware dev sia build production-like. Ma non tornerà mai "sigillato di fabbrica".

**Gate FASE 1:** il robot si riavvia, mostra la schermata di setup/occhi, ed entra in recovery mode a comando. Da recovery, lo stack Custom Firmware su websetup mostra le opzioni dev (prova che il bootloader accetta firmware non-prod).

---

## 5. FASE 2 — Installazione WireOS + verifica SSH

### 5.1 Installazione (os-vector/wire-os)

1. Robot sul caricatore, di nuovo in recovery mode (15s pulsante → luci blu).
2. `websetup.froggitti.net` → stack **Custom Firmware** → connetti → scegli **WireOS** → avvia il flusso.
   - Alternativa equivalente dal terminale BLE della recovery: `ota-start http://ota.pvic.xyz/vic/latest/dev.ota`
3. Attendi installazione e riavvio (boot WireOS: logo arcobaleno + animazione).

Questa installazione è nella categoria "sicura": se fallisce, il robot ricade in recovery e si riprova.

### 5.2 Verifica SSH

- Chiave SSH root globale di WireOS: file `ssh_root_key` nel repo `kercre123/unlocking-vector` (da scaricare in FASE 0 e salvare in `~/.ssh/vector_wireos_key`, permessi `600`).
- Test teorico: `ssh -i ~/.ssh/vector_wireos_key root@192.168.1.30` → shell root sul robot.
- IP del robot ricavabile dalla schermata CCIS: robot sul caricatore → doppio click pulsante → alza/abbassa il sollevatore.

**Gate FASE 2:** (a) WireOS boota e il robot è vivo; (b) login SSH root riuscito; (c) `http://192.168.1.30:8889/consolevars` risponde con la UI delle console vars (su WireOS è una pagina web completa).

---

## 6. FASE 3 — Re-autenticazione Wire-Pod + regressione VectorControl

Dopo il cambio firmware il robot NON è più autenticato con Wire-Pod.

1. Wire-Pod attivo sul Mac (`192.168.1.3:8080`).
2. Interfaccia Wire-Pod → **Bot Setup** → sezione **"Set up OSKR/dev bot"** (NON il flusso production: quello chiede il firmware ep; il bot ora è unlocked/dev — fonte: wiki wire-pod "Installation").
3. Completa l'autenticazione → Wire-Pod **rigenera la entry in `sdk_config.ini`** con un nuovo GUID. Il Python SDK (`wirepod-vector-sdk`) continua a funzionare senza modifiche al codice.
4. Verifica che il bot compaia in "Bot Settings" di Wire-Pod.

**Gate FASE 3 (regressione base VectorControl):**
- `.venv/bin/python -m web.server` parte senza errori;
- dashboard su `http://127.0.0.1:4001`: WAKE UP VECTOR funziona, camera live attiva, guida WASD risponde, TTS parla;
- `GET /api/status` → `connected: true`, firmware riportato = versione WireOS.

Se questo gate fallisce in modo non recuperabile: rollback = reflash di una OTA alternativa da recovery (il robot resta operabile; vedi §10).

---

## 7. FASE 4 — Fix deep sleep "dormi ma resta raggiungibile" (config-level)

Ordine di attacco, dal meno al più invasivo. Ogni passo ha verifica propria; ci si ferma al primo livello che rende il robot stabilmente raggiungibile.

### 7.1 Livello 1 — Wi-Fi power save OFF

Il sospetto principale per la morte della porta 8889 è il power saving Wi-Fi durante il power save mode.

- Via SSH, disattivare il power save dell'interfaccia wireless (comando teorico, da verificare sul kernel del robot: `iw dev wlan0 set power_save off` oppure l'equivalente `iwconfig wlan0 power off`).
- Persistenza: unità systemd o script di init in `/data` che riapplica il setting a ogni boot (i file su `/data` sopravvivono agli aggiornamenti; ogni file modificato on-robot va prima copiato in `.bak`).

### 7.2 Livello 2 — Console vars del power save

- Esplorare `http://192.168.1.30:8889/consolevars` (UI web su WireOS) alla ricerca delle variabili del power management (la documentazione conferma l'esistenza di behavior `PowerSaveTest`/`PowerSaveStressTest` e di console vars per categoria).
- Obiettivo: alzare le soglie o disabilitare l'ingresso in power save profondo QUANDO il robot è sul caricatore, lasciando intatto il sonno "cosmetico" (occhi chiusi, schermo spento).

### 7.3 Livello 3 — Tweak di `sleepCycle.json`

- Solo se i livelli 1-2 non bastano: via SSH, editare il decision tree del behavior SleepCycle (`behaviors/victorBehaviorTree/highLevelDelegates/sleeping/sleepCycle.json`) per modificare le condizioni di ingresso nel deep sleep sul caricatore. Backup `.bak` obbligatorio, poi restart dei servizi anki (`systemctl restart anki-robot.target`).

### 7.4 Fallback garantito — wake via SSH

Indipendentemente dai livelli sopra: con SSH root il wake è sempre possibile anche a robot "addormentato", perché sshd resta attivo a livello OS (non dipende dal behavior system). Vie di wake teoriche via SSH, in ordine di preferenza:

1. impostare la console var `FakeButtonPressType=singlePressDetected` da locale (`curl http://127.0.0.1:8889/consolevarset?...` eseguito SUL robot via SSH — bypassa il problema del Wi-Fi throttled perché la sessione SSH tiene sveglio il link);
2. restart mirato dei servizi (`systemctl restart anki-robot.target`) come ultima risorsa.

**Gate FASE 4 (il test che oggi fallisce):** robot sul caricatore, lasciato indisturbato 30+ minuti fino al sonno profondo; poi (a) la porta 8889 risponde ancora, (b) il wake da dashboard funziona al primo colpo, (c) ripetuto 3 volte con esito 3/3.

---

## 8. FASE 5 — Integrazione in VectorControl

Modifiche al codice (uniche modifiche software del piano):

### 8.1 `vectorcontrol/ssh_wake.py` (nuovo modulo)

- Funzione `ssh_wake(robot_ip, key_path) -> bool`: esegue via SSH il comando di wake (§7.4), timeout breve, nessuna dipendenza nuova pesante (subprocess + `ssh -i` di sistema, oppure `paramiko` se già disponibile).

### 8.2 `vectorcontrol/wake_manager.py`

- In `wake_vector` (`wake_manager.py:75-107`): dopo il fallimento dei burst HTTP su 8889 di un tentativo, provare `ssh_wake()` prima del tentativo successivo. FakeButtonPress HTTP resta il primo colpo (più rapido); SSH è il fallback garantito.
- Config chiave SSH: percorso letto da variabile d'ambiente o costante (`~/.ssh/vector_wireos_key`).

### 8.3 `vectorcontrol/vector_manager.py`

- `_send_wake_bursts` (`vector_manager.py:151-164`): eliminare la duplicazione (IP hardcoded `192.168.1.30`) delegando a `wake_manager`, e aggiungere lo stesso fallback SSH nel percorso di force-reconnect.

### 8.4 Documentazione

- `HANDOFF.md`: nuova sezione post-WireOS — nuova versione firmware, GUID rigenerato, procedura SSH, nuove procedure di recovery, stato del bug `play_animation` (da riverificare su WireOS: potrebbe essere sparito, verifica opportunistica, non obiettivo del piano).

**Gate FASE 5:** re-run completo della stress suite (§9) con esito ≥ pari al baseline (48/49), più il nuovo scenario deep-sleep (§9.4) superato.

---

## 9. Verifica finale — Re-run completo di `tools/stress_test.py` (descrizione teorica dettagliata)

### 9.1 Prerequisiti del run

1. Wire-Pod attivo (`GET http://192.168.1.3:8080/api-sdk/get_sdk_info` → 200; il server lo lancia comunque da solo: `web/server.py:74`, `ensure_wirepod`).
2. Server attivo: `cd /Users/roberto/AnkiVector/VectorControl && .venv/bin/python -m web.server` (porta 4001).
3. Robot acceso, connesso alla rete, su WireOS, autenticato con Wire-Pod.
4. Playwright Chromium installato nel venv (già presente: la suite lo usa oggi).
5. Robot preferibilmente NEL deep sleep sul caricatore all'avvio del run — così il TEST 3 (Wake) esercita esattamente il percorso che questo piano corregge.

### 9.2 Comando e semantica

```bash
cd /Users/roberto/AnkiVector/VectorControl
.venv/bin/python tools/stress_test.py
```

- Il main (`stress_test.py:270-303`) esegue 11 gruppi di test in sequenza, accumula i risultati in `RESULTS`, stampa il sommario e **esce con codice 0 solo se zero failure** (`stress_test.py:303`) — quindi l'esito è verificabile da un agente con `echo $?`.
- Pre-check: se il server non risponde su 4001 il run abortisce subito (`stress_test.py:275-278`).
- Durata attesa: ~60-90 secondi (5s camera + 3s telemetria + 17 comandi motore con pause 0.3s + 50 comandi rapidi + 3s attesa UI + 8s go home + wake variabile).

### 9.3 Gli 11 gruppi di test, cosa provano e criteri di pass

| # | Test (righe) | Cosa esercita | Criterio di pass |
|---|---|---|---|
| 1 | API Status (`:35-44`) | `GET /api/status` | 200, presenza `firmware` e `battery_volts` — **il campo firmware ora riporterà la versione WireOS: atteso valore diverso dal baseline, il test resta verde perché controlla solo la presenza** |
| 2 | Vector State (`:47-54`) | `GET /api/vector_state` | 200 con `state` |
| 3 | **Wake (`:57-76`)** | `POST /api/wake` + poll di `has_control` per 20s | **IL test chiave post-fix: con il fallback SSH e il power save corretto deve completare entro 20s partendo dal deep sleep — oggi è lo scenario che fallisce** |
| 4 | Camera WS (`:79-100`) | `ws://…/ws/camera` per 5s | >0 frame, ≥5 FPS, frame 1KB-200KB |
| 5 | Telemetry WS (`:103-125`) | `ws://…/ws/telemetry` per 3s | messaggi con battery/proximity/pose/accel/gyro |
| 6 | Motor APIs (`:128-157`) | 17 comandi drive/head/lift/stop | tutti 200 (baseline: 13-75ms l'uno) |
| 7 | Speed Presets (`:160-175`) | 5 livelli + GET presets | `ok` su tutti, 5 preset |
| 8 | Rapid Commands (`:178-194`) | 50 POST drive a raffica | 50/50 OK (baseline ~24ms avg) |
| 9 | Server Stability (`:197-206`) | status dopo lo stress | ancora `connected` e `has_control` |
| 10 | Playwright UI (`:209-255`) | Chromium headless sulla dashboard | ONLINE visibile, elementi presenti, 0 errori JS, W invia drive. **Nota: il check `#wake-state` (`:225-226`) cerca un elemento che non esiste in `index.html` — è il candidato del "49° test" storicamente rosso; da baseline resta tale (fix opzionale fuori scope)** |
| 11 | Go Home (`:258-267`) | `POST /api/go_home` + 8s | 200 e server vivo dopo |

### 9.4 Estensione post-fix (nuovo scenario, da aggiungere in FASE 5)

Alla suite va aggiunto **il test del deep sleep** (oggi non coperto):

1. precondizione: robot sul caricatore, inattivo ≥30 min (deep sleep raggiunto);
2. assert A: `GET http://192.168.1.30:8889/consolevars` risponde (rete viva nel sonno);
3. assert B: `POST /api/wake` → `has_control` entro 20s (wake garantito);
4. ripetizione ×3 nella stessa sessione, atteso 3/3.

Evidenza del run: output completo salvato (es. `tee stress-run-post-wireos.log`) + exit code.

### 9.5 Criterio complessivo di successo

- Nessuna regressione: tutti i test verdi nel baseline restano verdi (≥48/49);
- TEST 3 (Wake) verde **partendo dal deep sleep** — è la prova che l'obiettivo del piano è raggiunto;
- scenario §9.4 superato 3/3.

---

## 10. Matrice rischi e rollback

| Momento | Rischio | Probabilità | Rollback |
|---|---|---|---|
| FASE 1, flash unlock (~7 min) | **Brick permanente** | Bassa (con mitigazioni §4.2) | NESSUNO — unico punto senza rete di sicurezza |
| FASE 2, flash WireOS | Boot fallito | Bassa | Recovery mode → reflash (safe) |
| FASE 3, re-auth | Bot non autentica | Media (mDNS/`escapepod.local` capriccioso) | Troubleshooting wiki wire-pod (hostname, mDNS, AP isolation); nessun danno |
| FASE 4, tweak on-robot | Comportamento anomalo del robot | Bassa | Ripristino `.bak` via SSH + restart servizi |
| FASE 5, modifiche codice | Regressione VectorControl | Bassa | `git revert`; stress suite come rete |
| Generale | Bug SDK noti cambiano forma su WireOS | Media | La sequenza wake attuale resta nel codice; HANDOFF aggiornato con i nuovi comportamenti osservati |

---

## 11. Cosa questo piano NON fa (fuori scope)

- NON ricompila `wire-os-victor` né builda OTA custom (eventuale piano futuro separato).
- NON corregge il bug `play_animation`/`ListAnimations` (solo verifica opportunistica su WireOS).
- NON aggiunge funzionalità nuove alla dashboard.
- NON modifica Wire-Pod.
- NON crea una modalità "mai dormire": il robot continua a dormire, ma resta raggiungibile.

---

## 12. Fonti

- Procedura unlock: `unlock-prod.froggitti.net`, `ankibots.wiki/Unlocking_Vector`, `websetup.froggitti.net`
- Contesto sicurezza/rischi OTA: `github.com/digital-dream-labs/oskr-owners-manual/doc/unlock.md` e `unlock_checklist.md`
- WireOS: `github.com/os-vector/wire-os`, `os-vector.github.io/vector-docs`, learnwitharobot.com "WireOS on Vector"
- SSH key: `github.com/kercre123/unlocking-vector` (file `ssh_root_key`)
- Wire-Pod bot sbloccati: wiki `kercre123/wire-pod` → Installation → "Authenticate an unlocked bot"; `ankibots.wiki/Wire-pod`
- Power management / SleepCycle: `randym32.github.io/Anki.Vector.Documentation` → "Power management behaviors", "Console variables", "Behavior IDs"
- Codice locale: `vectorcontrol/wake_manager.py`, `vectorcontrol/vector_manager.py`, `web/server.py`, `tools/stress_test.py` (righe citate nel testo)
