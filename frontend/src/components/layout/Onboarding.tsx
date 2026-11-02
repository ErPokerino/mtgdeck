import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Compass, X } from "lucide-react";
import type { ActiveTab } from "./TopBar";

export const ONBOARDING_KEY = "aetherdeck.onboarding.v1";
const steps: {
  tab: ActiveTab;
  target: string;
  title: string;
  text: string;
  tryThis: string;
}[] = [
  {
    tab: "format_info",
    target: "formats",
    title: "Parti dal formato",
    text: "Il formato in alto governa ricerca, legalità, metagame e analisi AI. Set & Banlist mostra cosa puoi registrare.",
    tryThis:
      "Scegli Standard, Pioneer o Modern. Controlla la data del catalogo in alto e usa la freccia circolare per sincronizzarlo.",
  },
  {
    tab: "deckbuilder",
    target: "deckbuilder",
    title: "Costruisci o importa la tua lista",
    text: "Cerca le carte nel Deck Builder, aggiungile al main o alla sideboard, oppure importa una lista testuale.",
    tryThis:
      "Dai un nome alla lista e premi Salva. Prima del salvataggio è una bozza nel browser; dopo è nel server e nell’archivio.",
  },
  {
    tab: "meta",
    target: "meta",
    title: "Prepara il torneo sul meta",
    text: "Consulta quote, archetipi, liste campione e carte più presenti. Fonte e data ti aiutano a giudicare l’attualità dei dati.",
    tryThis:
      "Apri un archetipo: puoi caricarne una lista nel builder o portarlo al confronto matchup in AI Studio.",
  },
  {
    tab: "ai_studio",
    target: "ai_studio",
    title: "Usa l’AI con un obiettivo concreto",
    text: "In Crea mazzo scegli colori, archetipo e carte chiave. In Guida e sideboard analizzi una lista salvata o incollata; in Confronta matchup studi un avversario.",
    tryThis:
      "Configura il provider dalle impostazioni se necessario. Le guide mostrano la fase reale e conservano la bozza; puoi continuare a usare l’app durante l’analisi.",
  },
  {
    tab: "playtest",
    target: "playtest",
    title: "Prova le decisioni sul campo",
    text: "Scegli un mazzo e una mano iniziale. Clicca l’immagine in mano per giocarla, sul campo per TAP/STAP. I tre puntini aprono informazioni e azioni.",
    tryThis:
      "Prova a spostare una carta tra le zone. Nel menu trovi facce delle carte doppie, pedine e segnalini. Annulla recupera un’azione; il test non modifica il mazzo salvato.",
  },
  {
    tab: "library",
    target: "library",
    title: "Ritrova mazzi, versioni e guide",
    text: "Mazzi e guide è il tuo archivio: apri, duplica, consulta le versioni o archivia i mazzi. Le guide approvate sono versioni indipendenti, leggibili ed esportabili in PDF.",
    tryThis:
      "Archivia per togliere una lista dai selettori. In Archiviati puoi ripristinarla o eliminarla. Riapri questo percorso quando vuoi dal pulsante Aiuto in alto.",
  },
];

export function Onboarding({
  restartToken,
  onNavigate,
  onSettings,
  suspended = false,
}: {
  suspended?: boolean;
  restartToken: number;
  onNavigate: (tab: ActiveTab) => void;
  onSettings: () => void;
}) {
  const [mode, setMode] = useState<"welcome" | "tour" | "closed">(() => {
    try {
      return localStorage.getItem(ONBOARDING_KEY) ? "closed" : "welcome";
    } catch {
      return "welcome";
    }
  });
  const [step, setStep] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const originalFocus = useRef<HTMLElement | null>(null);
  const close = () => {
    setMode("closed");
    try {
      localStorage.setItem(ONBOARDING_KEY, "seen");
    } catch {}
    originalFocus.current?.focus();
  };
  useEffect(() => {
    if (restartToken) {
      originalFocus.current = document.activeElement as HTMLElement;
      setStep(0);
      setMode("welcome");
    }
  }, [restartToken]);
  useEffect(() => {
    if (mode === "closed" || suspended) return;
    if (mode === "tour") onNavigate(steps[step].tab);
    const timer = window.setTimeout(() => {
      heading.current?.focus();
      const target =
        mode === "tour"
          ? document.querySelector<HTMLElement>(
              `[data-tour="${steps[step].target}"]`,
            )
          : null;
      target?.setAttribute("data-tour-active", "true");
      target?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }, 60);
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
      if (mode === "welcome" && e.key === "Tab") {
        const buttons = Array.from(
          document.querySelectorAll<HTMLButtonElement>(
            "[data-onboarding-welcome] button",
          ),
        );
        const first = buttons[0],
          last = buttons.at(-1);
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === heading.current)
        ) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", key);
      document
        .querySelectorAll("[data-tour-active]")
        .forEach((el) => el.removeAttribute("data-tour-active"));
    };
  }, [mode, step, suspended]);
  if (mode === "closed" || suspended) return null;
  if (mode === "welcome")
    return (
      <div className="fixed inset-0 z-[80] bg-black/75 flex items-center justify-center p-4">
        <section
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-title"
          data-onboarding-welcome
          className="panel w-full max-w-xl space-y-5 shadow-2xl"
        >
          <div className="flex justify-between items-center">
            <Compass className="text-amber-200" size={30} />
            <button
              aria-label="Chiudi introduzione"
              className="btn-secondary"
              onClick={close}
            >
              <X size={18} />
            </button>
          </div>
          <p className="eyebrow">Benvenuto in Aetherdeck</p>
          <h2
            id="onboarding-title"
            ref={heading}
            tabIndex={-1}
            className="text-2xl font-bold"
          >
            Dalla lista al piano per il torneo
          </h2>
          <p className="text-slate-300 leading-relaxed">
            Un percorso di 6 tappe ti mostra dove costruire, studiare il meta,
            generare guide e provare il mazzo. Navigherai nelle sezioni reali,
            senza creare dati o avviare analisi AI.
          </p>
          <div className="flex flex-wrap gap-3">
            <button className="btn-primary" onClick={() => setMode("tour")}>
              Inizia il percorso <ArrowRight size={16} />
            </button>
            <button className="btn-secondary" onClick={close}>
              Esploro da solo
            </button>
          </div>
          <p className="text-sm text-slate-400">
            Puoi saltare qualsiasi tappa e riaprire il percorso da Aiuto.
          </p>
        </section>
      </div>
    );
  const current = steps[step];
  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby="tour-title"
      className="onboarding-coach panel fixed z-[60] bottom-4 right-4 w-[min(420px,calc(100vw-2rem))] max-h-[55vh] overflow-y-auto shadow-2xl border-amber-300/60 space-y-3"
    >
      <div className="flex items-center justify-between">
        <p className="eyebrow">
          Percorso iniziale · {step + 1} di {steps.length}
        </p>
        <button
          className="p-1 text-slate-400 hover:text-white"
          aria-label="Chiudi percorso"
          onClick={close}
        >
          <X size={18} />
        </button>
      </div>
      <h2
        id="tour-title"
        ref={heading}
        tabIndex={-1}
        className="text-lg font-bold"
      >
        {current.title}
      </h2>
      <p className="text-sm leading-relaxed text-slate-300">{current.text}</p>
      <p className="text-sm leading-relaxed rounded-lg bg-amber-200/5 border border-amber-200/15 p-3 text-amber-100">
        {current.tryThis}
      </p>
      {step === 3 && (
        <button className="text-sm underline text-sky-300" onClick={onSettings}>
          Apri impostazioni AI
        </button>
      )}
      <div className="flex items-center justify-between gap-2">
        <button
          className="btn-secondary"
          disabled={step === 0}
          onClick={() => setStep((s) => s - 1)}
          aria-label="Tappa precedente"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex gap-1">
          {steps.map((s, i) => (
            <button
              key={s.tab}
              aria-label={`Vai alla tappa ${i + 1}`}
              aria-current={step === i ? "step" : undefined}
              className={`w-6 h-6 rounded text-xs ${step === i ? "bg-amber-200 text-black" : "bg-slate-800 text-slate-400"}`}
              onClick={() => setStep(i)}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <button
          className="btn-primary"
          onClick={() =>
            step === steps.length - 1 ? close() : setStep((s) => s + 1)
          }
        >
          {step === steps.length - 1 ? "Fine" : "Avanti"}
          <ArrowRight size={14} />
        </button>
      </div>
    </aside>
  );
}
