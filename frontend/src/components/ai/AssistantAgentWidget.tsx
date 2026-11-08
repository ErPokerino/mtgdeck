import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  AudioLines,
  Bot,
  CheckCircle2,
  Loader2,
  Maximize2,
  Mic,
  MicOff,
  Minimize2,
  PhoneOff,
  Send,
  Sparkles,
  Trash2,
  Volume2,
  Wrench,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  AgentChatMessage,
  AgentToolCallTrace,
  AppSettings,
  Card,
  DeckDetail,
  FormatId,
} from "../../types";
import { CardInfoModal } from "../common/CardInfoModal";

interface Props {
  formatId: FormatId;
  activeTab: string;
  activeDeck: DeckDetail | null;
  settings: AppSettings | null;
  onOpenSettings: () => void;
}

type VoiceStatus =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

const TOOL_LABELS: Record<string, string> = {
  list_user_decks: "Mazzi salvati",
  get_deck_details: "Analisi mazzo & Karsten",
  get_metagame_overview: "Metagame live",
  get_archetype_details: "Consenso archetipo",
  search_cards_and_rulings: "Catalogo Scryfall & Ruling",
  simulate_deck_changes: "Simulatore cambi",
  get_app_help: "Documentazione App",
};

/**
 * Renders inline markdown tokens:
 * - [[Card Name]] clickable card inspection chips (without extra space before punctuation)
 * - `inline code`
 * - ***bold italic***
 * - **bold**
 * - *italic*
 */
function renderInlineFormatted(
  text: string,
  onInspectCard: (cardName: string) => void,
  keyPrefix = "in",
): React.ReactNode[] {
  const tokenRegex =
    /(\[\[[^\]]+\]\]|`[^`]+`|\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, idx) => {
    const key = `${keyPrefix}-${idx}`;
    if (!part) return null;

    if (part.startsWith("[[") && part.endsWith("]]")) {
      const cardName = part.slice(2, -2).trim();
      return (
        <button
          key={key}
          type="button"
          onClick={() => onInspectCard(cardName)}
          className="inline-flex items-center rounded border border-sky-600/70 bg-sky-950/75 px-1.5 py-0.5 text-[11px] font-semibold text-sky-200 hover:border-sky-400 hover:bg-sky-900/80 hover:text-white transition align-baseline leading-tight"
          title={`Ispeziona ${cardName}`}
        >
          {cardName}
        </button>
      );
    }

    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code
          key={key}
          className="rounded bg-slate-800/90 border border-slate-700/70 px-1.5 py-0.5 text-[11px] font-mono text-amber-200"
        >
          {part.slice(1, -1)}
        </code>
      );
    }

    if (part.startsWith("***") && part.endsWith("***") && part.length > 6) {
      return (
        <strong key={key} className="font-semibold italic text-slate-100">
          {renderInlineFormatted(
            part.slice(3, -3),
            onInspectCard,
            `${key}-bi`,
          )}
        </strong>
      );
    }

    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={key} className="font-semibold text-slate-100">
          {renderInlineFormatted(part.slice(2, -2), onInspectCard, `${key}-b`)}
        </strong>
      );
    }

    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return (
        <em key={key} className="italic text-slate-300">
          {renderInlineFormatted(part.slice(1, -1), onInspectCard, `${key}-i`)}
        </em>
      );
    }

    // Clean up awkward spaces before punctuation that models sometimes emit after [[Card]]
    const cleaned = idx > 0 ? part.replace(/^\s+([,.;:!?])/, "$1") : part;
    return <React.Fragment key={key}>{cleaned}</React.Fragment>;
  });
}

/**
 * Full structured Markdown block renderer for Agent messages:
 * Supports headings (#, ##, ###), horizontal dividers (---),
 * bullet lists (* or -) with real indentation and nested items,
 * numbered lists (1. 2.), fenced code blocks (```), and paragraphs.
 */
function renderMarkdownContent(
  text: string,
  onInspectCard: (cardName: string) => void,
): React.ReactNode {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // Skip empty lines
    if (!trimmed) {
      i++;
      continue;
    }

    // Fenced code block ```
    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // skip closing ```
      blocks.push(
        <pre
          key={`code-${i}`}
          className="my-2 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/90 p-2.5 text-[11px] font-mono text-slate-200"
        >
          <code>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    // Horizontal rule --- or *** or ___
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push(
        <hr key={`hr-${i}`} className="my-2.5 border-slate-800/90" />,
      );
      i++;
      continue;
    }

    // Headings #, ##, ###, ####
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const content = headingMatch[2];
      const headingClass =
        level === 1
          ? "text-sm font-bold text-white mt-3 mb-1.5"
          : level === 2
            ? "text-[13px] font-bold text-slate-100 mt-3 mb-1"
            : "text-xs font-bold text-sky-300 mt-2.5 mb-1";
      blocks.push(
        <div key={`h-${i}`} className={headingClass}>
          {renderInlineFormatted(content, onInspectCard, `h-${i}`)}
        </div>,
      );
      i++;
      continue;
    }

    // Unordered list (* or - or •)
    if (/^\s*(?:[*-]|•)\s+/.test(rawLine)) {
      const items: { indent: number; content: string; lineIdx: number }[] = [];
      while (i < lines.length) {
        const l = lines[i];
        const ulMatch = l.match(/^(\s*)(?:[*-]|•)\s+(.+)$/);
        if (ulMatch) {
          items.push({
            indent: ulMatch[1].length,
            content: ulMatch[2].trim(),
            lineIdx: i,
          });
          i++;
        } else if (
          l.trim() &&
          items.length > 0 &&
          !/^(?:#{1,4}\s+|\d+\.\s+|---|\*\*\*|```)/.test(l.trim())
        ) {
          // Continuation line of previous bullet
          items[items.length - 1].content += " " + l.trim();
          i++;
        } else {
          break;
        }
      }
      blocks.push(
        <ul
          key={`ul-${i}`}
          className="my-1.5 space-y-1.5 pl-4 list-disc marker:text-sky-400"
        >
          {items.map((item) => (
            <li
              key={`li-${item.lineIdx}`}
              className={`leading-relaxed text-slate-200 pl-0.5 ${
                item.indent >= 2 ? "ml-4 list-[circle] marker:text-slate-400" : ""
              }`}
            >
              {renderInlineFormatted(
                item.content,
                onInspectCard,
                `ul-${item.lineIdx}`,
              )}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // Ordered list (1. 2. etc.)
    const olFirst = rawLine.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (olFirst) {
      const startNum = parseInt(olFirst[2], 10) || 1;
      const items: { num: number; content: string; subBullets: string[]; lineIdx: number }[] = [];
      while (i < lines.length) {
        const l = lines[i];
        const olMatch = l.match(/^(\s*)(\d+)\.\s+(.+)$/);
        if (olMatch) {
          items.push({
            num: parseInt(olMatch[2], 10) || 1,
            content: olMatch[3].trim(),
            subBullets: [],
            lineIdx: i,
          });
          i++;
          // Collect any immediately following bullet points belonging to this numbered item
          while (i < lines.length) {
            const nextL = lines[i];
            const subMatch = nextL.match(/^\s*(?:[*-]|•)\s+(.+)$/);
            if (subMatch) {
              items[items.length - 1].subBullets.push(subMatch[1].trim());
              i++;
            } else if (!nextL.trim()) {
              i++;
              break;
            } else {
              break;
            }
          }
        } else {
          break;
        }
      }
      blocks.push(
        <ol
          key={`ol-${i}`}
          start={startNum}
          className="my-2 space-y-2 pl-5 list-decimal marker:text-sky-400 marker:font-semibold"
        >
          {items.map((item) => (
            <li
              key={`oli-${item.lineIdx}`}
              value={item.num}
              className="leading-relaxed text-slate-200 pl-0.5"
            >
              <div>
                {renderInlineFormatted(
                  item.content,
                  onInspectCard,
                  `ol-${item.lineIdx}`,
                )}
              </div>
              {item.subBullets.length > 0 && (
                <ul className="mt-1.5 space-y-1 pl-4 list-disc marker:text-sky-400/80">
                  {item.subBullets.map((sb, sIdx) => (
                    <li
                      key={`ol-sub-${item.lineIdx}-${sIdx}`}
                      className="leading-relaxed text-slate-200 pl-0.5"
                    >
                      {renderInlineFormatted(
                        sb,
                        onInspectCard,
                        `ol-sub-${item.lineIdx}-${sIdx}`,
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    // Standard paragraph: merge consecutive plain lines
    const paraLines: string[] = [trimmed];
    i++;
    while (i < lines.length) {
      const nextTrim = lines[i].trim();
      if (
        !nextTrim ||
        nextTrim.startsWith("```") ||
        /^(?:-{3,}|\*{3,}|_{3,})$/.test(nextTrim) ||
        /^(#{1,4})\s+/.test(nextTrim) ||
        /^\s*(?:[*-]|•)\s+/.test(lines[i]) ||
        /^\s*\d+\.\s+/.test(lines[i])
      ) {
        break;
      }
      paraLines.push(nextTrim);
      i++;
    }
    blocks.push(
      <p key={`p-${i}`} className="my-1.5 leading-relaxed text-slate-200">
        {renderInlineFormatted(paraLines.join(" "), onInspectCard, `p-${i}`)}
      </p>,
    );
  }

  return <div className="space-y-1">{blocks}</div>;
}

function downsampleTo16kPCMBase64(
  input: Float32Array,
  inputSampleRate: number,
): string {
  const targetRate = 16000;
  const ratio = inputSampleRate / targetRate;
  const outLength = Math.max(1, Math.floor(input.length / ratio));
  const pcm16 = new Int16Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const srcIdx = Math.min(input.length - 1, Math.floor(i * ratio));
    const sample = Math.max(-1, Math.min(1, input[srcIdx]));
    pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  const bytes = new Uint8Array(pcm16.buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

export const AssistantAgentWidget: React.FC<Props> = ({
  formatId,
  activeTab,
  activeDeck,
  settings,
  onOpenSettings,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [interactionId, setInteractionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspectedCard, setInspectedCard] = useState<Card | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Gemini 3.8 Live Voice Mode state
  const [voiceActive, setVoiceActive] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [liveUserTranscript, setLiveUserTranscript] = useState("");
  const [liveAgentTranscript, setLiveAgentTranscript] = useState("");
  const [liveToolCalls, setLiveToolCalls] = useState<AgentToolCallTrace[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const captureCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const playbackCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const isMutedRef = useRef<boolean>(false);
  const pendingUserTranscriptRef = useRef<string>("");
  const pendingAgentTranscriptRef = useRef<string>("");
  const pendingToolCallsRef = useRef<AgentToolCallTrace[]>([]);

  const ready = !!(
    settings?.has_gemini_api_key || settings?.ai_provider === "vertex-ai"
  );

  useEffect(() => {
    isMutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading, isOpen]);

  const stopPlaybackQueue = useCallback(() => {
    for (const src of activeSourcesRef.current) {
      try {
        src.stop();
        src.disconnect();
      } catch {
        // ignore already stopped source
      }
    }
    activeSourcesRef.current = [];
    if (playbackCtxRef.current) {
      nextPlayTimeRef.current = playbackCtxRef.current.currentTime;
    }
  }, []);

  const flushLiveTurnToMessages = useCallback(() => {
    const userTxt = pendingUserTranscriptRef.current.trim();
    const agentTxt = pendingAgentTranscriptRef.current.trim();
    const tools = [...pendingToolCallsRef.current];

    if (!userTxt && !agentTxt && tools.length === 0) return;

    setMessages((prev) => {
      const next = [...prev];
      if (userTxt) {
        next.push({ role: "user", content: userTxt });
      }
      if (agentTxt || tools.length > 0) {
        next.push({
          role: "assistant",
          content: agentTxt || "(Risposta vocale completata)",
          tool_calls: tools,
          model_id: "gemini-3.8-live",
        });
      }
      return next;
    });

    pendingUserTranscriptRef.current = "";
    pendingAgentTranscriptRef.current = "";
    pendingToolCallsRef.current = [];
    setLiveUserTranscript("");
    setLiveAgentTranscript("");
    setLiveToolCalls([]);
  }, []);

  const stopVoiceSession = useCallback(() => {
    flushLiveTurnToMessages();
    stopPlaybackQueue();

    if (processorRef.current) {
      try {
        processorRef.current.disconnect();
      } catch {
        // ignore
      }
      processorRef.current = null;
    }
    if (captureCtxRef.current) {
      void captureCtxRef.current.close().catch(() => {});
      captureCtxRef.current = null;
    }
    if (micStreamRef.current) {
      micStreamRef.current.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
    }
    if (playbackCtxRef.current) {
      void playbackCtxRef.current.close().catch(() => {});
      playbackCtxRef.current = null;
    }
    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "stop" }));
        }
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }

    setVoiceActive(false);
    setVoiceStatus("idle");
    setIsMuted(false);
  }, [flushLiveTurnToMessages, stopPlaybackQueue]);

  useEffect(() => {
    return () => {
      stopVoiceSession();
    };
  }, [stopVoiceSession]);

  const enqueueAudioChunk = useCallback(
    (base64Pcm: string, sampleRate = 24000) => {
      if (!playbackCtxRef.current) {
        playbackCtxRef.current = new AudioContext({ sampleRate });
        nextPlayTimeRef.current = playbackCtxRef.current.currentTime;
      }
      const ctx = playbackCtxRef.current;
      if (ctx.state === "suspended") {
        void ctx.resume();
      }

      const binary = window.atob(base64Pcm);
      const byteLen = binary.length;
      const bytes = new Uint8Array(byteLen);
      for (let i = 0; i < byteLen; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const pcm16 = new Int16Array(
        bytes.buffer,
        0,
        Math.floor(byteLen / 2),
      );
      if (pcm16.length === 0) return;

      const float32 = new Float32Array(pcm16.length);
      for (let i = 0; i < pcm16.length; i++) {
        float32[i] = pcm16[i] / 32768;
      }

      const audioBuffer = ctx.createBuffer(1, float32.length, sampleRate);
      audioBuffer.getChannelData(0).set(float32);

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);

      const startAt = Math.max(ctx.currentTime + 0.015, nextPlayTimeRef.current);
      source.start(startAt);
      nextPlayTimeRef.current = startAt + audioBuffer.duration;
      activeSourcesRef.current.push(source);
      setVoiceStatus("speaking");

      source.onended = () => {
        activeSourcesRef.current = activeSourcesRef.current.filter(
          (s) => s !== source,
        );
        if (activeSourcesRef.current.length === 0) {
          setVoiceStatus((prev) => (prev === "speaking" ? "listening" : prev));
        }
      };
    },
    [],
  );

  const startVoiceSession = async () => {
    if (!ready) {
      onOpenSettings();
      return;
    }
    setError(null);
    setVoiceActive(true);
    setVoiceStatus("connecting");
    setLiveUserTranscript("");
    setLiveAgentTranscript("");
    setLiveToolCalls([]);
    pendingUserTranscriptRef.current = "";
    pendingAgentTranscriptRef.current = "";
    pendingToolCallsRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      micStreamRef.current = stream;

      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const params = new URLSearchParams({
        format_id: formatId,
        active_tab: activeTab,
      });
      if (activeDeck?.id) params.set("active_deck_id", String(activeDeck.id));
      if (activeDeck?.name) params.set("active_deck_name", activeDeck.name);

      const wsUrl = `${proto}//${window.location.host}/api/ai/agent/live?${params.toString()}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // Initialize microphone capture pipeline
        const captureCtx = new AudioContext();
        captureCtxRef.current = captureCtx;
        const source = captureCtx.createMediaStreamSource(stream);
        const processor = captureCtx.createScriptProcessor(4096, 1, 1);
        processorRef.current = processor;

        processor.onaudioprocess = (ev) => {
          if (
            isMutedRef.current ||
            !wsRef.current ||
            wsRef.current.readyState !== WebSocket.OPEN
          ) {
            return;
          }
          const inputData = ev.inputBuffer.getChannelData(0);
          const b64 = downsampleTo16kPCMBase64(
            inputData,
            captureCtx.sampleRate,
          );
          wsRef.current.send(JSON.stringify({ type: "audio", data: b64 }));
        };

        source.connect(processor);
        processor.connect(captureCtx.destination);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "status") {
            if (msg.status === "listening") setVoiceStatus("listening");
            else if (msg.status === "thinking") setVoiceStatus("thinking");
          } else if (msg.type === "audio" && msg.data) {
            enqueueAudioChunk(msg.data, msg.sample_rate || 24000);
          } else if (msg.type === "input_transcript" && msg.text) {
            pendingUserTranscriptRef.current += msg.text;
            setLiveUserTranscript(pendingUserTranscriptRef.current.trim());
          } else if (msg.type === "output_transcript" && msg.text) {
            pendingAgentTranscriptRef.current += msg.text;
            setLiveAgentTranscript(pendingAgentTranscriptRef.current.trim());
          } else if (msg.type === "tool_call") {
            const tc: AgentToolCallTrace = {
              id: msg.id,
              tool_name: msg.tool_name,
              arguments: msg.arguments || {},
              summary: msg.summary || msg.tool_name,
              status: msg.status || "completed",
            };
            const existingIdx = pendingToolCallsRef.current.findIndex(
              (x) => x.id === tc.id,
            );
            if (existingIdx >= 0) {
              pendingToolCallsRef.current[existingIdx] = tc;
            } else {
              pendingToolCallsRef.current.push(tc);
            }
            setLiveToolCalls([...pendingToolCallsRef.current]);
          } else if (msg.type === "interrupted") {
            stopPlaybackQueue();
            setVoiceStatus("listening");
          } else if (msg.type === "turn_complete") {
            flushLiveTurnToMessages();
            if (activeSourcesRef.current.length === 0) {
              setVoiceStatus("listening");
            }
          } else if (msg.type === "error") {
            setError(msg.message || "Errore nella sessione vocale Gemini 3.8 Live.");
            setVoiceStatus("error");
          }
        } catch {
          // ignore malformed event
        }
      };

      ws.onerror = () => {
        setError("Errore di connessione WebSocket con Gemini 3.8 Live.");
        setVoiceStatus("error");
      };

      ws.onclose = () => {
        flushLiveTurnToMessages();
      };
    } catch (err: any) {
      setError(
        err?.message ||
          "Impossibile accedere al microfono per la modalità vocale Live.",
      );
      stopVoiceSession();
    }
  };

  const toggleMute = () => {
    const nextMuted = !isMuted;
    setIsMuted(nextMuted);
    if (
      nextMuted &&
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN
    ) {
      wsRef.current.send(JSON.stringify({ type: "audio_stream_end" }));
    }
  };

  const handleInspectCard = async (cardName: string) => {
    const clean = cardName.trim();
    const fromDeck = activeDeck?.cards.find(
      (c) =>
        c.card_name.toLowerCase() === clean.toLowerCase() ||
        c.card_name.split(" // ")[0].toLowerCase() === clean.toLowerCase(),
    )?.card;
    if (fromDeck) {
      setInspectedCard(fromDeck);
      return;
    }
    try {
      const res = await api.searchCards({
        format_id: formatId,
        q: clean,
        page_size: 8,
      });
      const hit =
        res.cards.find(
          (c) =>
            c.name.toLowerCase() === clean.toLowerCase() ||
            c.name.split(" // ")[0].toLowerCase() === clean.toLowerCase(),
        ) || res.cards[0];
      if (hit) setInspectedCard(hit);
    } catch {
      // ignore search error
    }
  };

  const sendMessage = async (textToSend?: string) => {
    const trimmed = (textToSend ?? input).trim();
    if (!trimmed || loading) return;

    // If voice mode is active, send text directly into the Live session
    if (
      voiceActive &&
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN
    ) {
      pendingUserTranscriptRef.current = trimmed;
      setLiveUserTranscript(trimmed);
      wsRef.current.send(JSON.stringify({ type: "text", text: trimmed }));
      if (!textToSend) setInput("");
      return;
    }

    const userMsg: AgentChatMessage = { role: "user", content: trimmed };
    const prevHistory = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    setMessages((prev) => [...prev, userMsg]);
    if (!textToSend) setInput("");
    setLoading(true);
    setError(null);

    try {
      const response = await api.agentChat({
        message: trimmed,
        previous_interaction_id: interactionId,
        history: prevHistory,
        format_id: formatId,
        active_tab: activeTab,
        active_deck_id: activeDeck?.id ?? null,
        active_deck_name: activeDeck?.name ?? null,
      });
      setInteractionId(response.interaction_id || null);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.reply,
          tool_calls: response.tool_calls,
          model_id: response.model_id,
          duration_ms: response.duration_ms,
        },
      ]);
    } catch (e: any) {
      setError(e.message || "Errore durante la comunicazione con l'agente.");
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setMessages([]);
    setInteractionId(null);
    setError(null);
  };

  const renderToolBadge = (tc: AgentToolCallTrace, tIdx: number) => {
    const isErr = tc.status === "error";
    const isRunning = tc.status === "running";
    const badgeColors = isErr
      ? "border-amber-700/70 bg-amber-950/45 text-amber-200"
      : isRunning
        ? "border-sky-700/70 bg-sky-950/45 text-sky-200"
        : "border-emerald-800/70 bg-emerald-950/40 text-emerald-200";

    return (
      <span
        key={`${tc.id || tc.tool_name}-${tIdx}`}
        className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] ${badgeColors}`}
        title={`Tool: ${tc.tool_name}(${JSON.stringify(tc.arguments)})`}
      >
        <Wrench
          size={11}
          className={
            isErr
              ? "text-amber-400 shrink-0"
              : isRunning
                ? "text-sky-400 shrink-0"
                : "text-emerald-400 shrink-0"
          }
        />
        <span className="font-medium">
          {TOOL_LABELS[tc.tool_name] || tc.tool_name}:
        </span>
        <span className="opacity-90 truncate max-w-[230px]">{tc.summary}</span>
        {isRunning ? (
          <Loader2 size={11} className="animate-spin text-sky-400 shrink-0" />
        ) : isErr ? (
          <AlertTriangle size={11} className="text-amber-400 shrink-0" />
        ) : (
          <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />
        )}
      </span>
    );
  };

  const quickPrompts = activeDeck
    ? [
        `Analizza punti deboli e possibili migliorie per il mio mazzo "${activeDeck.name}"`,
        `Come si posiziona "${activeDeck.name}" contro i principali archetipi del metagame ${formatId.toUpperCase()}?`,
        `Verifica se la manabase di "${activeDeck.name}" rispetta i requisiti di Karsten`,
        `Come funzionano le modalità di AI Studio e il simulatore di Playtest?`,
      ]
    : [
        `Quali sono i migliori archetipi del metagame ${formatId.toUpperCase()} in questo momento?`,
        `Mostrami i miei mazzi salvati e dimmi su quale lavorare`,
        `Spiegami come funzionano le abilità di mana di Gloomlake Verge secondo le regole`,
        `Come funziona la modalità "Migliora mazzo" e il resto dell'app?`,
      ];

  return (
    <>
      {/* Floating Action Button in bottom-right */}
      {!isOpen && (
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          aria-label="Apri AetherDeck Agent"
          className="fixed bottom-5 right-5 z-40 flex items-center gap-2.5 rounded-full border border-sky-400/60 bg-slate-900/95 px-4 py-3 text-sm font-semibold text-slate-100 shadow-xl shadow-black/60 hover:border-sky-300 hover:bg-slate-800 transition"
        >
          <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-sky-500/20 text-sky-300">
            <Bot size={17} />
            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          <span>Agente AI</span>
        </button>
      )}

      {/* Agent Panel */}
      {isOpen && (
        <aside
          aria-label="AetherDeck AI Agent"
          className={`fixed bottom-4 right-4 z-40 flex flex-col rounded-xl border border-slate-700/90 bg-slate-950/95 shadow-2xl shadow-black/80 backdrop-blur-md transition-all ${
            isExpanded
              ? "w-[96vw] md:w-[760px] h-[85vh]"
              : "w-[94vw] sm:w-[460px] h-[640px] max-h-[84vh]"
          }`}
        >
          {/* Header */}
          <div className="flex items-center justify-between gap-2 border-b border-slate-800 px-4 py-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-sky-500/40 bg-sky-500/15 text-sky-300">
                <Bot size={18} />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-bold text-slate-100 truncate">
                    AetherDeck Agent
                  </h2>
                  <span className="rounded-full border border-emerald-700/70 bg-emerald-950/50 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                    Tools attivi
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 truncate">
                  Formato:{" "}
                  <strong className="text-slate-200 uppercase">
                    {formatId}
                  </strong>
                  {activeDeck ? (
                    <>
                      {" "}
                      · Mazzo attivo:{" "}
                      <strong className="text-sky-300">{activeDeck.name}</strong>
                    </>
                  ) : null}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() =>
                  voiceActive ? stopVoiceSession() : void startVoiceSession()
                }
                title={
                  voiceActive
                    ? "Termina modalità vocale Live"
                    : "Avvia modalità vocale con Gemini 3.8 Live"
                }
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition ${
                  voiceActive
                    ? "border-rose-500/70 bg-rose-500/20 text-rose-200 hover:bg-rose-500/30"
                    : "border-sky-500/50 bg-sky-500/15 text-sky-200 hover:border-sky-400 hover:bg-sky-500/25"
                }`}
              >
                <AudioLines size={13} />
                <span className="hidden sm:inline">
                  {voiceActive ? "Live Attivo" : "Voice Live"}
                </span>
              </button>
              {messages.length > 0 && !voiceActive && (
                <button
                  type="button"
                  onClick={handleClear}
                  title="Nuova conversazione"
                  className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                >
                  <Trash2 size={15} />
                </button>
              )}
              <button
                type="button"
                onClick={() => setIsExpanded((v) => !v)}
                title={isExpanded ? "Riduci pannello" : "Espandi pannello"}
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                {isExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (voiceActive) stopVoiceSession();
                  setIsOpen(false);
                }}
                title="Chiudi agente"
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* ChatGPT-style Voice Mode Overlay when Gemini 3.8 Live is active */}
          {voiceActive ? (
            <div className="flex-1 flex flex-col items-center justify-between p-5 bg-gradient-to-b from-slate-950 via-slate-900/95 to-slate-950 overflow-y-auto">
              <div className="w-full flex items-center justify-between text-xs text-slate-400">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-500/40 bg-sky-950/60 px-2.5 py-1 text-[11px] font-medium text-sky-300">
                  <Sparkles size={12} /> Gemini 3.8 Live · Audio bidirezionale
                </span>
                <span className="text-[11px] text-slate-400">
                  {isMuted ? "Microfono in muto" : "Microfono attivo (16kHz PCM)"}
                </span>
              </div>

              {/* Central Animated Voice Orb */}
              <div className="my-auto flex flex-col items-center text-center max-w-md w-full py-4 space-y-5">
                <div className="relative flex items-center justify-center h-36 w-36">
                  <span
                    className={`absolute inset-0 rounded-full transition-all duration-500 ${
                      voiceStatus === "speaking"
                        ? "bg-sky-500/25 animate-ping"
                        : voiceStatus === "thinking"
                          ? "bg-amber-500/20 animate-pulse"
                          : voiceStatus === "listening" && !isMuted
                            ? "bg-emerald-500/20 animate-pulse"
                            : "bg-slate-800/40"
                    }`}
                  />
                  <span
                    className={`absolute inset-3 rounded-full border transition-all duration-300 ${
                      voiceStatus === "speaking"
                        ? "border-sky-400/60 bg-sky-500/20 scale-105"
                        : voiceStatus === "thinking"
                          ? "border-amber-400/60 bg-amber-500/15"
                          : voiceStatus === "listening" && !isMuted
                            ? "border-emerald-400/60 bg-emerald-500/15"
                            : "border-slate-700 bg-slate-900"
                    }`}
                  />
                  <div
                    className={`relative z-10 flex h-24 w-24 items-center justify-center rounded-full shadow-2xl transition-all ${
                      voiceStatus === "speaking"
                        ? "bg-gradient-to-br from-sky-400 to-indigo-600 text-white shadow-sky-500/40"
                        : voiceStatus === "thinking"
                          ? "bg-gradient-to-br from-amber-400 to-orange-600 text-white shadow-amber-500/30"
                          : voiceStatus === "listening" && !isMuted
                            ? "bg-gradient-to-br from-emerald-400 to-teal-600 text-slate-950 shadow-emerald-500/30"
                            : "bg-slate-800 text-slate-300"
                    }`}
                  >
                    {voiceStatus === "connecting" ||
                    voiceStatus === "thinking" ? (
                      <Loader2 size={36} className="animate-spin" />
                    ) : voiceStatus === "speaking" ? (
                      <Volume2 size={38} className="animate-bounce" />
                    ) : isMuted ? (
                      <MicOff size={34} />
                    ) : (
                      <AudioLines size={38} />
                    )}
                  </div>
                </div>

                <div className="space-y-1">
                  <p className="text-sm font-bold text-slate-100">
                    {voiceStatus === "connecting"
                      ? "Connessione a Gemini 3.8 Live..."
                      : voiceStatus === "thinking"
                        ? "Consultazione tool e analisi in corso..."
                        : voiceStatus === "speaking"
                          ? "AetherDeck Agent sta parlando..."
                          : isMuted
                            ? "Microfono disattivato"
                            : "In ascolto · Parla liberamente"}
                  </p>
                  <p className="text-xs text-slate-400">
                    Puoi chiedere analisi sul tuo mazzo, ruling Scryfall,
                    metagame o simulazioni di cambi a voce.
                  </p>
                </div>

                {/* Live Tool Calls executed during voice turn */}
                {liveToolCalls.length > 0 && (
                  <div className="flex flex-wrap justify-center gap-1.5 w-full">
                    {liveToolCalls.map((tc, idx) => renderToolBadge(tc, idx))}
                  </div>
                )}

                {/* Real-time transcripts */}
                {(liveUserTranscript || liveAgentTranscript) && (
                  <div className="w-full rounded-xl border border-slate-800 bg-slate-900/80 p-3 text-left space-y-2 max-h-40 overflow-y-auto">
                    {liveUserTranscript && (
                      <p className="text-xs text-sky-300">
                        <strong className="font-semibold text-sky-200">
                          Tu:{" "}
                        </strong>
                        {liveUserTranscript}
                      </p>
                    )}
                    {liveAgentTranscript && (
                      <div className="text-xs text-slate-200">
                        <strong className="font-semibold text-emerald-300">
                          Agente:{" "}
                        </strong>
                        {renderInlineFormatted(
                          liveAgentTranscript,
                          handleInspectCard,
                          "voice-live",
                        )}
                      </div>
                    )}
                  </div>
                )}

                {error && (
                  <div className="w-full rounded-lg border border-rose-800 bg-rose-950/60 px-3 py-2 text-xs text-rose-200">
                    {error}
                  </div>
                )}
              </div>

              {/* ChatGPT-style Bottom Voice Controls */}
              <div className="w-full flex items-center justify-center gap-4 pt-2 border-t border-slate-800/80">
                <button
                  type="button"
                  onClick={toggleMute}
                  className={`flex h-12 w-12 items-center justify-center rounded-full border transition ${
                    isMuted
                      ? "border-amber-500/70 bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
                      : "border-slate-700 bg-slate-800 text-slate-100 hover:bg-slate-700"
                  }`}
                  title={isMuted ? "Riattiva microfono" : "Silenzia microfono"}
                >
                  {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
                </button>

                <button
                  type="button"
                  onClick={stopVoiceSession}
                  className="flex items-center gap-2 rounded-full bg-rose-600 hover:bg-rose-500 px-5 py-3 text-xs font-bold text-white shadow-lg shadow-rose-950/60 transition"
                  title="Termina conversazione vocale"
                >
                  <PhoneOff size={16} />
                  <span>Termina Voice Mode</span>
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Messages Area */}
              <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-4 space-y-4 text-sm"
              >
                {!ready && (
                  <div className="rounded-lg border border-amber-700/70 bg-amber-950/30 p-3 text-xs text-amber-200 flex items-center justify-between gap-2">
                    <span>
                      Configura la Gemini API Key per utilizzare l'Agente AI.
                    </span>
                    <button
                      type="button"
                      onClick={onOpenSettings}
                      className="btn-secondary text-xs shrink-0"
                    >
                      Impostazioni
                    </button>
                  </div>
                )}

                {messages.length === 0 && (
                  <div className="space-y-4">
                    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3.5 space-y-2">
                      <p className="text-xs font-semibold text-sky-300 flex items-center gap-1.5">
                        <Sparkles size={14} /> Agente strategico con Tools &
                        Gemini 3.8 Live Voice
                      </p>
                      <p className="text-xs text-slate-300 leading-relaxed">
                        Posso ispezionare i tuoi mazzi salvati, calcolare le
                        fonti di Karsten, simulare cambi di carte, consultare le
                        liste di consenso del metagame, verificare testi Oracle
                        e ruling ufficiali Scryfall o parlare con te a voce in
                        tempo reale con <strong>Gemini 3.8 Live</strong>.
                      </p>
                    </div>

                    <div className="space-y-2">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Domande rapide consigliate
                      </p>
                      <div className="grid grid-cols-1 gap-2">
                        {quickPrompts.map((q, i) => (
                          <button
                            key={i}
                            type="button"
                            disabled={!ready || loading}
                            onClick={() => void sendMessage(q)}
                            className="text-left rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs text-slate-200 hover:border-sky-500/60 hover:bg-slate-900 transition disabled:opacity-50"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex flex-col ${
                      msg.role === "user" ? "items-end" : "items-start"
                    }`}
                  >
                    {msg.role === "assistant" &&
                      msg.tool_calls &&
                      msg.tool_calls.length > 0 && (
                        <div className="mb-1.5 flex flex-wrap gap-1.5 max-w-[95%]">
                          {msg.tool_calls.map((tc, tIdx) =>
                            renderToolBadge(tc, tIdx),
                          )}
                        </div>
                      )}

                    <div
                      className={`max-w-[94%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed ${
                        msg.role === "user"
                          ? "bg-sky-600 text-white whitespace-pre-line"
                          : "border border-slate-800 bg-slate-900/90 text-slate-200"
                      }`}
                    >
                      {msg.role === "assistant"
                        ? renderMarkdownContent(msg.content, handleInspectCard)
                        : msg.content}
                    </div>
                  </div>
                ))}

                {loading && (
                  <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 text-xs text-slate-300">
                    <Loader2 size={15} className="animate-spin text-sky-400" />
                    <span>
                      L'agente sta consultando i tool (mazzi, metagame,
                      Oracle)…
                    </span>
                  </div>
                )}

                {error && (
                  <div className="rounded-lg border border-rose-800 bg-rose-950/50 px-3 py-2 text-xs text-rose-200">
                    {error}
                  </div>
                )}
              </div>

              {/* Input Bar with ChatGPT-style Voice Mode Button */}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void sendMessage();
                }}
                className="border-t border-slate-800 p-3 flex items-end gap-2"
              >
                <textarea
                  rows={2}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder="Chiedi sui tuoi mazzi, strategia, metagame, ruling o sull'app…"
                  disabled={!ready || loading}
                  className="field flex-1 resize-none text-xs py-2"
                />
                <button
                  type="button"
                  disabled={!ready || loading}
                  onClick={() => void startVoiceSession()}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-sky-500/50 bg-sky-500/15 text-sky-300 hover:border-sky-400 hover:bg-sky-500/25 transition disabled:opacity-40"
                  title="Avvia conversazione vocale in tempo reale (Gemini 3.8 Live)"
                  aria-label="Avvia modalità vocale Gemini 3.8 Live"
                >
                  <AudioLines size={17} />
                </button>
                <button
                  type="submit"
                  disabled={!ready || loading || !input.trim()}
                  className="btn-primary h-9 px-3 shrink-0"
                  title="Invia messaggio"
                >
                  <Send size={15} />
                </button>
              </form>
            </>
          )}
        </aside>
      )}

      {inspectedCard && (
        <CardInfoModal
          card={inspectedCard}
          formatId={formatId}
          onClose={() => setInspectedCard(null)}
        />
      )}
    </>
  );
};
