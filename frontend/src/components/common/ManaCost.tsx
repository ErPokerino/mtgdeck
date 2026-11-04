import React from "react";

/**
 * Converte un token Scryfall es. "{W}", "{2/U}", "{B/P}", "{T}" nella classe CSS ufficiale di mana-font.
 */
function tokenToManaClass(rawToken: string): string {
  const clean = rawToken.replace(/[{}]/g, "").trim().toLowerCase();
  if (!clean) return "";
  if (clean === "t") return "ms ms-tap ms-cost ms-shadow";
  if (clean === "q") return "ms ms-untap ms-cost ms-shadow";
  // Ibridi o Phyrexian es. "w/u" -> "ms-wu", "w/p" -> "ms-wp"
  const normalized = clean.replace(/\//g, "");
  return `ms ms-${normalized} ms-cost ms-shadow`;
}

interface ManaCostProps {
  cost?: string | null;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
}

export const ManaCost: React.FC<ManaCostProps> = ({
  cost,
  size = "sm",
  className = "",
}) => {
  if (!cost) return null;

  const sizeClass =
    size === "xs"
      ? "text-[11px]"
      : size === "sm"
        ? "text-[13px]"
        : size === "md"
          ? "text-[15px]"
          : "text-[18px]";

  // Gestisce anche carte split o DFC " {1}{R} // {2}{U} "
  const parts = cost.split("//");

  return (
    <span
      className={`inline-flex items-center gap-0.5 flex-wrap ${sizeClass} ${className}`}
    >
      {parts.map((part, pIdx) => {
        const matches = part.match(/\{[^}]+\}/g) || [];
        return (
          <React.Fragment key={pIdx}>
            {pIdx > 0 && (
              <span className="text-slate-400 mx-1 font-mono-tech text-xs">
                //
              </span>
            )}
            {matches.map((tok, idx) => (
              <i key={idx} className={tokenToManaClass(tok)} title={tok} />
            ))}
          </React.Fragment>
        );
      })}
    </span>
  );
};

/**
 * Renderizza il testo Oracle sostituendo i simboli {W}, {T}, {2}{B} con le icone ufficiali mana-font.
 */
export const OracleTextRenderer: React.FC<{
  text?: string | null;
  className?: string;
}> = ({ text, className = "" }) => {
  if (!text) return null;
  const paragraphs = text.split("\n");

  return (
    <div className={`space-y-1.5 leading-relaxed ${className}`}>
      {paragraphs.map((line, lineIdx) => {
        if (line.trim() === "//") {
          return <hr key={lineIdx} className="border-slate-700/70 my-2" />;
        }
        const segments = line.split(/(\{[^}]+\})/g);
        return (
          <p key={lineIdx} className="text-slate-200">
            {segments.map((seg, sIdx) => {
              if (seg.startsWith("{") && seg.endsWith("}")) {
                return (
                  <i
                    key={sIdx}
                    className={`${tokenToManaClass(seg)} text-[12px] mx-0.5 align-baseline`}
                    title={seg}
                  />
                );
              }
              return <React.Fragment key={sIdx}>{seg}</React.Fragment>;
            })}
          </p>
        );
      })}
    </div>
  );
};

export const ColorBadges: React.FC<{
  colors: string[];
  size?: "sm" | "md";
}> = ({ colors, size = "sm" }) => {
  if (!colors || colors.length === 0) {
    return (
      <span className="inline-flex items-center" title="Colorless">
        <i
          className={`ms ms-c ms-cost ms-shadow ${size === "sm" ? "text-xs" : "text-sm"}`}
        />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5">
      {colors.map((c) => (
        <i
          key={c}
          className={`ms ms-${c.toLowerCase()} ms-cost ms-shadow ${
            size === "sm" ? "text-xs" : "text-sm"
          }`}
          title={c}
        />
      ))}
    </span>
  );
};

export const SetSymbol: React.FC<{
  setCode: string;
  rarity?: string;
  setName?: string;
  className?: string;
}> = ({ setCode, rarity = "common", setName, className = "" }) => {
  const rarityClass =
    rarity === "mythic"
      ? "ss-mythic"
      : rarity === "rare"
        ? "ss-rare"
        : rarity === "uncommon"
          ? "ss-uncommon"
          : "ss-common";

  return (
    <i
      className={`ss ss-${setCode.toLowerCase()} ${rarityClass} ss-grad ${className}`}
      title={
        setName
          ? `${setName} (${setCode.toUpperCase()})`
          : setCode.toUpperCase()
      }
    />
  );
};
