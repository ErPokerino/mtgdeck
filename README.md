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

Il database predefinito è `data/mtgdeck.db`, nel server dell'app, **non nel cloud del browser**. Conserva mazzi, guide, revisioni e impostazioni (compresa la chiave provider inserita nella UI). Non pubblicarlo. Per un backup coerente usa SQLite `.backup` oppure arresta l'app prima di copiare il database. Puoi configurare `DATABASE_URL`; per PostgreSQL occorre installare il driver appropriato. Il deployment multiutente e l'autenticazione non sono implementati: il servizio è progettato come workbench personale.

## Legalità e qualità delle analisi

La validazione usa `legalities` di Scryfall per identità Oracle: banlist, rotazione, limite combinato delle copie e relative eccezioni. La stampa mostrata non determina da sola la legalità. In Constructed il minimo è **60 main** e il massimo **15 side**, companion incluso. Il generatore propone, per scelta, **60+15**. Le restrizioni specifiche dei companion richiedono una verifica manuale e impediscono la certificazione automatica della lista.

Il catalogo viene aggiornato senza cancellare identità collegate ai mazzi. Le analisi AI sono bloccate se manca una sincronizzazione documentata o ha più di 48 ore. Questa soglia limita i dati obsoleti ma non certifica l'assenza di un annuncio di ban più recente: prima del torneo consulta le regole Wizards. La lista dei set è indicativa, derivata dalle stampe rappresentative del catalogo Oracle; il controllo effettivo è sempre sulla carta.

Le skill motivano engine, densità, manabase, clock, interazioni Oracle, esclusioni, piani alternativi e slot post-side. Prezzo, rarità o tipo Lesson non sono filtri di legalità. Le probabilità di vedere almeno una copia in 7/9/10 carte sono calcolate con distribuzione ipergeometrica; non sono probabilità di poter lanciare la carta. Le liste invalide vengono riproposte all'AI o rifiutate, senza riempire automaticamente i buchi. Mani di esempio e sidate vengono verificate per copie disponibili e bilanciamento IN/OUT.

Le guide passano un ciclo **bozza → controlli deterministici → revisione Oracle → correzioni → nuova verifica**, prima di qualsiasi salvataggio. Per gli errori testuali l’editor applica modifiche mirate con riscontro esatto del testo originale; gli errori strutturali richiedono una nuova versione completa. Sono richiesti tutti i matchup dello snapshot forniti nel prompt, senza duplicati e con motivazione della stima Bo3. Il numero massimo di revisioni è configurabile in `deck_guide.maxValidationRetries`. Solo la versione che supera i controlli viene archiviata, con data e numero di revisioni. Un tentativo fallito lascia intatte le guide precedenti e non le presenta come risultato nuovo. La revisione AI riduce gli errori, ma non è una certificazione formale delle regole.

**Winrate teorico ponderato**: `somma(quota archetipi × WR teorico Bo3) / somma(quote coperte)`. La guida mostra copertura, righe, fonte e data. I matchup mancanti restano ignoti; quote incoerenti impediscono il calcolo. Si tratta di stime AI, non risultati empirici, intervalli statistici o promesse di rendimento. Anche la matrice metagame è esplicitamente euristica, senza campioni inventati. Le guide storiche eventualmente già salvate vengono preservate; non è possibile ricostruire dati che non erano stati registrati.

Ogni nuova guida include `meta_estimate`, anche quando il calcolo non è possibile: `status` e `reason` distinguono snapshot assente, quote incoerenti e matchup non corrispondenti. Il messaggio delle versioni storiche senza dati non viene usato per questi casi.

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
