# Aetherdeck — Piano degli interventi

Data analisi: 2026-11-03. Ambito: backend, frontend, pipeline AI (generazione mazzi e guide), dati di metagame, UX/UI.
Riferimenti di qualità: 9 guide professionali fornite (Boros Energy, UW Oculus, Pixie, UW Omni, Izzet Lessons, Prowess + update, Izzet Deck Wins).

Stato verificato: 51 test backend verdi; ruff 505 segnalazioni (quasi tutte stilistiche, non in CI); nessun errore in console nel browser.
Nota: `poc/mtg-deck-builder` è un prototipo precedente (Vite + Scryfall diretto, senza guide) superato da questo progetto.

---

## 1. Diagnosi in sintesi

Il codice è curato sul piano della **correttezza formale** (legalità per identità Oracle, sidate bilanciate, job persistenti, firma della lista). I problemi che impediscono di raggiungere l'obiettivo — *mazzi e guide in grado di battere i tier del meta* — sono soprattutto di **impostazione e di dati**, non di singoli bug:

1. **Il generatore inventa una lista da un pool di carte invece di partire da ciò che vince.** I mazzi salvati sono brew fuori meta (Rakdos Attrition Control in Pioneer, Mono-Black Sorin Ripper e Grixis Frog Reanimator in Modern). Un giocatore competitivo parte dalla lista consolidata di un archetipo forte e ottimizza i flex slot e la sideboard contro il campo atteso.
2. **L'AI ragiona con dati poveri o falsi.**
   - Oracle troncato a 135 caratteri nel pool.
   - Una sola lista campione per archetipo, a volte incompleta (56–58 carte).
   - Statistiche per archetipo ricavate con formule e non osservate.
   - Matrice dei matchup euristica, basata su stereotipi di categoria.
   - Avversari descritti con 12 righe di main e nessuna sideboard.
3. **Le guide sono ottimizzate per "zero errori", non per la profondità.**
   - Limiti di circa 35 parole per piano di matchup e 6 parole per motivo di sidata, contro 150–400 parole nelle guide pro.
   - Revisore solo formale, nessuna revisione strategica.
   - Regole cablate su singole carte (Kiki-Jiki, Torch the Tower…).
   - Pubblicazione "tutto o niente": 8 generazioni su 16 sono fallite e il costo AI è andato perso.
   - Nonostante tutto, la guida Rakdos contiene comunque errori di regole.
4. **La UX è curata su desktop ma il builder è inutilizzabile sotto i 1024 px.** Diversi comandi esistono solo all'hover e quindi non si raggiungono da tastiera o da touch.

L'ordine proposto: prima i **bug che falsano i dati** (Fase 0–1), poi il **nuovo processo di generazione** (Fase 2) e le **guide** (Fase 3), che dipendono da dati affidabili, mentre la **UX** (Fase 4) procede in parallelo. Chiude un **sistema di misura** (Fase 5) per sapere se i cambiamenti migliorano davvero i risultati.

---

## 2. Fase 0 — Bug e incoerenze da correggere subito

Priorità per impatto. Stima complessiva: 2–3 giorni.

| ID | Gravità | Dove | Difetto | Correzione |
|---|---|---|---|---|
| B1 | Critica | `scryfall_sync.py:239`, upsert `:509-515` | Le carte "any number of cards named" (Hare Apparent, Slime Against Humanity, Relentless Rats, Persistent Petitioners…) sono salvate con `max_copies=4` perché `None` cade sul default della colonna. I mazzi che le usano sono rifiutati da validatore, generazione e guide. | Sentinella esplicita per "illimitato" (es. `-1`) o nessun default; test di regressione con una sync reale. |
| B2 | Alta | `main.py:106-112` | CORS `*` con credenziali su un'API senza autenticazione che conserva la chiave Gemini: qualsiasi sito visitato può cambiare impostazioni, cancellare mazzi o consumare quota. Il Dockerfile espone `0.0.0.0`. | Origini limitate a `127.0.0.1:5173/8090`; token locale o avviso esplicito nel deploy Docker. |
| B3 | Alta | `models.py` (`decks`, `ai_runs`, `guide_jobs`) | Gli ID dei mazzi eliminati vengono riassegnati (SQLite senza `AUTOINCREMENT`); `ai_runs.deck_id` e `guide_jobs.deck_id` non hanno FK. Verificato: il mazzo 7 risulta collegato anche a una vecchia richiesta "aggro UB con Quantum Riddler". | `sqlite_autoincrement=True` (migrazione), FK con `SET NULL` su `ai_runs`/`guide_jobs`. |
| B4 | Alta | `meta_scraper.py:168,193,201,205` | Se il parsing fallisce vengono salvati valori inventati (2000 mazzi, quota 1%, WR 50%, 50 mazzi) con stato "completed". | Fallire la sync o marcare la riga; controllo di coerenza (somma quote, colonne attese). |
| B5 | Alta | `meta_scraper.py:573, 587-606` | Presenza per archetipo calcolata con `max(65, overall*1.8)` e assegnata per sottoinsieme di colori. Verificato: Duress all'84,8% sia in Dimir sia in Jund; Torpor Orb al 65% in Mono Green. Questi numeri arrivano all'UI e all'AI. | Salvare solo valori osservati (null se ignoti). |
| B6 | Alta | `meta_scraper.py:361-367, 438` | Liste "reali" accettate con main ≥ 50 dopo aver scartato in silenzio le carte non risolte (Golgari 56, Dimir Ninjas 58). "Carica mazzo archetipo" crea liste da 56. | Richiedere 60/15 complete oppure conservare il testo grezzo e segnalare le lacune. |
| B7 | Alta | `deck_validator.py:290-296` | L'export Arena usa stampe non Arena: 84 carte su 139 senza `arena_id` (es. Blood Crypt TRK). | Scegliere una stampa con `arena_id` o esportare solo il nome. |
| B8 | Alta | `DeckBuilderView.tsx:646`, `ResizableSplitPane.tsx:110` | Sotto i 1024 px il pannello del mazzo è irraggiungibile: l'input nome è a y=5564 in una pagina alta 957. | Vedi U1. |
| B9 | Media | `AIStudioView.tsx:221, 402-405` | Matchup con avversario salvato o incollato: `deck_b_name` prende il nome del primo archetipo del meta. | Usare il nome della sorgente effettivamente scelta. |
| B10 | Media | `LibraryView.tsx:393` | Il ripristino di una versione non aggiorna `activeDeck` né la bozza locale: un "Salva" successivo annulla il ripristino. | Aggiornare lo stato e la bozza dopo il restore. |
| B11 | Media | `runner.py:816-894` | Il validatore della generazione ignora `requested_colors`: l'AI può uscire dai colori richiesti senza che venga segnalato. | Verifica dei colori (con eccezioni dichiarate: terre, ibride, Phyrexian). |
| B12 | Media | `runner.py:956-984` | Le riparazioni della lista usano sempre Flash Lite, anche se hai scelto il modello migliore: la tesi strategica viene riscritta da un modello debole; le eccezioni vengono ingoiate (`except: break`). | Riparazione deterministica dove possibile (conteggi), altrimenti stesso modello della generazione; loggare l'errore. |
| B13 | Media | `meta_scraper.py:825-827`, `meta.py:175` | Un errore su un formato blocca la sync degli altri; nessun lock: scheduler e sync manuale possono sovrapporsi. | try/except per formato, lock di sync. |
| B14 | Media | `main.py:70-90`, `guide_quality.py:273` | Dopo più di 2 giorni di app spenta tutte le funzioni AI sono bloccate finché non sincronizzi a mano. | Sync Scryfall all'avvio se più vecchia di 24 h, in background. |
| B15 | Media | `guide_jobs.py:241-242` | Ogni eccezione viene mostrata come "timeout del provider": i bug reali restano nascosti. | Mappare solo gli errori del provider; per il resto loggare il tipo. |
| B16 | Media | `meta.py:22-49` | `async def` con query sincrone e uno scrape di minuti dentro una GET. | `def` sincrono, risoluzione carte in batch, 503 più sync in background. |
| B17 | Media | `executeSearch`/`analyzeDeck` (`DeckBuilderView.tsx:277, 340-362`) | Race condition: niente abort né debounce; risposte vecchie sovrascrivono validazione e statistiche. | `AbortController` più numero di sequenza, debounce. |
| B18 | Media | `App.tsx:387` | AI Studio è montato con `key={selectedFormat}`: generazione o matchup in corso si perdono cambiando formato, anche se l'UI promette il contrario. | Trasformarli in job persistenti come le guide (vedi G-8). |
| B19 | Media | `decks.py:312` | L'import non registra la revisione (il mazzo importato mostra "0 versioni"). | `record_revision` anche nell'import. |
| B20 | Media | curva di mana (frontend `:1717` e backend) | Scala fissa a 20 carte; Room e split card contate col mana value combinato (Unholy Annex finisce in "6+"). | Mana value della faccia lanciabile, scala proporzionale. |
| B21 | Bassa | `FormatExplorerView` / sets | Standard mostra 32 set, inclusi set non ancora usciti (2026-11-13, 2027-04-09) e set di sole ristampe. | Filtrare per data di uscita e tipo di set. |
| B22 | Bassa | vari | Riga vuota nel main interpretata come inizio della sideboard (`deck_validator.py:235`); split card esportate col solo nome anteriore; PDF in Helvetica base-14 (glifi mancanti per → ≥); `toLowerCase` su nome nullo (`LibraryView.tsx:147`); `pushState` dentro l'updater (`App.tsx:122`); `mana-font@latest` non fissato; "1 cicli"; liste di esempio cablate. | Correzioni puntuali. |

### Stato Fase 0 (2026-11-03)

Completati B1–B21 e quasi tutto B22, con 20 test di regressione in `backend/tests/test_phase0_fixes.py` (71 test verdi) e verifica nel browser su una copia del database.

Le correzioni ai dati esistenti avvengono all'avvio, in `backend/app/migrations.py`; sono idempotenti:
- tabella `decks` ricostruita con `AUTOINCREMENT`;
- limiti copie ricalcolati dal testo Oracle;
- collegamenti a mazzi riutilizzati scollegati;
- statistiche per archetipo inventate sostituite con le copie osservate;
- conteggi di partite inventati azzerati nella matrice euristica;
- flag di legalità dei set ricalcolati;
- revisioni iniziali mancanti create.

Note emerse durante il lavoro:
- B1: la causa vera era `default=4` sulla colonna. Con l'ORM, un `None` esplicito attiva il default; la sync usa Core e non era colpita.
- La matrice dei matchup mostrava "N match osservati", ma quei conteggi erano inventati da una versione precedente dello scraper.
- B18 risolto mantenendo un'istanza di AI Studio per formato visitato. I job persistenti restano in G-8.

Restano aperti:
- font Unicode nel PDF;
- liste di esempio cablate in `ImportExportModal`;
- ricerca che non usa l'indice FTS5.

**Debito tecnico da pianificare:**
- `FORMAT_CONSTRUCTED_STAPLES` in `runner.py:66-422`: circa 350 nomi scritti a mano, con refusi ("extinction Event", "fleeting Spirit"), voci inesistenti ("Raptor") e carte che si invecchiano a ogni set. Da sostituire con dati derivati dal meta (Fase 2).
- `runner.py` (55 KB) e `DeckBuilderView.tsx` (78 KB) sono monoliti da suddividere quando si toccano.
- Ruff in CI, almeno con le regole `F`, `B`, `BLE`.

---

## 3. Fase 1 — Dati di metagame affidabili (fondamenta)

Senza questa fase, qualunque miglioramento di prompt produce analisi sicure di sé ma basate su dati sbagliati. Stima: 4–6 giorni.

- **D1. Più liste, complete.** Per ogni archetipo, 10–30 liste recenti (ultime 2–4 settimane) con main e side completi, evento, piazzamento, data e fonte. Oggi ce n'è una sola.
- **D2. Copertura del meta.** Scendere oltre i 12 archetipi fino all'80–90% della quota e dichiarare la quota non coperta.
- **D3. Matchup reali.** Se la fonte (MTGDecks) espone matrici testa a testa, salvare WR e numero di partite. Altrimenti tenere la matrice euristica solo come fallback, etichettata, ed **escluderla** dal "winrate ponderato".
- **D4. Statistiche per archetipo osservate.** Calcolate dalle liste di D1: tasso di inclusione e copie medie in main e side, separatamente.
- **D5. Validazione e storicizzazione.** Controlli di coerenza su ogni snapshot (quote, colonne, liste ≥ 60/15), stato "degradato" visibile in UI e pulizia degli snapshot vecchi.
- **D6. Ruling Scryfall.** Scaricare e salvare in cache `/cards/{id}/rulings` per le carte usate nei mazzi e nelle liste del meta. Servono alle guide (G-3).
- **D7. Fonti (decisione richiesta).** Lo scraping di MTGTop8 e MTGDecks è fragile. Valutare l'aggiunta di MTGO Decklists ufficiali o di Melee.gg; preferire fonti con dati strutturati.

---

## 4. Fase 2 — Nuovo processo di generazione mazzi

Obiettivo: liste che un giocatore competitivo registrerebbe, con ogni scelta motivata contro il campo atteso. Stima: 6–8 giorni.

### 4.1 Pipeline proposta ("consapevole del meta")

Decisione presa: archetipi e carte fuori meta restano pienamente supportati, perché i parametri del form li consentono. Il meta non limita le scelte; è il **campo da battere**, e ogni lista, anche creativa, deve essere ottimizzata contro di esso.

1. **Punto di partenza.**
   - **Archetipo del meta scelto**: si parte dalla lista di consenso (punto 2) e la si migliora.
   - **Brew** (archetipo, colori o build-around fuori meta): si parte dalla tesi dell'utente. Le liste di consenso più vicine servono come riferimento di densità (interazione, curva, terre) e come fonte di carte già testate, non come vincolo. L'ottimizzazione può essere creativa (tech, angoli d'attacco che il meta non si aspetta), ma ogni scelta va motivata contro il campo.
2. **Lista di consenso (deterministica).** Dalle liste D1 si calcolano il tasso di inclusione e le copie medie per carta.
   - **Core**: carte presenti in almeno l'80% delle liste.
   - **Flex**: il resto.
   - **Lista stock**: il consenso arrotondato a 60/15.

   Nessuna AI in questo passaggio.
3. **Modello del campo atteso.** Archetipi pesati per quota (D2) con le loro liste reali e la loro interazione (vedi 4.2).
4. **Ottimizzazione AI.** Il modello riceve punto di partenza, campo atteso, profili avversari e Oracle completo (senza troncature).
   - Per gli archetipi del meta motiva ogni differenza dalla stock con una tabella *delta* (carta, IN/OUT, quale matchup migliora, costo opportunità).
   - Per i brew dichiara contro quali archetipi principali la lista è costruita, le concessioni accettate e come la sideboard copre i matchup peggiori.
5. **Analisi deterministiche sulla lista finale.**
   - Fonti per colore rispetto ai requisiti per turno (tabelle Karsten calcolate dall'app, non dal modello).
   - Terre che entrano tappate e curva.
   - Densità di interazione per tipo.
   - Probabilità ipergeometriche delle carte chiave.
   - Copertura della sideboard per i matchup principali.
6. **Revisione strategica (critico).** Un secondo passaggio AI con mandato diverso: cercare i punti deboli della lista contro i 4–5 archetipi più giocati, i slot morti e l'overboarding. Il risultato sono raccomandazioni, applicate solo se motivate.
7. **Validazione e riparazione.** Prima i controlli deterministici (60/15, copie, legalità, colori — B11), poi riparazioni deterministiche. L'AI di riparazione è lo stesso modello (B12).
8. **Output.** Lista, tabella delta rispetto alla stock, metriche del punto 5, rischi, e criteri per cambiare i flex slot ("se X supera il N% del meta → A al posto di B").

### 4.2 Contesto "magic numbers" precalcolato

Per ogni archetipo del campo, l'app calcola dalle liste e dall'Oracle:
- rimozioni per tipo (soglia di danno, esilio o distruzione, velocità);
- counter;
- hate al cimitero;
- wrath;
- curva iniziale tipica;
- carte di sideboard più probabili contro di noi (da D4).

Il modello riceve fatti, non deve dedurli.

### 4.3 Altri interventi

- Rimuovere `FORMAT_CONSTRUCTED_STAPLES`: il pool deriva da D1/D4. Per la modalità Brew restano i filtri di legalità e colore più la ricerca FTS.
- Togliere dal prompt i proclami ("Pro Tour", "Masterclass") e i valori imposti come "4x consigliato" per le build-around.
- Allineare lo schema `AIDeckGenerationOutput` al prompt: lo schema oggi chiede "Karsten math", che il prompt vieta.
- Archetipi: lasciare che la lista porti il nome dell'archetipo del meta da cui deriva, invece di un nome inventato.

### 4.4 Criteri di accettazione

- Archetipo del meta: ogni differenza dalla lista di consenso è motivata in tabella.
- Brew: la tesi indica gli archetipi principali bersaglio e le concessioni; la sideboard ha un piano per ciascuno dei primi 5 archetipi del campo.
- Nessuna fonte colorata sotto il requisito calcolato, se non con una motivazione esplicita.
- 0 statistiche inventate nel contesto passato al modello (verificato da test).

---

## 5. Fase 3 — Guide di livello professionale

Stima: 6–9 giorni. Dipende da D1, D4 e D6.

### 5.1 Cosa distingue le guide di riferimento (sintesi)

- Ogni conteggio di copie è motivato rispetto al meta (es. 4ª Swiftspear e una terra in meno quando sale Belcher).
- Le scelte sono confrontate con alternative nominate: "perché non X".
- Flex slot e "hedge" sono espliciti, con le condizioni per cambiarli.
- Ogni matchup dice **chi è il beatdown** e come cambia dopo la sidata.
- Le carte avversarie vengono nominate con soglie numeriche e finestre di timing precise.
- Ci sono **tell** (segnali) per riconoscere la variante o la carta in mano all'avversario, e piani che si **ramificano per variante**.
- Play e draw sono distinti, con motivazione.
- Viene **prevista la sidata avversaria**.
- Le mani di mulligan sono reali e il verdetto cambia in base al matchup ("trap hand", "6 funzionale").
- Principi trasferibili ("chi inciampa per primo perde").
- Dati empirici dichiarati (record di leghe) e incertezza ammessa.
- Log di aggiornamento datati.
- Profondità tipica: 150–400 parole per matchup.

### 5.2 Gap della guida Rakdos generata

- **Profondità.** Circa 10 volte inferiore per matchup. Testo generico ("Mantenere il controllo delle creature target"). In tutti gli 8 matchup la sidata on the play e on the draw è identica.
- **Errori di regole o logica non intercettati dal revisore.**
  - Kroxa lanciato dalla mano "per bloccare" (viene sacrificato).
  - Withering Torment su Teferi (colpisce solo creature e incantesimi).
  - Mano di mulligan con sole terre nere e carte rosse.
  - "Mano a sei carte" detto di una mano da sette.
  - Kolaghan's Command come se fossimo noi a scegliere lo scarto.
  - Hive of the Eye Tyrant "a pila vuota dopo aver forzato i counter" (un'abilità non si contromagia).
  - Revolt di Fatal Push "dalle fetchland" (in Pioneer non ci sono e il mazzo non ne gioca).
  - Conteggio delle fonti colorate sbagliato.
- **Valutazioni poco informative.** "Pro score 8/10" senza evidenza; tutti i WR tra il 47% e il 56%, quindi il "52,5% ponderato" non dice nulla.
- **Scelte non argomentate.** Terre, sideboard e numero di copie non sono motivati; le esclusioni sono deboli.

### 5.3 Interventi

- **G-1. Dati per matchup.** Per ogni archetipo, 2–3 liste complete da 75 (varianti); Oracle delle 10–15 carte chiave avversarie; il profilo 4.2; la sideboard avversaria prevista da D4.
- **G-2. Fatti calcolati dall'app.** Fonti per colore, fonti stappate al turno 1–3, requisiti alla Karsten per carta, probabilità ipergeometriche, castabilità. Il modello li cita, non li calcola.
- **G-3. Ruling invece di regole cablate.** Iniettare le ruling Scryfall (D6) delle carte di entrambi i mazzi e rimuovere dal prompt le regole su singole carte (`deck_guide.v1.md:13-15`) e il controllo ad hoc `reflection_copy_errors`.
- **G-4. Copertura e profondità.** Decisione presa: la guida copre **tutti i matchup principali**; l'analisi approfondita del singolo matchup resta compito dell'"Analisi matchup" dedicata, a cui la guida rimanda. Quindi niente 300 parole per matchup, ma un formato operativo più denso di oggi: ruolo pre/post side, 2 carte avversarie chiave con la nostra risposta, sidata con motivi leggibili, differenza play/draw. Budget proporzionale alla quota solo per i primi 3–4 archetipi.
- **G-5. Schema arricchito.**
  - Per matchup: `role_pre`/`role_post`; `opponent_key_cards` (carta, perché conta, nostra risposta, quando); `expected_opponent_sideboard`; `sequencing_lines` (2–4 linee "se X allora Y" con turno e mana); `tells`; `variant_branches`; motivi di sidata da 12–25 parole; play/draw sempre valutati, con "identica" ammessa solo se motivata.
  - Per carta: `count_rationale`, `alternatives_considered`, `flex_slots` con trigger di meta. Includere anche terre e sideboard.
  - Mulligan: almeno una mano il cui verdetto cambia per matchup, una "trap hand", una mano rischiosa con probabilità calcolate dall'app.
  - `update_log`.
- **G-6. Valutazioni oneste.** Eliminare `pro_score`, oppure sostituirlo con tier qualitativo più confidenza. WR per matchup in fasce (favorito / pari / sfavorito) con confidenza. Il "winrate ponderato" va mostrato solo se basato su dati reali (D3), altrimenti etichettato come opinione. Campo per i **record empirici dell'utente**, separati dalle stime AI.
- **G-7. Revisione in due livelli.**
  - Controlli deterministici nuovi:
    - carte avversarie citate presenti nelle liste fornite;
    - mani di mulligan castabili in curva con le terre in mano;
    - danni dichiarati confrontati con la costituzione dei bersagli;
    - conteggi delle fonti coincidenti con quelli calcolati;
    - confusioni frequenti (bloccare con una creatura sacrificata, "contromagiare" un'abilità, effetti sul tipo di permanente sbagliato).
  - Revisore AI che oltre alla correttezza segnala genericità e piani incoerenti (es. hate al cimitero contro un mazzo che non usa il cimitero).
- **G-8. Niente più "tutto o niente".** Pubblicare la guida con gli avvisi non risolti marcati ("da verificare"), invece di scartarla. Così non si paga per bozze buttate (oggi il 50% delle esecuzioni fallisce). Anche generazione mazzo e matchup spot diventano job persistenti.
- **G-9. Prompt.** Aggiungere 1–2 sezioni di matchup d'esempio scritte internamente come riferimento di profondità (non copiate dalle guide Patreon). Ogni matchup deve citare almeno 2 carte avversarie con un'interazione specifica. Allineare lo schema al prompt, che oggi si contraddicono su numeri di elementi e su "Karsten".
- **G-10. Lettore e PDF.** Matrice di sideboard compatta carta × matchup (+2/−1, play/draw), immagini nelle mani di mulligan, badge "guida aggiornata / obsoleta rispetto alla lista", confronto tra versioni.
- **G-11. Modello.** Usare il modello più forte (Argon) per le chiamate per matchup e il critico; Flash per la sintesi. Stima e visualizzazione del costo prima dell'avvio.

### 5.4 Criteri di accettazione

- Su un set di 3 mazzi di riferimento (vedi Fase 5): 0 errori di regole tra quelli elencati in 5.2; ogni matchup principale cita almeno 2 carte avversarie con soglie o timing; play/draw differenziati dove ha senso.
- Tasso di guide non pubblicate sotto il 10%.

---

## 6. Fase 4 — UX/UI

Può procedere in parallelo alle Fasi 1–3. Stima: 5–7 giorni.

**U1. Builder responsivo e accessibile.**
- Sotto `lg`: tab Cerca/Mazzo e una barra fissa in basso con contatore 60/15 e Salva.
- Comandi di riga sempre visibili, oppure un menu "⋯" attivabile da tastiera, con `aria-label` che include il nome della carta.
- Focus visibile (oggi i comandi sono `opacity-0` o `hidden` fino all'hover).

**U2. Pannello statistiche competitivo.**
- Fonti per colore rispetto ai requisiti di Karsten.
- Terre che entrano tappate.
- Probabilità ipergeometriche per categorie (terre, rimozioni) e carte chiave, già calcolate dal backend per le guide.
- Curva di mana corretta (B20).
- Vista a pile visive per costo o tipo, in stile Moxfield/Archidekt.

**U3. Coerenza del sistema.**
- Un componente modale unico (Esc, focus trap, ritorno del focus), oggi assente in Library, Settings e Import/Export.
- `aria-current` sulla navigazione e `aria-label` sui bottoni a sola icona.
- Label sulle select del builder.
- Elementi cliccabili come `button` invece di `div onClick`.
- Icona "Nuovo mazzo" al posto del cestino.

**U4. Leggibilità.**
- Contrasto AA: `slate-500/600` su sfondo scuro oggi è a 2,4–3,9:1.
- Testo minimo 12–13 px, target di tocco di almeno 24 px (44 consigliati).
- Header compatto su mobile: oggi occupa 205 px su 812.
- Eliminare l'overflow orizzontale su Metagame.

**U5. Lingua.** Glossario unico per l'intera app. Oggi convivono "Meta Share", "Decks / Match", "Apri Sample Deck", "Instant" e altri termini misti (decisione richiesta: italiano con termini MTG in inglese, o tutto in inglese).

**U6. Feedback affidabile.**
- Skeleton invece del falso "Nessuna carta trovata" al primo caricamento.
- Indicatore di caricamento sulle ricerche successive.
- Toast con "Annulla" per rimozioni ed eliminazioni.
- Conferma prima che l'import sovrascriva una bozza non salvata.
- Errore "0/60" mostrato come progressione neutra, non in rosso, su una bozza vuota.

**U7. Metagame.**
- Celle della matrice con opacità proporzionale al campione e intervallo di Wilson nel tooltip.
- Intestazioni sticky.
- Etichetta "euristica" ben visibile finché D3 non è disponibile.

**U8. Playtest e split pane.**
- Supporto touch.
- Scorciatoie (D pesca, U stappa, M mulligan, Z annulla).
- Mano visibile senza scroll.
- Ridimensionatore utilizzabile da tastiera.

**U9. Ricerca carte.**
- Chip con i filtri attivi.
- Filtri funzionali (rimozione, pescate, counter).
- Scorciatoia "/" per il focus.
- Una sola select di ordinamento.

---

## 7. Fase 5 — Misurare la qualità

Senza misure non si può dire se un cambio di prompt o di modello migliora i risultati. Stima: 2–3 giorni, da avviare insieme alla Fase 2.

- **M1. Set di riferimento.** 3–5 mazzi tier 1 reali per formato (liste di consenso D1) più i mazzi già generati.
- **M2. Valutazioni automatiche per i mazzi.** Sovrapposizione con il consenso, fonti rispetto ai requisiti, densità di interazione, numero di differenze non motivate.
- **M3. Valutazioni automatiche per le guide.** Esito dei validatori G-7, copertura dei matchup, parole per i matchup principali, carte avversarie citate.
- **M4. Valutazione umana.** Su un campione, griglia breve derivata da 5.1 (1–5 per profondità, correttezza e utilità in gara).
- **M5. Registro.** Per ogni esecuzione: versione del prompt, modello, costo, esito ed errori (in parte esiste già in `ai_runs`). Mostrare il trend in Impostazioni.
- **M6. Ciclo con i risultati reali.** I record dell'utente (G-6) alimentano la revisione delle stime e la scelta dei flex slot.

---

## 8. Sequenza consigliata

| Settimana | Lavoro |
|---|---|
| 1 | Fase 0 (B1–B8 subito, poi B9–B22); impianto M1/M5 |
| 2 | Fase 1 (D1–D6); in parallelo U1, U3 |
| 3 | Fase 2 (pipeline ancorata al meta) più M2 |
| 4 | Fase 3 (G-1…G-8) più M3 |
| 5 | G-9…G-11, U2, U4–U9, revisione con M4 |

Dipendenze principali:
- B4–B6 e D1–D4 vengono prima di Fase 2 e Fase 3.
- D6 viene prima di G-3.
- G-8 (job persistenti) risolve anche B18.

---

## 9. Decisioni richieste

1. ~~Modalità predefinita del generatore~~ — **decisa**: brew e archetipi fuori meta pienamente supportati, sempre ottimizzati contro il meta (4.1). Le guide coprono tutti i matchup principali; il dettaglio va all'analisi matchup (G-4).
2. **Fonti dati.** Restare su scraping di MTGTop8 e MTGDecks rafforzato, oppure aggiungere fonti strutturate (MTGO ufficiale, Melee)?
3. **Budget AI per le guide.** Le guide più profonde costano di più: più chiamate e modello Argon per i matchup. Serve un tetto di costo per guida.
4. **Lingua dell'interfaccia** (U5).
5. **Priorità mobile.** Il builder su telefono è un requisito reale, o basta il tablet?
