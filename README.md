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

Al primo avvio vengono creati database e catalogo. La sincronizzazione iniziale richiede una connessione Internet e può impiegare alcuni minuti. Configura Gemini o Vertex AI nelle Impostazioni; i modelli e i ruoli si configurano in `config/ai-models.json`. I due selettori strategici mostrano gli stessi due modelli e condividono la preferenza. Le riparazioni di una lista generata usano lo stesso modello della generazione, per non diluire la tesi strategica. Un errore di capacità/quota non cambia silenziosamente il modello.

## Mazzi, bozze e guide

- **Deck Builder**: una nuova lista è una bozza nel browser. “Salva” la memorizza nel server e conserva una versione. La bozza viene recuperata dopo un reload e rimane disponibile quando cambi sezione.
- **Generazione AI e importazione**: il mazzo viene salvato automaticamente. Le carte non riconosciute bloccano l'importazione, evitando liste parziali.
- **Statistiche del builder**: fonti per colore rispetto ai requisiti di Karsten, terre tappate, probabilità di terre e interazione in main e sideboard, ricalcolate a ogni modifica. Eliminare una carta mostra "Annulla".
- **Ricerca carte**: "/" porta il focus sulla ricerca. C'è un filtro per funzione (rimozione, counter, pescata, hate al cimitero…, dai tag Scryfall) e i filtri attivi compaiono come chip rimovibili.
- **Generazione e Analisi matchup** girano sul server come lavori persistenti: AI Studio mostra la fase reale, permette di annullare e ritrova il lavoro dopo un reload. Dal Metagame, "Costruisci da questo archetipo" apre la generazione con quel punto di partenza.
- **Playtest**: D pesca, T nuovo turno, U stappa, M mulligan, Z annulla.
- **Mazzi e guide → Qualità**: metriche automatiche per formato, senza AI.
  - Mazzi generati confrontati con le liste di consenso: sovrapposizione, deficit di fonti, interazione, differenze non motivate.
  - Guide: matchup coperti, parole e carte avversarie per matchup, errori dei validatori, avvisi aperti.
  - Esecuzioni per versione del prompt e modello, con le tue valutazioni da 1 a 5 (in fondo a ogni guida).
  - Da riga di comando: `python quality_report.py pioneer [--json]` dalla cartella `backend`.
  - Ogni esecuzione AI registra i token del provider. Per vedere anche il costo medio imposta la tariffa del modello in `config/ai-models.json`, per esempio `"pricing": {"inputPerMillion": 1.25, "outputPerMillion": 10, "currency": "USD"}`, con i prezzi del tuo contratto. Senza tariffa il report mostra solo i token.
- **Risultati reali**: il pulsante "Risultati" su un mazzo registra i tuoi match per archetipo avversario. La guida successiva li confronta con le stime.
- **Mazzi e guide → Mazzi attivi**: cerca, apri, duplica, avvia il playtest, consulta le versioni o archivia una lista. Archiviare la toglie dai selettori, mantenendo dati e storico.
- **Archiviati**: ripristina una lista oppure eliminala definitivamente dopo conferma.
- **Guide salvate**: ogni generazione conserva una versione indipendente con la lista analizzata, modello, data e contesto. Anche le liste incollate hanno una guida archiviata. Puoi leggere ed esportare ogni versione in PDF con indice navigabile, lista, piani e tabelle di sidata.
- Modificare le carte o il formato rende la guida precedente uno storico; non la presenta come aggiornata. Eliminare un mazzo elimina le sue revisioni, ma mantiene le guide e le rispettive liste.

L’export PDF è illustrato anche per le versioni già salvate: lista testuale e griglia completa main/side con quantità, immagini in tutte le mani di esempio e in ogni scheda carta. Le schede delle vere carte a doppia faccia mostrano anche il retro disponibile. Il formato usa copertina con riepilogo, indice navigabile di soli capitoli, intestazioni di sezione e tabelle che continuano correttamente su più pagine.

Le immagini ufficiali in risoluzione normale vengono scaricate da Scryfall e conservate in `data/cache/pdf-card-images`; i download falliti non vengono memorizzati e saranno riprovati all’export successivo. In assenza di un’immagine il riquadro riporta esplicitamente il nome della carta. Riscaricare un PDF applica il nuovo stile alla guida esistente, senza nuove chiamate AI.

Il database predefinito è `data/mtgdeck.db`, nel server dell'app, **non nel cloud del browser**. Conserva mazzi, guide, revisioni e impostazioni (compresa la chiave provider inserita nella UI). Non pubblicarlo. Per un backup coerente usa SQLite `.backup` oppure arresta l'app prima di copiare il database. Puoi configurare `DATABASE_URL`; per PostgreSQL occorre installare il driver appropriato. Il deployment multiutente e l'autenticazione non sono implementati: il servizio è progettato come workbench personale. Le richieste che modificano dati sono accettate solo dall'origine dell'app o da quelle in `CORS_ORIGINS` (predefinite: `127.0.0.1`/`localhost` su 5173 e 8090), così una pagina web visitata non può usare l'API locale. L'immagine Docker ascolta su `0.0.0.0`: non esporla in rete senza un proxy con autenticazione.

## Legalità e qualità delle analisi

La validazione usa `legalities` di Scryfall per identità Oracle: banlist, rotazione, limite combinato delle copie e relative eccezioni. La stampa mostrata non determina da sola la legalità. In Constructed il minimo è **60 main** e il massimo **15 side**, companion incluso. Il generatore propone, per scelta, **60+15**. Le restrizioni specifiche dei companion richiedono una verifica manuale e impediscono la certificazione automatica della lista.

Il catalogo viene aggiornato senza cancellare identità collegate ai mazzi. Le analisi AI sono bloccate se manca una sincronizzazione documentata o ha più di 48 ore; con lo scheduler attivo, all'avvio la sync parte da sola se l'ultima ha più di 24 ore. Questa soglia limita i dati obsoleti ma non certifica l'assenza di un annuncio di ban più recente: prima del torneo consulta le regole Wizards. La lista dei set è indicativa, derivata dalle stampe rappresentative del catalogo Oracle (per Standard, una finestra continua di espansioni già uscite); il controllo effettivo è sempre sulla carta.

Le skill motivano engine, densità, manabase, clock, interazioni Oracle, esclusioni, piani alternativi e slot post-side. Prezzo, rarità o tipo Lesson non sono filtri di legalità. Le probabilità di vedere almeno una copia in 7/9/10 carte sono calcolate con distribuzione ipergeometrica; non sono probabilità di poter lanciare la carta. Le liste invalide vengono riproposte all'AI o rifiutate, senza riempire automaticamente i buchi. Mani di esempio e sidate vengono verificate per copie disponibili e bilanciamento IN/OUT.

### Generazione dei mazzi

Il meta non limita le scelte: è il campo da battere. Il punto di partenza si sceglie in AI Studio:
- **Lista di consenso di un archetipo del meta.** L'app aggrega le liste complete dell'archetipo con il metodo di Frank Karsten: ogni copia entra se la gioca il maggior numero di liste. Le carte nell'80% delle liste o più sono il *core*, le altre i *flex*. Ogni differenza della proposta rispetto al consenso deve essere motivata: carta, copie, matchup che migliora e costo opportunità.
- **Brew dalla tua tesi.** Archetipi, colori e build-around fuori meta sono ammessi. Le due liste di consenso più vicine servono come riferimento di densità e come fonte di carte già testate.

Il modello riceve il **campo atteso**: i primi 8 archetipi pesati per quota, ciascuno con il core, l'interazione attesa per lista (calcolata con i tag funzionali di Scryfall), la curva e la sideboard probabile. Riceve anche i testi Oracle completi delle carte chiave avversarie e del pool, cioè le carte osservate nel formato e lanciabili nei colori. Sono ammesse anche carte fuori pool, purché legali. La lista di staple scritta a mano è stata eliminata.

Il processo:
1. **Generazione.**
2. **Controlli deterministici e riparazioni** con lo stesso modello: legalità, colori, copie, 60+15, build-around.
3. **Analisi calcolata dall'app**:
   - fonti per colore rispetto ai requisiti della tabella di Karsten (le fetch contano solo per ciò che possono cercare nella lista);
   - terre tappate;
   - curva;
   - interazione nel main e in sideboard;
   - probabilità ipergeometriche.
4. **Verifiche del ragionamento**: un piano di sideboard per ciascuno dei 5 archetipi principali, con IN e OUT bilanciati e disponibili, e i delta rispetto al consenso.
5. **Revisione strategica** con un mandato diverso: cerca punti deboli contro i tier principali, slot morti, overboarding e affermazioni contraddette dai testi Oracle.

Se il revisore trova problemi gravi o una verifica non è superata, il modello rivede la lista una volta sola. Una revisione che viola le regole del formato viene scartata e resta la lista precedente, già valida. Il risultato mostra:
- punto di partenza e tabella dei delta;
- analisi;
- piani contro il campo;
- regole per cambiare i flex slot;
- esito della revisione;
- avvisi ancora aperti.

### Guide

La guida riceve gli stessi fatti della generazione:
- il campo atteso;
- le liste di consenso complete dei primi 4 archetipi;
- l'Oracle delle carte avversarie chiave;
- i ruling Scryfall delle nostre carte;
- l'analisi della lista calcolata dall'app (fonti, terre tappate, probabilità).

Per ogni matchup principale indica:
- chi è il beatdown prima e dopo la sideboard;
- almeno 2 carte avversarie con soglie o timing e la nostra risposta;
- la sideboard avversaria prevista;
- le note play/draw;
- la sidata motivata;
- una stima Bo3 con confidenza.

L'analisi approfondita di un singolo matchup resta compito dell'Analisi matchup. Al posto del punteggio numerico c'è una posizione qualitativa nel campo. La stima ponderata è un'opinione del modello, perché nessuna fonte pubblica dati testa a testa.

Le guide passano **bozza → controlli deterministici → revisione con correzioni → verifica dei passaggi modificati**. I controlli deterministici verificano:
- copie disponibili;
- sidate bilanciate;
- copertura dei matchup;
- carte avversarie citate presenti nelle loro liste osservate;
- mani tenute lanciabili con i colori delle terre in mano.

Il revisore restituisce patch con riscontro esatto e fonte; ogni patch si applica da sola, quindi una malformata non scarta le altre. Il lettore e il PDF includono una matrice di sideboard carta × matchup.

Ogni tentativo ha un **budget di 12 minuti**, timeout per chiamata e nessun retry HTTP automatico. Sono previsti al massimo tre passaggi di revisione o verifica, riducibili con `deck_guide.maxValidationRetries`. Una bozza completa **non viene più scartata**: se la revisione non si chiude (tempo, errore del provider, rilievi non risolti, correzioni non verificate), la guida viene pubblicata come "Pubblicata con punti da verificare", con l'elenco dei rilievi aperti nel lettore e nel PDF. La revisione AI riduce gli errori, ma non è una certificazione formale delle regole.

La generazione avviene nel server come lavoro persistente (`guide_jobs`): AI Studio mostra fase reale, tempo trascorso e annullamento. Puoi cambiare sezione o ricaricare la pagina. Una bozza completa viene conservata prima della revisione; dopo un errore o riavvio puoi riprendere soltanto i controlli, senza riscriverla. Una firma della lista e del modello impedisce di pubblicare una guida su una lista modificata nel frattempo. L’annullamento impedisce la pubblicazione; una chiamata al provider già in corso può terminare prima dell’arresto del lavoro. I tentativi duplicati vengono riuniti; sono ammesse al massimo due analisi contemporanee.

Le bozze rifiutate dal flusso precedente sono recuperabili se la lista è rimasta invariata, e non vengono proposte quando esiste una guida successiva già approvata. Le bozze non approvate restano separate da **Guide salvate**.

**Winrate teorico ponderato**: `somma(quota archetipi × WR teorico Bo3) / somma(quote coperte)`. La guida mostra copertura, righe, fonte e data. I matchup mancanti restano ignoti; quote incoerenti impediscono il calcolo. Si tratta di stime AI, non risultati empirici, intervalli statistici o promesse di rendimento. I nuovi snapshot non contengono matrici dei matchup; quelle degli snapshot precedenti sono mostrate come stime euristiche. Le guide storiche eventualmente già salvate vengono preservate; non è possibile ricostruire dati che non erano stati registrati.

Ogni nuova guida include `meta_estimate`, anche quando il calcolo non è possibile: `status` e `reason` distinguono snapshot assente, quote incoerenti e matchup non corrispondenti. Il messaggio delle versioni storiche senza dati non viene usato per questi casi.

Le fasi della generazione vengono registrate nei log del backend. Un tentativo fallito conserva una diagnostica e l’ultima bozza in `ai_runs`, separatamente dalle guide pubblicate, per poter analizzare gli errori senza ricreare il testo. Le eccezioni del provider vengono registrate solo per tipo, senza contenuti della richiesta o credenziali.

## Metagame

La fonte è MTGTop8 (periodo "Last 2 Months"), letta con richieste HTTP normali, un User-Agent identificativo e una pausa tra le richieste (`META_REQUEST_DELAY_MS`). Per gli archetipi principali, fino a coprire il 90% della quota (`META_COVERAGE_TARGET_PCT`, massimo `META_MAX_ARCHETYPES`), vengono raccolte fino a `META_LISTS_PER_ARCHETYPE` liste recenti complete. Le liste restano in cache (`tournament_decklists`): le sincronizzazioni successive scaricano solo quelle nuove, e una lista che contiene una carta bandita in seguito viene esclusa. La prima sincronizzazione richiede alcuni minuti per formato.

Da queste liste l'app calcola solo valori osservati: per ogni archetipo, la percentuale di liste che gioca ogni carta e le copie medie in main e side; per il formato, la presenza ponderata per quota. Colori, carte chiave e liste di esempio derivano dalle stesse liste. Il tier è una convenzione dell'app per quota (Tier 1 ≥ 5%, Tier 2 ≥ 2%). La fonte non pubblica winrate né risultati testa a testa: l'app non li stima. Ogni snapshot riporta copertura, liste analizzate e avvisi (archetipi con meno di tre liste complete); sotto il 70% di copertura è marcato come parziale. Una pagina non riconosciuta fa fallire la sincronizzazione invece di salvare numeri inventati. Si conservano gli ultimi `META_KEEP_SNAPSHOTS` snapshot per formato.

Con il catalogo vengono scaricati anche i ruling ufficiali e i tag funzionali di Scryfall Tagger (rimozione, counterspell, pescata, hate al cimitero…), mostrati nella scheda carta e disponibili per le analisi.

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
