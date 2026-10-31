/** Signature de l'usager au doigt (MOB-03) : la toile produit une image PNG ; « signature impossible » reste possible. */
import { useEffect, useRef, useState, type PointerEvent } from "react";

export function Signature({ onChange }: { onChange: (signature: Blob | null) => void }) {
  const toile = useRef<HTMLCanvasElement>(null);
  const trace = useRef(false);
  const [signe, setSigne] = useState(false);

  useEffect(() => {
    const contexte = toile.current?.getContext("2d");
    if (!contexte) return;
    contexte.lineWidth = 3;
    contexte.lineCap = "round";
    contexte.strokeStyle = "#000";
  }, []);

  const position = (e: PointerEvent<HTMLCanvasElement>) => {
    const zone = e.currentTarget.getBoundingClientRect();
    return { x: ((e.clientX - zone.left) * e.currentTarget.width) / zone.width, y: ((e.clientY - zone.top) * e.currentTarget.height) / zone.height };
  };

  const terminer = () => {
    if (!trace.current) return;
    trace.current = false;
    setSigne(true);
    toile.current?.toBlob((blob) => onChange(blob), "image/png");
  };

  const effacer = () => {
    const contexte = toile.current?.getContext("2d");
    if (contexte && toile.current) contexte.clearRect(0, 0, toile.current.width, toile.current.height);
    setSigne(false);
    onChange(null);
  };

  return (
    <fieldset className="signature">
      <legend>Signature de l'usager</legend>
      <canvas
        ref={toile}
        width={600}
        height={200}
        className="signature__toile"
        role="img"
        aria-label={signe ? "Signature tracée" : "Zone de signature : l'usager signe avec le doigt"}
        onPointerDown={(e) => {
          trace.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          const p = position(e);
          const contexte = e.currentTarget.getContext("2d");
          contexte?.beginPath();
          contexte?.moveTo(p.x, p.y);
        }}
        onPointerMove={(e) => {
          if (!trace.current) return;
          const p = position(e);
          const contexte = e.currentTarget.getContext("2d");
          contexte?.lineTo(p.x, p.y);
          contexte?.stroke();
        }}
        onPointerUp={terminer}
        onPointerLeave={terminer}
      />
      <button type="button" className="bouton bouton--lien" onClick={effacer}>
        Effacer la signature
      </button>
      <p className="aide">Sans signature (usager absent ou refus), indiquez-le dans les observations.</p>
    </fieldset>
  );
}
