# Aetherdeck

Workbench locale per preparare mazzi MTG competitivi in Standard, Pioneer e Modern: catalogo Scryfall, analisi del metagame, builder, guide AI e playtest solitario.

## Avvio

Richiede Python 3.11+ e Node.js 22+.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
.venv/Scripts/python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8090
```

Apri http://127.0.0.1:8090. Per lo sviluppo esegui anche `npm run dev` nella cartella `frontend` e apri http://127.0.0.1:5173; Vite inoltra le API alla porta **8090**.

Al primo avvio vengono creati database e catalogo. La sincronizzazione iniziale richiede una connessione Internet e può impiegare alcuni minuti. Configura Gemini o Vertex AI nelle Impostazioni; i modelli e i ruoli si configurano in `config/ai-models.json`. I due selettori strategici mostrano gli stessi due modelli e condividono la preferenza; Flash Lite rimane riservato alle riparazioni. Un errore di capacità/quota non cambia silenziosamente il modello.

## Mazzi, bozze e guide

- **Deck Builder**: una nuova lista è una bozza nel browser. “Salva” la memorizza nel server e conserva una versione. La bozza viene recuperata dopo un reload e rimane disponibile quando cambi sezione.
- **Generazione AI e importazione**: il mazzo viene salvato automaticamente. Le carte non riconosciute bloccano l'importazione, evitando liste parziali.
- **Mazzi e guide → Mazzi attivi**: cerca, apri, duplica, avvia il playtest, consulta le versioni o archivia una lista. Archiviare la toglie dai selettori, mantenendo dati e storico.
- **Archiviati**: ripristina una lista oppure eliminala definitivamente dopo conferma.
- **Guide salvate**: ogni generazione conserva una versione indipendente con la lista analizzata, modello, data e contesto. Anche le liste incollate hanno una guida archiviata. Puoi leggere ed esportare ogni versione in PDF con indice navigabile, lista, piani e tabelle di sidata.
- Modificare le carte o il formato rende la guida precedente uno storico; non la presenta come aggiornata. Eliminare un mazzo elimina le sue revisioni, ma mantiene le guide e le rispettive liste.

L’export PDF è illustrato anche per le versioni già salvate: lista testuale e griglia completa main/side con quantità, immagini in tutte le mani di esempio e in ogni scheda carta. Le schede delle vere carte a doppia faccia mostrano anche il retro disponibile. Il formato usa copertina con riepilogo, indice navigabile di soli capitoli, intestazioni di sezione e tabelle che continuano correttamente su più pagine.

Le immagini ufficiali in risoluzione normale vengono scaricate da Scryfall e conservate in `data/cache/pdf-card-images`; i download falliti non vengono memorizzati e saranno riprovati all’export successivo. In assenza di un’immagine il riquadro riporta esplicitamente il nome della carta. Riscaricare un PDF applica il nuovo stile alla guida esistente, senza nuove chiamate AI.

Il database predefinito è `data/mtgdeck.db`, nel server dell'app, **non nel cloud del browser**. Conserva mazzi, guide, revisioni e impostazioni (compresa la chiave provider inserita nella UI). Non pubblicarlo. Per un backup coerente usa SQLite `.backup` oppure arresta l'app prima di copiare il database. Puoi configurare `DATABASE_URL`; per PostgreSQL occorre installare il driver appropriato. Il deployment multiutente e l'autenticazione non sono implementati: il servizio è progettato come workbench personale.

## Legalità e qualità delle analisi

La validazione usa `legalities` di Scryfall per identità Oracle: banlist, rotazione, limite combinato delle copie e relative eccezioni. La stampa mostrata non determina da sola la legalità. In Constructed il minimo è **60 main** e il massimo **15 side**, companion incluso. Il generatore propone, per scelta, **60+15**. Le restrizioni specifiche dei companion richiedono una verifica manuale e impediscono la certificazione automatica della lista.

Il catalogo viene aggiornato senza cancellare identità collegate ai mazzi. Le analisi AI sono bloccate se manca una sincronizzazione documentata o ha più di 48 ore. Questa soglia limita i dati obsoleti ma non certifica l'assenza di un annuncio di ban più recente: prima del torneo consulta le regole Wizards. La lista dei set è indicativa, derivata dalle stampe rappresentative del catalogo Oracle; il controllo effettivo è sempre sulla carta.

Le skill motivano engine, densità, manabase, clock, interazioni Oracle, esclusioni, piani alternativi e slot post-side. Prezzo, rarità o tipo Lesson non sono filtri di legalità. Le probabilità di vedere almeno una copia in 7/9/10 carte sono calcolate con distribuzione ipergeometrica; non sono probabilità di poter lanciare la carta. Le liste invalide vengono riproposte all'AI o rifiutate, senza riempire automaticamente i buchi. Mani di esempio e sidate vengono verificate per copie disponibili e bilanciamento IN/OUT.

Le guide passano **bozza → controlli deterministici → revisione con correzioni → verifica dei passaggi modificati**, prima della pubblicazione. Il revisore restituisce direttamente patch con riscontro esatto e fonte, anche per errori strutturali: non viene rigenerato l’intero primer. Sono richiesti tutti i matchup forniti, senza duplicati e con stima Bo3 motivata. Se la sidata play/draw coincide con il piano base viene dichiarato esplicitamente, evitando tabelle duplicate; se differisce, gli array devono essere completi e bilanciati.

Ogni tentativo ha un **budget di 5 minuti**, timeout per chiamata e nessun retry HTTP automatico. Massimo tre passaggi di revisione/verifica (riducibili con `deck_guide.maxValidationRetries`, mai oltre due correzioni). Il primer privilegia decisioni concrete e testo conciso; scrittura e controlli usano ragionamento medio con una revisione indipendente, evidenza Oracle e verifiche deterministiche. Solo la versione che supera i controlli viene archiviata, con data e numero di revisioni. La revisione AI riduce gli errori, ma non è una certificazione formale delle regole.

La generazione avviene nel server come lavoro persistente (`guide_jobs`): AI Studio mostra fase reale, tempo trascorso e annullamento. Puoi cambiare sezione o ricaricare la pagina. Una bozza completa viene conservata prima della revisione; dopo un errore o riavvio puoi riprendere soltanto i controlli, senza riscriverla. Una firma della lista e del modello impedisce di pubblicare una guida su una lista modificata nel frattempo. L’annullamento impedisce la pubblicazione; una chiamata al provider già in corso può terminare prima dell’arresto del lavoro. I tentativi duplicati vengono riuniti; sono ammesse al massimo due analisi contemporanee.

Le bozze rifiutate dal flusso precedente sono recuperabili se la lista è rimasta invariata, e non vengono proposte quando esiste una guida successiva già approvata. Le bozze non approvate restano separate da **Guide salvate**.

**Winrate teorico ponderato**: `somma(quota archetipi × WR teorico Bo3) / somma(quote coperte)`. La guida mostra copertura, righe, fonte e data. I matchup mancanti restano ignoti; quote incoerenti impediscono il calcolo. Si tratta di stime AI, non risultati empirici, intervalli statistici o promesse di rendimento. Anche la matrice metagame è esplicitamente euristica, senza campioni inventati. Le guide storiche eventualmente già salvate vengono preservate; non è possibile ricostruire dati che non erano stati registrati.

Ogni nuova guida include `meta_estimate`, anche quando il calcolo non è possibile: `status` e `reason` distinguono snapshot assente, quote incoerenti e matchup non corrispondenti. Il messaggio delle versioni storiche senza dati non viene usato per questi casi.

Le fasi della generazione vengono registrate nei log del backend. Un tentativo fallito conserva una diagnostica e l’ultima bozza in `ai_runs`, separatamente dalle guide pubblicate, per poter analizzare gli errori senza ricreare il testo. Le eccezioni del provider vengono registrate solo per tipo, senza contenuti della richiesta o credenziali.

## Percorso iniziale

Al primo accesso viene proposto un percorso interattivo di sei tappe nelle sezioni reali: formato e catalogo, lista, meta, AI, playtest e archivio. Non crea dati né avvia analisi. Si può saltare, chiudere con Esc e riaprire da **Aiuto**. La preferenza è locale al browser (`aetherdeck.onboarding.v1`); il percorso mantiene la tappa quando apri le impostazioni e si adatta al telefono.

## Playtest

Il playtest è un sandbox solitario manuale, non un motore di regole né un avversario AI. Il campo mostra due corsie distinte: creature e altri permanenti sopra, terre e fonti sotto; la mano rimane separata. Le corsie scorrono orizzontalmente quando contengono molte carte. La prima azione conferma automaticamente la mano; dopo un London mulligan devi prima selezionare il numero corretto di carte da mettere in fondo. Puoi giocare, tappare, spostare, pescare, fare scry/surveil, cambiare vite, segnalini, mescolare e annullare un'azione.

Le carte sono ingrandibili e hanno azioni esplicite. “Azioni” apre immagine e testo leggibili, facce e pedine. Transform/MDFC si possono girare; split, avventure e Room non vengono erroneamente trattate come carte con retro. Fuori dal campo le carte tornano al fronte e perdono i segnalini. Le pedine ufficiali sono risolte su richiesta tramite le relazioni Scryfall; in assenza di connessione puoi creare una pedina personalizzata. Le pedine che lasciano il campo cessano di esistere. Le modifiche al playtest non cambiano la lista salvata. La configurazione post-side viene applicata solo avviando la nuova partita; puoi annullarla.

## Verifiche

```powershell
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
.venv/Scripts/python.exe -m pytest backend/tests -q
cd frontend
npm run build
npx playwright install chromium
```

I test browser usano un database separato con quattro carte e snapshot offline. Da root:

```powershell
.venv/Scripts/python.exe scripts/seed_qa.py
$env:DATABASE_URL="sqlite:///$((Get-Location).Path.Replace('\','/'))/tmp/qa/fixture.db"
$env:ENABLE_SCHEDULER="false"
.venv/Scripts/python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8090
```

In un altro terminale avvia Vite; poi esegui `npm run test:e2e` in `frontend`. Non puntare i test al database personale. Le chiamate Gemini sono sostituite da provider controllati nei test: qualità strategica e disponibilità del modello richiedono validazione tramite risultati reali di testing. La CI esegue test backend, build e test browser su fixture isolate.
